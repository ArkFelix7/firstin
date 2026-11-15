"""Access geometry for fire pre-plans: ladder/aerial EDGES, STAGING polygon, ENTRY/EXIT points.

analyze_access(building_id) -> dict

Geometry comes from the Vexcel footprint polygon (so lines sit exactly on the wall); the vision
model only DECIDES (which numbered wall is accessible, where staging is, which doors are visible),
then a separate verification call checks the drawn geometry and anything that fails is dropped.

Vision calls (each cached in agent/cache/vision/<sha1>.json, so offline replay works):
  1. edges     - ortho crop with numbered footprint walls -> accessible yes/no + reason per wall
  2. staging   - ortho crop with accessible walls highlighted -> one tight polygon on paved ground
  3. entries   - the 4 obliques (facade views) in ONE call -> tight door bboxes with type
  4. verify    - drawn geometry + door crops -> yes/no per element
Coordinates: every `px` / `bbox` is in FULL-resolution pixels of the image named next to it
(base ortho/context image for edges/staging/ortho_point; the oblique for entry bboxes).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agent import config
from agent.tools import sources, vexcel

VERSION = "access-v1"
VERIFY = "VERIFY ON SITE"
HEADING = {"N": 0.0, "E": 90.0, "S": 180.0, "W": 270.0}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
VLM_MAX = 1568
MIN_EDGE_M = 6.0
ENTRY_TYPES = ("dock_door", "drive_in", "rollup", "entrance", "exit")
TYPE_NAME = {"dock_door": ("dock door", "dock doors"), "drive_in": ("drive-in door", "drive-in doors"),
             "rollup": ("roll-up door", "roll-up doors"), "entrance": ("entrance", "entrances"),
             "exit": ("exit door", "exit doors")}
TYPE_COLOR = {"dock_door": (255, 140, 0), "drive_in": (255, 215, 0), "rollup": (255, 99, 71),
              "entrance": (0, 220, 255), "exit": (255, 0, 200)}
EDGE_COLORS = [(255, 0, 0), (0, 200, 255), (255, 0, 255), (255, 165, 0), (0, 255, 0), (255, 255, 0),
               (148, 0, 211), (0, 128, 255), (255, 105, 180), (0, 255, 200), (200, 120, 0), (180, 255, 0)]


# =============================================================== geometry (pure, unit-tested)
def _dist_pt_seg(p, a, b) -> tuple[float, float]:
    """(distance, t in [0,1]) from point p to segment ab."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(p[0] - ax, p[1] - ay), 0.0
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy)), t


def _dp(pts: list, tol: float) -> list:
    if len(pts) < 3:
        return list(pts)
    a, b = pts[0], pts[-1]
    dmax, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        d, _ = _dist_pt_seg(pts[i], a, b)
        if d > dmax:
            dmax, idx = d, i
    if dmax <= tol:
        return [a, b]
    return _dp(pts[: idx + 1], tol)[:-1] + _dp(pts[idx:], tol)


def simplify_ring(ring: list, tol: float) -> list:
    """Douglas-Peucker on a closed ring (no repeated closing vertex in/out)."""
    pts = [tuple(map(float, p)) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 4:
        return pts
    i0 = 0
    i1 = max(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]))
    c1 = _dp(pts[i0: i1 + 1], tol)
    c2 = _dp(pts[i1:] + [pts[0]], tol)
    out = c1[:-1] + c2[:-1]
    # second pass: drop vertices that barely deviate from their neighbours' chord
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            d, _ = _dist_pt_seg(out[i], out[i - 1], out[(i + 1) % len(out)])
            if d < tol:
                out.pop(i)
                changed = True
                break
    return out


def point_in_poly(x: float, y: float, poly: list) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def poly_area(poly: list) -> float:
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2.0


def compass(bearing_deg: float) -> str:
    return COMPASS[int(((bearing_deg % 360) + 22.5) // 45) % 8]


def extract_edges(ring_px: list, gsd_m: float, min_len_m: float = MIN_EDGE_M) -> tuple[list, list]:
    """Footprint ring (image px, y down, north up) -> (simplified ring, candidate wall edges).

    Each edge: {id, i, a, b, len_m, normal (outward, px), bearing (outward normal, deg from N), side}.
    Edges shorter than min_len_m are not candidates (still part of the ring)."""
    simp = simplify_ring(ring_px, max(0.8 / gsd_m, 1.0))
    edges = []
    for i in range(len(simp)):
        a, b = simp[i], simp[(i + 1) % len(simp)]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L * gsd_m < min_len_m:
            continue
        dx, dy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = dy, -dx
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        eps = max(3.0, 0.5 / gsd_m)
        if point_in_poly(mx + nx * eps, my + ny * eps, simp):
            nx, ny = -nx, -ny
        bearing = math.degrees(math.atan2(nx, -ny)) % 360
        edges.append({"id": len(edges) + 1, "i": i, "a": [round(a[0], 1), round(a[1], 1)],
                      "b": [round(b[0], 1), round(b[1], 1)], "len_m": round(L * gsd_m, 1),
                      "normal": [round(nx, 4), round(ny, 4)], "bearing": round(bearing, 1), "side": compass(bearing)})
    return simp, edges


def select_edges(cands: list, edge_answer: dict | None, verify_answer: dict | None = None) -> list:
    """Combine geometry candidates with the VLM's per-wall decision and the verification pass.
    Returns accessible edges only (sorted by conf desc). Verification 'no' drops the edge."""
    by_id = {}
    for e in (edge_answer or {}).get("edges") or []:
        try:
            by_id[int(e.get("id"))] = e
        except (TypeError, ValueError):
            continue
    ver = {}
    for v in (verify_answer or {}).get("edges") or []:
        try:
            ver[int(v.get("id"))] = v
        except (TypeError, ValueError):
            continue
    out = []
    for c in cands:
        ans = by_id.get(c["id"])
        if not ans or ans.get("accessible") is not True:
            continue
        conf = float(ans.get("conf") or 0.5)
        v = ver.get(c["id"])
        if v is not None and v.get("ok") is False:
            continue
        if v is not None and v.get("ok") is True:
            conf = min(0.95, conf + 0.05)
        elif verify_answer is not None:
            conf *= 0.8  # not covered by verification
        out.append({**c, "conf": round(conf, 2), "reason": ans.get("reason"), "adjacent": ans.get("adjacent"),
                    "clear_width_ft": ans.get("clear_width_ft"), "verified": (v or {}).get("ok"),
                    "verify_note": (v or {}).get("why")})
    return sorted(out, key=lambda e: -e["conf"])


def overlap_frac(poly: list, other: list, res: float = 0.5) -> float:
    """Fraction of `poly`'s area that lies inside `other` (raster estimate on a res-px grid)."""
    from PIL import Image, ImageDraw

    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    x0, y0 = min(xs), min(ys)
    w, h = max(xs) - x0, max(ys) - y0
    if w <= 0 or h <= 0:
        return 0.0
    k = min(1.0 / res, 400.0 / max(w, h))
    W, H = int(w * k) + 3, int(h * k) + 3
    tr = lambda pp: [((x - x0) * k + 1, (y - y0) * k + 1) for x, y in pp]  # noqa: E731
    a = Image.new("1", (W, H), 0)
    ImageDraw.Draw(a).polygon(tr(poly), fill=1)
    b = Image.new("1", (W, H), 0)
    ImageDraw.Draw(b).polygon(tr(other), fill=1)
    import numpy as np

    A = np.asarray(a, dtype=bool)
    B = np.asarray(b, dtype=bool)
    na = A.sum()
    return float((A & B).sum() / na) if na else 0.0


def clip_halfplane(poly: list, p0, n) -> list:
    """Sutherland-Hodgman: keep the part of poly with (x - p0) . n >= 0."""
    f = lambda q: (q[0] - p0[0]) * n[0] + (q[1] - p0[1]) * n[1]  # noqa: E731
    out = []
    for i in range(len(poly)):
        c, d = poly[i], poly[(i + 1) % len(poly)]
        fc, fd = f(c), f(d)
        if fc >= 0:
            out.append(c)
        if (fc >= 0) != (fd >= 0):
            t = fc / (fc - fd)
            out.append((c[0] + t * (d[0] - c[0]), c[1] + t * (d[1] - c[1])))
    return out


def validate_staging(poly: list, footprint: list, edges: list, gsd_m: float, adjacent_id: int | None = None) -> dict:
    """Staging polygon must not overlap the footprint. Clip to the outside of the adjacent accessible
    wall (offset 0.5 m) if it does; reject if still overlapping or too small/large/far.
    Returns {ok, poly, reason, overlap_before, overlap_after, clipped, area_m2, dist_m, edge_id}."""
    res: dict[str, Any] = {"ok": False, "poly": None, "clipped": False}
    pts = [(float(x), float(y)) for x, y in (poly or []) if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    if len(pts) < 3:
        return {**res, "reason": "fewer than 3 vertices"}
    if len(pts) > 8:
        pts = simplify_ring(pts, max(0.5 / gsd_m, 1.0))[:8]
    ov0 = overlap_frac(pts, footprint)
    res["overlap_before"] = round(ov0, 3)
    edge = None
    if edges:
        if adjacent_id is not None:
            edge = next((e for e in edges if e["id"] == adjacent_id), None)
        if edge is None:
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            edge = min(edges, key=lambda e: _dist_pt_seg((cx, cy), e["a"], e["b"])[0])
    if ov0 > 0.005:
        if not edge:
            return {**res, "reason": f"overlaps building ({ov0:.0%}) and no wall to clip against"}
        off = 0.5 / gsd_m
        p0 = (edge["a"][0] + edge["normal"][0] * off, edge["a"][1] + edge["normal"][1] * off)
        pts = clip_halfplane(pts, p0, edge["normal"])
        res["clipped"] = True
        if len(pts) < 3:
            return {**res, "reason": "nothing left after clipping to outside of wall"}
    ov1 = overlap_frac(pts, footprint) if len(pts) >= 3 else 1.0
    res["overlap_after"] = round(ov1, 3)
    if ov1 > 0.02:
        return {**res, "reason": f"still overlaps building ({ov1:.0%}) after clipping"}
    area = poly_area(pts) * gsd_m * gsd_m
    res["area_m2"] = round(area, 1)
    if area < 25:
        return {**res, "reason": f"too small ({area:.0f} m2)"}
    if area > 6000:
        return {**res, "reason": f"too large ({area:.0f} m2) to be a tight staging area"}
    if edge:
        d = min(min(_dist_pt_seg(p, e["a"], e["b"])[0] for e in edges) for p in pts) * gsd_m
        res["dist_m"] = round(d, 1)
        res["edge_id"] = edge["id"]
        if d > 30:
            return {**res, "reason": f"{d:.0f} m from the nearest accessible wall"}
    return {**res, "ok": True, "poly": [[round(x, 1), round(y, 1)] for x, y in pts], "reason": "ok"}


# --------------------------------------------------------------- oblique projection (approx)
def _obl_frame(meta: dict):
    """Linear ground->image model for a Vexcel oblique crop (camera heading h, building at centre).
    x = W/2 + (p.right)/s ; y = H/2 - (p.fwd)*k/s   with s = extent_m/W, k = H/W  (p in metres E,N).
    Verified visually: the projected footprint lands on the wall bases within ~1-2 m."""
    h = math.radians(HEADING[meta["direction"]])
    W, H = float(meta["width"]), float(meta["height"])
    s = float(meta.get("extent_m") or 120) / W
    k = H / W
    fwd = (math.sin(h), math.cos(h))
    right = (math.cos(h), -math.sin(h))
    return W, H, s, k, fwd, right


def obl_project(meta: dict, e: float, n: float) -> tuple[float, float]:
    W, H, s, k, f, r = _obl_frame(meta)
    return W / 2 + (e * r[0] + n * r[1]) / s, H / 2 - (e * f[0] + n * f[1]) * k / s


def obl_unproject(meta: dict, x: float, y: float) -> tuple[float, float]:
    W, H, s, k, f, r = _obl_frame(meta)
    pr = (x - W / 2) * s
    pf = (H / 2 - y) * s / k
    return pr * r[0] + pf * f[0], pr * r[1] + pf * f[1]


# =============================================================== vision plumbing (cached)
def _font(size: int):
    from PIL import ImageFont

    for f in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _sha(p: str | Path) -> str:
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


def _jpeg(im) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _live_ok(allow_live: bool | None) -> bool:
    if allow_live is not None:
        return allow_live and config.has_api_key()
    return config.has_api_key() and not config.offline_mode()


def _ask(kind: str, images: list, prompt: str, key_material: Any, allow_live: bool | None, log: list) -> dict | None:
    """One cached VLM call. images: list of (label, PIL image). Key = sha1(version+kind+prompt+key_material)
    where key_material names the SOURCE images (file sha1) and the drawn geometry, so re-styling the
    overlay does not invalidate the cache."""
    import os

    if os.environ.get("FI_ACCESS_DEBUG"):
        for j, (_lab, im) in enumerate(images):
            im.save(f"{os.environ['FI_ACCESS_DEBUG']}_{kind}_{j}.jpg", quality=85)
    key = hashlib.sha1(json.dumps([VERSION, kind, prompt, key_material], sort_keys=True, default=str).encode()).hexdigest()
    f = config.VISION_CACHE_DIR / f"{key}.json"
    if f.exists():
        try:
            d = json.loads(f.read_text())
            log.append({"call": kind, "cached": True, "key": key, "s": 0})
            return d.get("parsed")
        except Exception:  # noqa: BLE001
            pass
    if not _live_ok(allow_live):
        log.append({"call": kind, "cached": False, "error": "no cached answer (offline)", "key": key})
        return None
    t0 = time.time()
    try:
        import anthropic

        content: list = []
        for label, im in images:
            content.append({"type": "text", "text": f"{label} ({im.size[0]}x{im.size[1]} px):"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.b64encode(_jpeg(im)).decode()}})
        content.append({"type": "text", "text": prompt + "\n\nRespond with ONLY the JSON object (no prose, no markdown fences)."})
        client = anthropic.Anthropic(max_retries=3)
        resp = client.messages.create(model=config.vision_model_name(), max_tokens=16000,
                                      output_config={"effort": "medium"},
                                      messages=[{"role": "user", "content": content}])
        if resp.stop_reason == "refusal":
            log.append({"call": kind, "error": "refused", "key": key, "s": round(time.time() - t0, 1)})
            return None
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        parsed = _parse(text)
    except Exception as e:  # noqa: BLE001
        log.append({"call": kind, "error": f"{type(e).__name__}: {e}", "key": key, "s": round(time.time() - t0, 1)})
        return None
    if parsed is None:
        log.append({"call": kind, "error": "unparseable answer", "key": key, "raw": text[:300]})
        return None
    config.VISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"kind": f"{VERSION}:{kind}", "parsed": parsed, "model": config.vision_model_name(),
                             "created_at": time.time(), "secs": round(time.time() - t0, 1)}, indent=1))
    log.append({"call": kind, "cached": False, "key": key, "s": round(time.time() - t0, 1)})
    return parsed


# =============================================================== drawing helpers
class Crop:
    """Region of the full-res base image shown to the VLM, downscaled to <= VLM_MAX px."""

    def __init__(self, full, box):
        x0, y0, x1, y1 = [int(round(v)) for v in box]
        self.x0, self.y0 = x0, y0
        self.s = min(1.0, VLM_MAX / max(x1 - x0, y1 - y0))
        reg = full.crop((x0, y0, x1, y1))
        self.im = reg.resize((max(1, int((x1 - x0) * self.s)), max(1, int((y1 - y0) * self.s))))

    def to(self, p):  # base px -> crop px
        return ((p[0] - self.x0) * self.s, (p[1] - self.y0) * self.s)

    def back(self, p):  # crop px -> base px
        return (p[0] / self.s + self.x0, p[1] / self.s + self.y0)


def _label(dr, xy, text, font, fill=(255, 255, 255), fg=(0, 0, 0), outline=(0, 0, 0)):
    x, y = xy
    tb = dr.textbbox((0, 0), text, font=font)
    w, h = tb[2] - tb[0], tb[3] - tb[1]
    pad = max(3, h // 4)
    dr.rectangle((x - w / 2 - pad, y - h / 2 - pad, x + w / 2 + pad, y + h / 2 + pad), fill=fill, outline=outline, width=2)
    dr.text((x - w / 2 - tb[0], y - h / 2 - tb[1]), text, font=font, fill=fg)


def _draw_edges_im(crop: Crop, ring, edges, highlight_only=False, color=None, width=7, prefix=""):
    from PIL import ImageDraw

    im = crop.im.copy()
    dr = ImageDraw.Draw(im)
    rp = [crop.to(p) for p in ring]
    dr.line(rp + [rp[0]], fill=(255, 30, 30), width=2)
    font = _font(max(18, int(im.size[0] / 55)))
    for j, e in enumerate(edges):
        c = color or EDGE_COLORS[j % len(EDGE_COLORS)]
        a, b = crop.to(e["a"]), crop.to(e["b"])
        dr.line([a, b], fill=c, width=width)
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        off = 30
        _label(dr, (mx + e["normal"][0] * off, my + e["normal"][1] * off), f"{prefix}{e['id']}", font, fill=c)
    return im


# =============================================================== prompts
EDGE_Q = """You are a fire-service pre-incident planning analyst. The image is a top-down, north-up aerial photo (about {mpp:.2f} m per pixel). The target building's footprint is outlined in thin red, and its walls are drawn as thick coloured segments with numbered labels ({ids}); each label sits just OUTSIDE its wall.
For EACH numbered wall decide whether a fire apparatus (aerial ladder truck, or an engine for ground ladders) could set up alongside it to reach the roof. A wall is accessible only if a paved street, alley, drive aisle or open paved lot runs alongside it, within about 10 m (35 ft) of the wall, with at least about 6 m (20 ft) of clear driveable width, connected to a street, and NOT separated from the wall by rail tracks, fences or gates, another building, dense yard storage, trees or landscaping. Parking stalls between the aisle and the wall are acceptable (aerial reach). Judge only what is visible.
Return JSON: {{"edges": [{{"id": int, "adjacent": "what lies directly outside this wall, short", "clear_width_ft": number or null, "accessible": true or false, "conf": 0-1, "reason": "one short sentence"}}], "summary": "one sentence"}}"""

STAGING_Q = """You are a fire-service pre-incident planning analyst. The image is a top-down, north-up aerial photo (about {mpp:.2f} m per pixel). The target building's footprint is outlined in red; the walls judged usable for aerial/ladder access are drawn thick green. Candidate apparatus staging rectangles (each about 20 m x 6 m, parallel to a green wall, at increasing distance from it) are outlined in white with yellow letter labels ({labels}).
For EACH lettered rectangle, look carefully at what is underneath it and classify it:
 "surface": the main ground cover inside the rectangle, one of drive_aisle | open_paved_lot | street | parking_stalls | sidewalk_or_apron | building_or_roof | dirt_or_landscaping | rail | storage_or_debris
 "clear": fraction 0-1 of the rectangle that is free of buildings, parked vehicles/trailers, stored material, fences, poles and vegetation
 "connected": true if a fire engine could drive into it from a street without crossing a fence, kerb-less dirt or buildings
Return JSON: {{"cands": [{{"label": "A", "surface": "...", "clear": 0-1, "connected": true or false, "why": "short"}}], "best": "label of the single best staging rectangle (open drive aisle or lot, clear, connected, close to the wall) or null", "value": "short phrase describing the ground of the best rectangle, e.g. 'paved drive aisle connected to the street' (no compass directions, no letter labels, no colours)"}}"""

ENTRIES_Q = """You are a fire-service pre-incident planning analyst. The images above are oblique (about 45 degree) aerial photos of the SAME target building, which is the large building at the centre of each image, taken from different directions. Where its walls appear in each image (approximate pixel x-ranges at ground level, from the footprint):
{hints}
Find every exterior opening a firefighter could use to enter or leave the TARGET building (ignore neighbouring buildings and fences/gates):
- dock_door: overhead / roll-up door at truck-bed height (dock-high), usually with a truck well, dock bumpers or a raised loading dock
- drive_in: grade-level overhead / roll-up door that a vehicle can drive straight into (flush with the pavement or with a short ramp)
- rollup: overhead / roll-up door when you cannot tell dock-high from grade-level
- entrance: main pedestrian entrance, storefront, lobby or glass doors (often with canopy, signage, steps or a ramp)
- exit: single or double personnel (man) door or emergency exit (small, about 1 m wide, often dark; look along every visible wall base, including next to overhead doors and under stairs/ramps)
List EVERY door individually, even when many identical doors repeat along a wall (multi-tenant industrial buildings often have one overhead door plus one personnel door per suite). Give EACH opening its own TIGHT bbox (just the door, not the wall) in that image's own pixel coordinates. Report only openings you can actually see; walls hidden from a camera are covered by another image, so do not guess. At most 30 per image.
Return JSON: {{"images": [{{"image": int, "entries": [{{"type": "dock_door|drive_in|rollup|entrance|exit", "bbox": [x0, y0, x1, y1], "desc": "short description of the door itself, without compass directions", "conf": 0-1}}]}}]}}"""

VERIFY_Q = """Check proposed fire pre-plan access geometry. Be strict and answer only from what you can see.
Image A (top-down, north up): thick green lines labelled E<n> are walls proposed for aerial/ladder apparatus access. {staging_note}
{entries_note}
Answer every item:
- each E<n>: does a paved street, drive aisle or lot that a fire apparatus can drive onto run alongside this wall within about 10 m (35 ft), so an aerial or ground ladders could reach the roof? A sidewalk, parking stalls or low shrubs in between are fine; rail tracks, a fence, another building, yard storage or a dense tree belt in between are not.
{staging_item}{entries_item}
Return JSON: {{"edges": [{{"id": int, "ok": true or false, "why": "short"}}], "staging": {staging_schema}, "entries": [{{"n": int, "ok": true or false, "type": "the correct type (dock_door|drive_in|rollup|entrance|exit)", "why": "short"}}]}}"""


def staging_candidates(edges: list, ring: list, gsd: float, depth_m: float = 6.0, bands: int = 4,
                       win_m: float = 20.0, max_n: int = 20) -> list:
    """Wall-parallel rectangles outside accessible walls: up to 3 windows along each wall x `bands`
    offsets of depth_m (starting 3 m off the wall). Rectangles overlapping the footprint are dropped."""
    out = []
    for e in sorted(edges, key=lambda e: -e["len_m"])[:4]:
        L = e["len_m"]
        if L < 8:
            continue
        a, b = e["a"], e["b"]
        u = ((b[0] - a[0]) / (L / gsd), (b[1] - a[1]) / (L / gsd))
        n = e["normal"]
        w = min(win_m, L)
        centres = [0.5] if L < 30 else ([0.3, 0.7] if L < 55 else [0.2, 0.5, 0.8])
        for c in centres:
            s0 = max(0.0, c * L - w / 2)
            s1 = min(L, s0 + w)
            for k in range(bands):
                o0, o1 = 3.0 + k * depth_m, 3.0 + (k + 1) * depth_m
                P = lambda s, o: (a[0] + u[0] * s / gsd + n[0] * o / gsd, a[1] + u[1] * s / gsd + n[1] * o / gsd)  # noqa: E731
                poly = [P(s0, o0), P(s1, o0), P(s1, o1), P(s0, o1)]
                if overlap_frac(poly, ring) > 0.02:
                    continue
                out.append({"edge_id": e["id"], "side": e["side"], "win": c, "band": k, "s": [s0, s1], "off": [o0, o1],
                            "poly": [[round(x, 1), round(y, 1)] for x, y in poly]})
    out = out[:max_n]
    for i, c in enumerate(out):
        c["label"] = chr(ord("A") + i)
    return out


GOOD_SURF = {"drive_aisle": 1.0, "open_paved_lot": 0.95, "street": 0.85}


def rank_staging(cands: list, ans: dict | None) -> list:
    """Usable rectangles ranked by a deterministic score over the model's per-candidate classification:
    paved & open surface, clear fraction >= 0.75, connected to a street; closer bands and the model's
    `best` get a small bonus. Each is one wall-parallel rectangle (~20 m x 6 m)."""
    if not ans:
        return []
    rows = ans.get("cands") or ans.get("usable") or []
    best = str(ans.get("best") or "").strip().upper()
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        k = str(r.get("label")).strip().upper()
        c = next((x for x in cands if x["label"] == k), None)
        if not c:
            continue
        surf = str(r.get("surface") or "").strip().lower()
        clear = float(r.get("clear") if isinstance(r.get("clear"), (int, float)) else (r.get("conf") or 0))
        if surf and surf not in GOOD_SURF:
            continue
        if clear < 0.75 or r.get("connected") is False:
            continue
        score = GOOD_SURF.get(surf, 0.5) * clear + (0.1 if k == best else 0) - 0.03 * c["band"]
        out.append({**c, "labels": [k], "conf": round(min(0.85, 0.35 + 0.5 * score), 2), "score": score,
                    "why": r.get("why"), "surface": surf})
    return sorted(out, key=lambda x: -x["score"])


def _draw_staging_im(crop: "Crop", ring, edges, cands):
    from PIL import ImageDraw

    im = crop.im.copy()
    dr = ImageDraw.Draw(im)
    rp = [crop.to(p) for p in ring]
    dr.line(rp + [rp[0]], fill=(255, 30, 30), width=2)
    for e in edges:
        dr.line([crop.to(e["a"]), crop.to(e["b"])], fill=(0, 255, 0), width=7)
    font = _font(max(16, int(im.size[0] / 70)))
    for c in cands:
        pp = [crop.to(p) for p in c["poly"]]
        dr.line(pp + [pp[0]], fill=(255, 255, 255), width=2)
    for c in cands:
        pp = [crop.to(p) for p in c["poly"]]
        cx = sum(p[0] for p in pp) / 4
        cy = sum(p[1] for p in pp) / 4
        _label(dr, (cx, cy), c["label"], font, fill=(255, 255, 0))
    return im


# =============================================================== main
def _norm_type(t: str | None) -> str | None:
    t = str(t or "").lower().replace("-", "_").replace(" ", "_")
    if "dock" in t or "loading" in t:
        return "dock_door"
    if "drive" in t:
        return "drive_in"
    if "roll" in t or "overhead" in t or "garage" in t:
        return "rollup"
    if "entr" in t or "lobby" in t or "store" in t:
        return "entrance"
    if "exit" in t or "man" in t or "door" in t or "person" in t:
        return "exit"
    return None


def _pick_base(bid: str, ring_ll: list) -> tuple[str, dict, list] | None:
    for view in ("ortho", "context"):
        t = sources.vexcel_tile(bid, view)
        if t.get("error") or "georef" not in t:
            continue
        g = t["georef"]
        px = [vexcel.latlng_to_px(g, lat, lng) for lat, lng in ring_ll]
        px = [(p["x"], p["y"]) for p in px]
        m = 10.0 / g["gsd_m"]
        if view == "context" or all(m <= x <= g["width"] - m and m <= y <= g["height"] - m for x, y in px):
            return view, t, px
    return None


def _edge_text(e: dict) -> str:
    adj = re.sub(r"\s+", " ", str(e.get("adjacent") or "")).strip().rstrip(".")
    w = f", ~{int(e['clear_width_ft'])} ft clear" if isinstance(e.get("clear_width_ft"), (int, float)) else ""
    return f"{e['side']} wall ({e['len_m']:.0f} m): {adj}{w}" if adj else f"{e['side']} wall ({e['len_m']:.0f} m){w}"


def _short_adj(text: str | None, n: int = 5) -> str:
    t = re.split(r"[,;.(]| with | and | then | to the | beyond | across ", str(text or ""))[0].strip()
    w = t.split()[:n]
    while w and w[-1].lower() in ("to", "the", "a", "an", "of", "on", "at", "in", "from", "by", "along", "between"):
        w.pop()
    return " ".join(w).lower()


def analyze_access(building_id: str, allow_live: bool | None = None, force: bool = False) -> dict:
    """Ladder/aerial access edges, staging polygon and entry/exit points (see module doc)."""
    t_start = time.time()
    log: list = []
    try:
        return _analyze(building_id, allow_live, force, log, t_start)
    except Exception as e:  # noqa: BLE001 - tools never raise
        import traceback

        return {"error": f"analyze_access failed: {type(e).__name__}: {e}", "calls": log,
                "trace": traceback.format_exc(limit=3)}


def _analyze(bid: str, allow_live, force, log, t_start) -> dict:
    from PIL import Image, ImageDraw

    Image.MAX_IMAGE_PIXELS = None
    tile0 = sources.vexcel_tile(bid, "ortho")
    if tile0.get("error"):
        return {"error": f"no Vexcel tile: {tile0['error']}"}
    vdir = Path(tile0["image_path"]).parent
    out_json = vdir / "access.json"
    if not force and not _live_ok(allow_live) and out_json.exists():
        try:
            d = json.loads(out_json.read_text())
            if d.get("version") == VERSION:
                return {**d, "cached": True}
        except Exception:  # noqa: BLE001
            pass
    fp = sources.vexcel_footprint(bid)
    if fp.get("error") or not fp.get("footprint_latlng"):
        return {"error": f"no footprint: {fp.get('error')}"}
    pb = _pick_base(bid, fp["footprint_latlng"])
    if not pb:
        return {"error": "no georeferenced ortho/context tile"}
    view, tile, ring = pb
    g = tile["georef"]
    gsd = float(g["gsd_m"])
    base_path = tile["image_path"]
    base_sha = _sha(base_path)
    simp, cands = extract_edges(ring, gsd)
    if not cands:
        return {"error": "footprint has no wall >= 6 m"}
    full = Image.open(base_path).convert("RGB")
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    mg = max(35.0 / gsd, 0.25 * span)
    box = (max(0, min(xs) - mg), max(0, min(ys) - mg), min(full.size[0], max(xs) + mg), min(full.size[1], max(ys) + mg))
    crop = Crop(full, box)
    mpp = gsd / crop.s
    geo_key = {"base": base_sha, "box": [round(v) for v in box], "edges": [[e["id"], e["a"], e["b"]] for e in cands]}

    # ---------- obliques (needed for entries; runs in parallel with edges+staging)
    obl = []
    for D in ("N", "E", "S", "W"):
        m = sources.vexcel_oblique(bid, D)
        if m.get("error") or not m.get("image_path") or not Path(m["image_path"]).exists():
            continue
        obl.append(m)

    def base_to_en(p, lat0, lng0):
        """base px -> metres (E, N) relative to lat0/lng0."""
        c = vexcel.latlng_to_px(g, lat0, lng0)
        return (p[0] - c["x"]) * gsd, -(p[1] - c["y"]) * gsd

    def en_to_base(e, n, lat0, lng0):
        c = vexcel.latlng_to_px(g, lat0, lng0)
        return c["x"] + e / gsd, c["y"] - n / gsd

    def visible_edges(m):
        f = (math.sin(math.radians(HEADING[m["direction"]])), math.cos(math.radians(HEADING[m["direction"]])))
        vis = []
        for i in range(len(simp)):
            a, b = simp[i], simp[(i + 1) % len(simp)]
            L = math.hypot(b[0] - a[0], b[1] - a[1]) * gsd
            if L < 2.0:
                continue
            ce = next((c for c in cands if c["i"] == i), None)
            if ce:
                nrm = ce["normal"]
            else:
                d = (b[0] - a[0], b[1] - a[1])
                nl = math.hypot(*d) or 1
                nrm = [d[1] / nl, -d[0] / nl]
                mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                if point_in_poly(mx + nrm[0] * 3, my + nrm[1] * 3, simp):
                    nrm = [-nrm[0], -nrm[1]]
            facing = nrm[0] * f[0] + (-nrm[1]) * f[1]  # outward normal (E,N) . camera forward
            if facing < -0.15:
                ae = base_to_en(a, m["lat"], m["lng"])
                be = base_to_en(b, m["lat"], m["lng"])
                vis.append({"i": i, "a": a, "b": b, "len_m": L, "normal": nrm,
                            "side": compass(math.degrees(math.atan2(nrm[0], -nrm[1]))),
                            "pa": obl_project(m, *ae), "pb": obl_project(m, *be)})
        return vis

    for m in obl:
        m["_vis"] = visible_edges(m)

    def run_entries():
        if not obl:
            return None, []
        ims, hints, key = [], [], []
        for k, m in enumerate(obl, 1):
            im = Image.open(m["image_path"]).convert("RGB")
            # zoom on the target's ground-level footprint (doors sit on it): projected ring bbox + margin
            ring_o = [obl_project(m, *base_to_en(p, m["lat"], m["lng"])) for p in simp]
            gx = [p[0] for p in ring_o]
            gy = [p[1] for p in ring_o]
            cx0 = int(max(0, min(gx) - 90))
            cx1 = int(min(im.size[0], max(gx) + 90))
            cy0 = int(max(0, min(gy) - 260))
            cy1 = int(min(im.size[1], max(gy) + 90))
            if cx1 - cx0 < 200 or cy1 - cy0 < 200:
                cx0, cy0, cx1, cy1 = 0, 0, im.size[0], im.size[1]
            im = im.crop((cx0, cy0, cx1, cy1))
            s = min(2.0, VLM_MAX / max(im.size))
            m["_s"], m["_off"] = s, (cx0, cy0)
            ims.append((f"Image {k}: camera looking {m['camera_looking']}", im.resize((int(im.size[0] * s), int(im.size[1] * s)))))
            parts = {}
            for v in m["_vis"]:
                if v["len_m"] < 5:
                    continue
                x0, x1 = sorted([(v["pa"][0] - cx0) * s, (v["pb"][0] - cx0) * s])
                if x1 < 0 or x0 > im.size[0] * s:
                    continue
                cur = parts.get(v["side"])
                parts[v["side"]] = [min(x0, cur[0]), max(x1, cur[1])] if cur else [x0, x1]
            desc = ", ".join(f"{sd} wall x~{max(0, int(a))}-{min(int(im.size[0] * s), int(b))}" for sd, (a, b) in
                             sorted(parts.items(), key=lambda kv: kv[1][0]))
            hints.append(f"- Image {k} (camera looking {m['camera_looking']}): {desc or 'walls not resolved'}")
            key.append([m["tile_id"], _sha(m["image_path"])])
        q = ENTRIES_Q.format(hints="\n".join(hints))
        return _ask("entries", ims, q, key, allow_live, log), ims

    pool = ThreadPoolExecutor(max_workers=1)
    fut_entries = pool.submit(run_entries)

    # ---------- 1. edges
    im_edges = _draw_edges_im(crop, simp, cands)
    edge_ans = _ask("edges", [("Image", im_edges)], EDGE_Q.format(mpp=mpp, ids=", ".join(str(e["id"]) for e in cands)),
                    geo_key, allow_live, log)
    prelim = select_edges(cands, edge_ans)

    # ---------- 2. staging (set-of-marks: code proposes wall-parallel rectangles, the model picks)
    stg_ans = None
    stg_val: dict = {"ok": False, "reason": "no accessible wall"}
    scands = staging_candidates(prelim, simp, gsd) if prelim else []
    if prelim and not scands:
        stg_val = {"ok": False, "reason": "no candidate area outside the footprint"}
    if scands:
        im_stg = _draw_staging_im(crop, simp, prelim, scands)
        stg_ans = _ask("staging", [("Image", im_stg)],
                       STAGING_Q.format(mpp=mpp, labels=", ".join(c["label"] for c in scands)),
                       {**geo_key, "accessible": [e["id"] for e in prelim],
                        "cands": [[c["label"], c["poly"]] for c in scands]}, allow_live, log)
        stg_opts = []
        for ch in rank_staging(scands, stg_ans):
            v = validate_staging(ch["poly"], simp, prelim, gsd, ch["edge_id"])
            if v.get("ok"):
                stg_opts.append({**v, "labels": ch["labels"], "conf": ch["conf"], "surface": ch.get("surface")})
            if len(stg_opts) == 3:
                break
        stg_val = stg_opts[0] if stg_opts else {"ok": False, "reason": "model found no clear paved staging area"}
    else:
        stg_opts = []

    # ---------- 3. entries (map oblique bbox -> footprint edge -> ortho point)
    ent_ans, ent_ims = fut_entries.result()
    pool.shutdown()
    entries = []
    for blk in (ent_ans or {}).get("images") or []:
        try:
            m = obl[int(blk.get("image")) - 1]
        except (TypeError, ValueError, IndexError):
            continue
        s = m.get("_s") or 1.0
        for en in blk.get("entries") or []:
            typ = _norm_type(en.get("type"))
            bb = en.get("bbox")
            if not typ or not (isinstance(bb, list) and len(bb) == 4 and all(isinstance(v, (int, float)) for v in bb)):
                continue
            ox, oy = m.get("_off") or (0, 0)
            bb = [round(bb[0] / s + ox), round(bb[1] / s + oy), round(bb[2] / s + ox), round(bb[3] / s + oy)]
            x0, y0, x1, y1 = min(bb[0], bb[2]), min(bb[1], bb[3]), max(bb[0], bb[2]), max(bb[1], bb[3])
            if x1 - x0 < 3 or y1 - y0 < 3:
                continue
            gx, gy = obl_unproject(m, (x0 + x1) / 2, y1)  # door base sits on the ground footprint line
            gb = en_to_base(gx, gy, m["lat"], m["lng"])
            best = None
            for v in m["_vis"]:
                d, t = _dist_pt_seg(gb, v["a"], v["b"])
                if best is None or d < best[0]:
                    best = (d, t, v)
            ent = {"type": typ, "desc": en.get("desc"), "conf_det": float(en.get("conf") or 0.5),
                   "oblique": m["direction"], "tile_id": m["tile_id"], "bbox": [x0, y0, x1, y1],
                   "img_w": m["width"], "img_h": m["height"], "url": m["image_url"], "shows_facade": m.get("shows_facade")}
            if best:
                d, t, v = best
                p = (v["a"][0] + t * (v["b"][0] - v["a"][0]), v["a"][1] + t * (v["b"][1] - v["a"][1]))
                ent.update({"side": v["side"], "edge_i": v["i"], "t": round(t, 3), "snap_m": round(d * gsd, 1),
                            "pt": [round(p[0], 1), round(p[1], 1)],
                            "pos_m": t * v["len_m"]})
            else:
                ent["side"] = None
            entries.append(ent)
    # dedupe the same door seen from two obliques (same wall, same family, within 3.5 m)
    fam = lambda t: "overhead" if t in ("dock_door", "drive_in", "rollup") else "door"  # noqa: E731
    entries.sort(key=lambda e: -e["conf_det"])
    kept: list = []
    for e in entries:
        dup = next((k for k in kept if k.get("edge_i") is not None and k.get("edge_i") == e.get("edge_i")
                    and fam(k["type"]) == fam(e["type"]) and abs(k["pos_m"] - e["pos_m"]) < 3.5
                    and k["oblique"] != e["oblique"]
                    and e["oblique"] not in {a["oblique"] for a in k.get("also_seen") or []}), None)
        if dup:
            dup.setdefault("also_seen", []).append({"oblique": e["oblique"], "tile_id": e["tile_id"], "bbox": e["bbox"],
                                                    "url": e["url"], "img_w": e["img_w"], "img_h": e["img_h"]})
            dup["conf_det"] = min(0.95, dup["conf_det"] + 0.05)
            continue
        kept.append(e)
    entries = kept[:60]

    # ---------- 4. verification pass
    ver_ans = None
    if prelim or entries:
        imA = _draw_edges_im(crop, simp, prelim, color=(0, 255, 0), width=9, prefix="E")
        for j, so in enumerate(stg_opts, 1):
            ov = imA.copy()
            dr = ImageDraw.Draw(ov, "RGBA")
            sp = [crop.to(p) for p in so["poly"]]
            dr.polygon(sp, fill=(0, 120, 255, 110), outline=(0, 80, 255, 255))
            imA = ov
            far = ((sp[2][0] + sp[3][0]) / 2, (sp[2][1] + sp[3][1]) / 2)  # far side (away from the wall)
            _label(ImageDraw.Draw(imA), far, f"S{j}", _font(24), fill=(0, 120, 255), fg=(255, 255, 255))
        imgs = [("Image A", imA)]
        if entries:
            imgs.append(("Image B", _contact_sheet(entries)))
        vq = VERIFY_Q.format(
            staging_note=("Blue polygons " + " and ".join(f"S{j}" for j in range(1, len(stg_opts) + 1)) + " are proposed apparatus staging areas.") if stg_opts else "",
            entries_note="Image B: numbered crops (#n) from oblique aerial photos; the red box in each is a proposed exterior door of the target building, with its proposed type written under it." if entries else "",
            staging_item="- each S<n>: is the polygon entirely on paved, open, driveable ground outside every building (not on a roof, parked cars, storage or dirt), and big enough to park a fire apparatus?\n" if stg_opts else "",
            entries_item="- each #n: is there really an exterior door or opening of the building inside the red box? ok = true if a real door/opening is there even when the stated type is wrong; put the correct type in the type field.\n" if entries else "",
            staging_schema='[{"id": "S1", "ok": true or false, "why": "short"}]' if stg_opts else "[]")
        vkey = {**geo_key, "edges": [e["id"] for e in prelim], "staging": [so["poly"] for so in stg_opts],
                "entries": [[e["tile_id"], e["bbox"], e["type"]] for e in entries]}
        ver_ans = _ask("verify", imgs, vq, vkey, allow_live, log)

    # ---------- assemble
    edges = select_edges(cands, edge_ans, ver_ans)
    vs = (ver_ans or {}).get("staging")
    vs = vs if isinstance(vs, list) else ([vs] if isinstance(vs, dict) else [])
    vmap = {str(x.get("id") or x.get("label") or "").upper(): x for x in vs if isinstance(x, dict)}
    staging, ver_stg = None, None
    for j, so in enumerate(stg_opts, 1):
        vv = vmap.get(f"S{j}") or (vs[0] if len(stg_opts) == 1 and vs and isinstance(vs[0], dict) else None)
        if vv and vv.get("ok") is False:
            ver_stg = ver_stg or vv
            continue
        stg_val, ver_stg = so, vv
        break
    else:
        stg_val = {**stg_val, "ok": False} if stg_opts else stg_val
    if stg_val.get("ok"):
        conf = float(stg_val.get("conf") or 0.5)
        conf = min(0.9, conf + 0.05) if (ver_stg or {}).get("ok") else conf * 0.8
        if stg_val.get("clipped"):
            conf *= 0.9
        e_st = next((e for e in prelim if e["id"] == stg_val.get("edge_id")), None)
        phrase = re.sub(r"\s+", " ", str((stg_ans or {}).get("value") or "paved open ground")).strip().rstrip(".")
        sval = f"{e_st['side'] + ' side: ' if e_st else ''}{phrase} (about {stg_val.get('area_m2', 0):.0f} m2, {stg_val.get('dist_m', 0):.0f} m off the wall)"
        staging = {"value": sval, "side": e_st["side"] if e_st else None, "labels": stg_val.get("labels"),
                   "px": stg_val["poly"], "latlng": [_ll(g, p) for p in stg_val["poly"]], "conf": round(conf, 2),
                   "edge_id": stg_val.get("edge_id"), "verified": (ver_stg or {}).get("ok"),
                   "verify_note": (ver_stg or {}).get("why"),
                   "validation": {k: stg_val.get(k) for k in ("overlap_before", "overlap_after", "clipped", "area_m2", "dist_m")}}
    staging_rejected = None
    if not staging:
        staging_rejected = (f"verification: {ver_stg.get('why')}" if ver_stg else stg_val.get("reason"))

    ver_e = {}
    for v in (ver_ans or {}).get("entries") or []:
        try:
            ver_e[int(v.get("n"))] = v
        except (TypeError, ValueError):
            continue
    final_entries, dropped = [], []
    for n, e in enumerate(entries, 1):
        v = ver_e.get(n)
        if v is not None and v.get("ok") is False:
            dropped.append({"type": e["type"], "side": e.get("side"), "bbox": e["bbox"], "oblique": e["oblique"], "why": v.get("why")})
            continue
        typ = _norm_type((v or {}).get("type")) or e["type"]
        conf = e["conf_det"] * (1.0 if (v or {}).get("ok") else 0.8)
        pt = None
        if e.get("pt"):
            pconf = max(0.2, min(0.6, 0.6 - 0.03 * max(0.0, e["snap_m"] - 2)))
            pt = {"px": e["pt"], "latlng": _ll(g, e["pt"]), "approx": True, "conf": round(pconf, 2),
                  "snap_m": e["snap_m"], "t": e["t"]}
        final_entries.append({
            "type": typ, "side": e.get("side"), "value": e.get("desc") or TYPE_NAME[typ][0], "conf": round(conf, 2),
            "verified": (v or {}).get("ok"), "verify_note": (v or {}).get("why"),
            "cite": {"src": "vexcel", "id": e["tile_id"], "conf": round(conf, 2), "bbox": e["bbox"], "img_w": e["img_w"],
                     "img_h": e["img_h"], "url": e["url"], "oblique": e["oblique"], "shows_facade": e["shows_facade"],
                     "from": None},
            "also_seen": e.get("also_seen"), "ortho_point": pt})
    for i, e in enumerate(final_entries, 1):
        e["n"] = i

    # ---------- cross-references
    prop = sources.costar_property(bid)
    docks = prop.get("loading_docks") if not prop.get("error") else None
    dib = prop.get("drive_in_bays") if not prop.get("error") else None
    mp = sources.matterport_model(bid)
    mp_rooms = [r for r in (mp.get("rooms") or []) if re.search(r"entr|lobby|foyer|vestibule|reception", str(r.get("label") or ""), re.I)] if not mp.get("error") else []
    counts: dict = {}
    for e in final_entries:
        counts.setdefault(e["type"], {}).setdefault(e.get("side") or "?", 0)
        counts[e["type"]][e.get("side") or "?"] += 1
    parts = []
    for typ in ENTRY_TYPES:
        if typ in counts:
            n = sum(counts[typ].values())
            sides = ", ".join(f"{c} {s}" if len(counts[typ]) > 1 else s for s, c in sorted(counts[typ].items(), key=lambda kv: -kv[1]))
            parts.append(f"{n} {TYPE_NAME[typ][n != 1]} ({sides})")
    xref = []
    n_dock = sum(counts.get("dock_door", {}).values())
    n_over = n_dock + sum(counts.get("drive_in", {}).values()) + sum(counts.get("rollup", {}).values())
    if isinstance(docks, (int, float)) and docks:
        agree = "agrees" if n_dock == docks else ("partly visible" if 0 < n_dock < docks else ("more visible than listed" if n_dock > docks else "none identified as dock-high"))
        xref.append(f"CoStar lists {int(docks)} loading docks; {n_dock} dock doors visible ({agree}; {n_over} overhead doors in total)")
    elif docks:
        xref.append(f"CoStar: loading docks {docks}; {n_dock} dock doors visible")
    if dib:
        xref.append(f"CoStar drive-in bays: {dib}; {sum(counts.get('drive_in', {}).values())} drive-in doors visible")
    if mp_rooms:
        xref.append(f"Matterport scan has {len(mp_rooms)} entrance/lobby room(s) ('{mp_rooms[0].get('label')}')")
    from_fields = ["vexcel.obliques"] + (["costar.loading_docks"] if docks else []) + (["costar.drive_in_bays"] if dib else []) + \
                  (["matterport.rooms"] if mp_rooms else [])
    summary = None
    if parts:
        summary = {"value": "; ".join(parts) + (". " + ". ".join(xref) if xref else ""),
                   "counts": counts, "costar_loading_docks": docks, "costar_drive_in_bays": dib,
                   "matterport_entry_rooms": [{"label": r.get("label"), "id": r.get("id"), "floor": r.get("floor")} for r in mp_rooms],
                   "cite": {"src": "inference", "id": "access:entries", "conf": 0.6, "bbox": None, "url": None, "from": from_fields}}
    elif xref:
        summary = {"value": "No exterior doors identified on the obliques. " + ". ".join(xref),
                   "cite": {"src": "inference", "id": "access:entries", "conf": 0.4, "bbox": None, "url": None, "from": from_fields}}

    # ---------- roof access text
    rejected = []
    by_id = {int(e["id"]): e for e in (edge_ans or {}).get("edges") or [] if str(e.get("id", "")).isdigit()}
    for c in cands:
        a = by_id.get(c["id"])
        if a and a.get("accessible") is False and c["len_m"] >= 15:
            if not any(r.startswith(c["side"] + " ") for r in rejected):
                rejected.append(f"{c['side']} ({_short_adj(a.get('adjacent'), 6) or 'blocked'})")
    roof_access = None
    if edges:
        seen, txt = set(), []
        for e in edges:
            if e["side"] in seen:
                continue
            seen.add(e["side"])
            txt.append(_edge_text(e))
        sides = list(dict.fromkeys(e["side"] for e in edges))
        val = "Aerial/ladder access from " + "; ".join(txt)
        if rejected:
            val += ". Not accessible: " + ", ".join(dict.fromkeys(rejected))
        short = f"{'/'.join(sides[:3])} side{'s' if len(sides) > 1 else ''} from {_short_adj(edges[0].get('adjacent'))}".strip()
        roof_access = {"value": val, "short": short if edges[0].get("adjacent") else f"{'/'.join(sides[:3])} side",
                       "conf": round(max(e["conf"] for e in edges), 2)}

    # aerial reach: ~30 m (100 ft) aerials; taller roofs are reached by interior stairs
    roof = sources.vexcel_roof(bid)
    h = ((roof.get("target") or {}).get("height_est_m") if not roof.get("error") else None)
    if roof_access and isinstance(h, (int, float)) and h > 30:
        roof_access["value"] = (f"High-rise (~{h:.0f} m): roof is beyond aerial ladder reach (~30 m), use interior stairs. "
                                f"Apparatus can set up at: " + roof_access["value"].removeprefix("Aerial/ladder access from "))
        roof_access["short"] = f"high-rise, interior stairs; apparatus at {'/'.join(list(dict.fromkeys(e['side'] for e in edges))[:3])}"
        roof_access["high_rise"] = True
        roof_access["height_m"] = round(h, 1)

    res = {
        "version": VERSION,
        "building_id": bid,
        "base": {"view": view, "tile_id": tile["tile_id"], "image_url": tile["image_url"], "img_w": g["width"],
                 "img_h": g["height"], "gsd_m": gsd, "captured_at": tile.get("captured_at")},
        "footprint_px": [[round(x, 1), round(y, 1)] for x, y in simp],
        "roof_access": roof_access,
        "edges": [{"id": e["id"], "side": e["side"], "px": [e["a"], e["b"]], "latlng": [_ll(g, e["a"]), _ll(g, e["b"])],
                   "len_m": e["len_m"], "conf": e["conf"], "reason": e.get("reason"), "adjacent": e.get("adjacent"),
                   "clear_width_ft": e.get("clear_width_ft"), "verified": e.get("verified"), "verify_note": e.get("verify_note")}
                  for e in edges],
        "candidate_edges": [{"id": c["id"], "side": c["side"], "len_m": c["len_m"], "px": [c["a"], c["b"]],
                             "accessible": (by_id.get(c["id"]) or {}).get("accessible"),
                             "reason": (by_id.get(c["id"]) or {}).get("reason")} for c in cands],
        "staging": staging,
        "staging_rejected": staging_rejected,
        "staging_proposed": None if staging else [{"px": so["poly"], "labels": so["labels"]} for so in stg_opts] or None,
        "entries": final_entries,
        "entries_dropped": dropped,
        "entries_summary": summary,
        "checked": {"edges": edge_ans is not None, "staging": (stg_ans is not None) or (edge_ans is not None and not prelim),
                    "entries": ent_ans is not None, "verify": ver_ans is not None},
        "calls": log,
        "secs": round(time.time() - t_start, 1),
    }
    try:
        res["annotated_url"], res["annotated"] = _render(full, crop, box, simp, res, vdir, g)
        res["oblique_annotated"] = _render_obliques(obl, final_entries, vdir)
    except Exception as e:  # noqa: BLE001
        res["render_error"] = f"{type(e).__name__}: {e}"
    res["image_url"] = res.get("annotated_url") or tile["image_url"]
    res["cite"] = {"src": "vexcel", "id": tile["tile_id"], "conf": 0.8, "bbox": None, "url": res.get("annotated_url") or tile["image_url"]}
    ok_calls = all(not c.get("error") for c in log)
    if ok_calls:
        out_json.write_text(json.dumps(res, indent=1, default=str))
    return res


def _ll(g, p) -> list:
    d = vexcel.px_to_latlng(g, p[0], p[1])
    return [d["lat"], d["lng"]]


def _contact_sheet(entries: list):
    from PIL import Image, ImageDraw

    T, cols = 220, 5
    rows = (len(entries) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * T, rows * (T + 26)), (30, 30, 30))
    dr = ImageDraw.Draw(sheet)
    font = _font(17)
    cache: dict = {}
    for n, e in enumerate(entries, 1):
        im = cache.get(e["url"])
        if im is None:
            p = config.CACHE_DIR / e["url"].split("/static/cache/", 1)[1]
            im = cache[e["url"]] = Image.open(p).convert("RGB")
        x0, y0, x1, y1 = e["bbox"]
        side = max(140, 2.6 * max(x1 - x0, y1 - y0))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        bx = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
        tile = im.crop(tuple(int(v) for v in bx)).resize((T, T))
        k = T / side
        ImageDraw.Draw(tile).rectangle(((x0 - bx[0]) * k, (y0 - bx[1]) * k, (x1 - bx[0]) * k, (y1 - bx[1]) * k), outline=(255, 0, 0), width=3)
        r, c = divmod(n - 1, cols)
        sheet.paste(tile, (c * T, r * (T + 26)))
        dr.text((c * T + 6, r * (T + 26) + T + 3), f"#{n} {e['type']}", font=font, fill=(255, 255, 255))
    return sheet


def _render(full, crop: Crop, box, ring, res: dict, vdir: Path, g) -> tuple[str | None, dict]:
    """access_annotated.jpg: crop of the base image (full res, <=1800 px) with edges, staging, entries, legend."""
    from PIL import ImageDraw

    x0, y0, x1, y1 = [int(round(v)) for v in box]
    s = min(1.0, 1800 / max(x1 - x0, y1 - y0))
    im = full.crop((x0, y0, x1, y1)).resize((int((x1 - x0) * s), int((y1 - y0) * s)))
    T = lambda p: ((p[0] - x0) * s, (p[1] - y0) * s)  # noqa: E731
    ov = ImageDraw.Draw(im, "RGBA")
    rp = [T(p) for p in ring]
    ov.line(rp + [rp[0]], fill=(255, 40, 40, 255), width=3)
    st = res.get("staging")
    if st:
        sp = [T(p) for p in st["px"]]
        ov.polygon(sp, fill=(0, 120, 255, 95), outline=(0, 90, 255, 255))
        ov.line(sp + [sp[0]], fill=(0, 90, 255, 255), width=4)
    dr = ImageDraw.Draw(im)
    fs = max(16, int(im.size[0] / 70))
    font = _font(fs)
    for e in res["edges"]:
        a, b = T(e["px"][0]), T(e["px"][1])
        dr.line([a, b], fill=(0, 230, 0), width=max(8, int(im.size[0] / 180)))
    longest = {}
    for e in res["edges"]:
        if e["len_m"] > longest.get(e["side"], {}).get("len_m", 0):
            longest[e["side"]] = e
    for e in longest.values():
        a, b = T(e["px"][0]), T(e["px"][1])
        mx, my = a[0] + 0.25 * (b[0] - a[0]), a[1] + 0.25 * (b[1] - a[1])
        cand = _cand_normal(e, ring)
        _label(dr, (mx + cand[0] * 34, my + cand[1] * 34), f"LADDER {e['side']}", font, fill=(0, 230, 0))
    if st:
        sp = [T(p) for p in st["px"]]
        far = ((sp[2][0] + sp[3][0]) / 2, (sp[2][1] + sp[3][1]) / 2)  # far side, away from the wall label
        cen = (sum(p[0] for p in sp) / 4, sum(p[1] for p in sp) / 4)
        _label(dr, (far[0] + (far[0] - cen[0]) * 0.6, far[1] + (far[1] - cen[1]) * 0.6), "STAGING", font, fill=(0, 90, 255), fg=(255, 255, 255))
    r = max(11, int(im.size[0] / 110))
    for e in res["entries"]:
        p = (e.get("ortho_point") or {}).get("px")
        if not p:
            continue
        x, y = T(p)
        col = TYPE_COLOR.get(e["type"], (255, 255, 255))
        dr.ellipse((x - r, y - r, x + r, y + r), fill=col, outline=(0, 0, 0), width=2)
        f2 = _font(int(r * 1.3))
        tb = dr.textbbox((0, 0), str(e["n"]), font=f2)
        dr.text((x - (tb[2] - tb[0]) / 2 - tb[0], y - (tb[3] - tb[1]) / 2 - tb[1]), str(e["n"]), font=f2, fill=(0, 0, 0))
    # legend
    items = [((0, 230, 0), "line", "Ladder/aerial access wall"), ((0, 120, 255), "box", "Apparatus staging")]
    types_present = list(dict.fromkeys(e["type"] for e in res["entries"] if e.get("ortho_point")))
    items += [(TYPE_COLOR[t], "dot", f"{TYPE_NAME[t][1].capitalize()} (approx. position)") for t in types_present]
    lh = fs + 10
    W = int(fs * 17)
    ov2 = ImageDraw.Draw(im, "RGBA")
    ov2.rectangle((8, 8, 8 + W, 14 + lh * len(items) + 4), fill=(0, 0, 0, 170))
    for i, (col, kind, txt) in enumerate(items):
        yy = 16 + i * lh + lh // 2
        if kind == "line":
            dr.line((16, yy, 46, yy), fill=col, width=7)
        elif kind == "box":
            dr.rectangle((16, yy - 8, 46, yy + 8), fill=col)
        else:
            dr.ellipse((23, yy - 8, 39, yy + 8), fill=col, outline=(0, 0, 0))
        dr.text((56, yy - fs // 2 - 2), txt, font=font, fill=(255, 255, 255))
    att = "Vexcel Imaging US, Inc. ©"
    tb = dr.textbbox((0, 0), att, font=font)
    dr.text((im.size[0] - (tb[2] - tb[0]) - 10, im.size[1] - (tb[3] - tb[1]) - 12), att, font=font, fill=(255, 255, 255))
    p = vdir / "access_annotated.jpg"
    im.save(p, "JPEG", quality=88)
    return config.static_url(p), {"url": config.static_url(p), "crop_px": [x0, y0, x1, y1], "scale": round(s, 6),
                                  "img_w": im.size[0], "img_h": im.size[1],
                                  "note": "annotated px = (base_px - crop_px[0:2]) * scale"}


def _cand_normal(e: dict, ring: list) -> tuple[float, float]:
    a, b = e["px"]
    d = (b[0] - a[0], b[1] - a[1])
    L = math.hypot(*d) or 1
    n = (d[1] / L, -d[0] / L)
    if point_in_poly((a[0] + b[0]) / 2 + n[0] * 4, (a[1] + b[1]) / 2 + n[1] * 4, ring):
        n = (-n[0], -n[1])
    return n


def _render_obliques(obl: list, entries: list, vdir: Path) -> dict:
    """oblique_<D>_entries.jpg with numbered entry bboxes (same numbers as access_annotated.jpg)."""
    from PIL import Image, ImageDraw

    out = {}
    for m in obl:
        mine = [e for e in entries if e["cite"]["oblique"] == m["direction"]]
        mine += [e for e in entries if any(a["oblique"] == m["direction"] for a in (e.get("also_seen") or []))]
        if not mine:
            continue
        im = Image.open(m["image_path"]).convert("RGB")
        dr = ImageDraw.Draw(im)
        font = _font(24)
        for e in mine:
            bb = e["cite"]["bbox"] if e["cite"]["oblique"] == m["direction"] else \
                next(a["bbox"] for a in e["also_seen"] if a["oblique"] == m["direction"])
            col = TYPE_COLOR.get(e["type"], (255, 255, 255))
            dr.rectangle(bb, outline=col, width=4)
            _label(dr, (bb[0] + 4, bb[1] - 16), str(e["n"]), font, fill=col)
        p = vdir / f"oblique_{m['direction']}_entries.jpg"
        im.save(p, "JPEG", quality=88)
        out[m["direction"]] = config.static_url(p)
    return out


__all__ = ["analyze_access", "extract_edges", "select_edges", "validate_staging", "overlap_frac", "clip_halfplane"]
