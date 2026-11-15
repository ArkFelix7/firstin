"""Vexcel aerial imagery + derived-data tools for FirstIn.

API: Vexcel API 2.0 at https://api.vexcelgroup.com/v2  (OpenAPI spec: /v2/api-docs)
Auth: `X-API-KEY: <VEXCEL_API_KEY>` header (also accepted: ?api_key=...).

Public functions (all return JSON-serializable dicts, never raise):
  vexcel_tile(building_id, view="ortho")        view: ortho (120m) | context (300m) | N|E|S|W (-> oblique)
  vexcel_tile_at(lat, lng, view="ortho", building_id=None)
  vexcel_oblique(building_id, direction="N")    direction: N|E|S|W
  vexcel_oblique_at(lat, lng, direction="N", building_id=None)
  vexcel_roof(building_id)                       AI roof/structure attributes + DSM height + neighbours
  vexcel_roof_at(lat, lng, building_id=None)
  vexcel_footprint(building_id)                  footprint polygon (lat/lng + pixel coords on cached ortho/context)
  latlng_to_px(georef, lat, lng) / px_to_latlng(georef, x, y)   georef = result["georef"] of an ortho/context tile

Cache layout: agent/cache/vexcel/<building_id>/{ortho,context}.jpg+.json, oblique_<D>.jpg+.json,
roof.json, property_raw.json. Cache-first; live call if FIRSTIN_LIVE=1 or cache miss.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # firstin/
CACHE_ROOT = ROOT / "agent" / "cache"
VX_CACHE = CACHE_ROOT / "vexcel"
BUILDINGS_JSON = CACHE_ROOT / "buildings.json"
API = "https://api.vexcelgroup.com/v2"
STATIC_PREFIX = "/static/cache/vexcel"

VIEW_SIZES_M = {"ortho": 120, "context": 300}
OBLIQUE_SIZE_M = 120
DIRS = {"N": "north", "E": "east", "S": "south", "W": "west"}
R_EARTH = 6378137.0

# ---------------------------------------------------------------- helpers


def _key() -> str | None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    return os.getenv("VEXCEL_API_KEY")


def _live() -> bool:
    return os.getenv("FIRSTIN_LIVE", "0") == "1"


def _get(path: str, params: dict, timeout: float = 90.0):
    """GET with retries. Returns httpx.Response or raises (callers catch)."""
    import httpx

    key = _key()
    if not key:
        raise RuntimeError("VEXCEL_API_KEY not set in firstin/.env")
    last = None
    for attempt in range(3):
        try:
            r = httpx.get(f"{API}/{path.lstrip('/')}", params=params, headers={"X-API-KEY": key}, timeout=timeout)
        except Exception as e:  # network error
            last = e
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            time.sleep(2 * (attempt + 1))
            continue
        return r
    raise RuntimeError(f"Vexcel request failed: {last}")


def _err_text(r) -> str:
    try:
        j = r.json()
        return f"HTTP {r.status_code}: {j.get('message') or j}"
    except Exception:
        return f"HTTP {r.status_code}: {r.text[:200]}"


def _safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


def _pt_id(lat: float, lng: float) -> str:
    return _safe_id(f"pt_{lat:.5f}_{lng:.5f}")


def _bdir(bid: str) -> Path:
    d = VX_CACHE / _safe_id(bid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _url(bid: str, fname: str) -> str:
    return f"{STATIC_PREFIX}/{_safe_id(bid)}/{fname}"


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _write_json(p: Path, obj: Any) -> None:
    p.write_text(json.dumps(obj, indent=2, default=str))


def _same_pt(cached: dict, lat: float, lng: float) -> bool:
    try:
        return abs(float(cached["lat"]) - float(lat)) < 1e-6 and abs(float(cached["lng"]) - float(lng)) < 1e-6
    except Exception:
        return False


def _wkt_pt(lat: float, lng: float) -> str:
    return f"POINT({lng:.7f} {lat:.7f})"


def _best_coords(b: dict) -> dict:
    """Pick the coordinate most likely to sit ON the building.

    Priority: vexcel_lat/vexcel_lng (manual override) > matterport_geolocation (if within 400 m of the
    geocode; in testing it always landed inside the right footprint) > lat/lng (census geocodes are
    street-interpolated and were 30-210 m off, sometimes on the wrong building).
    """
    b = dict(b)
    if b.get("vexcel_lat") is not None and b.get("vexcel_lng") is not None:
        b["lat"], b["lng"], b["coord_source"] = float(b["vexcel_lat"]), float(b["vexcel_lng"]), "vexcel_override"
        return b
    mg = b.get("matterport_geolocation") or {}
    if mg.get("lat") is not None and mg.get("lng") is not None:
        if b.get("lat") is None or _dist_m(b["lat"], b["lng"], mg["lat"], mg["lng"]) <= 400:
            b["geocode_lat"], b["geocode_lng"] = b.get("lat"), b.get("lng")
            b["lat"], b["lng"], b["coord_source"] = float(mg["lat"]), float(mg["lng"]), "matterport_geolocation"
            return b
    if b.get("lat") is None or b.get("lng") is None:
        return {"error": f"building {b.get('building_id')} has no lat/lng"}
    b["coord_source"] = b.get("geocode_source") or "registry"
    return b


def _resolve(building_id: str) -> dict:
    """Look up lat/lng from agent/cache/buildings.json; also accepts 'pt_<lat>_<lng>' ids."""
    m = re.match(r"^pt_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)$", building_id or "")
    if m:
        return {"building_id": building_id, "lat": float(m.group(1)), "lng": float(m.group(2))}
    try:
        data = json.loads(BUILDINGS_JSON.read_text())
    except Exception as e:
        data = []
        err = f"could not read buildings.json ({BUILDINGS_JSON}): {e}"
    else:
        err = None
    if isinstance(data, dict):
        data = data.get("buildings", [])
    for b in data:
        if b.get("building_id") == building_id:
            return _best_coords(b)
    # fall back to anything previously cached for this id (e.g. test ids cached via *_at functions)
    for f in ("ortho.json", "context.json", "roof.json", "oblique_N.json"):
        c = _read_json(VX_CACHE / _safe_id(building_id or "") / f)
        if c and c.get("lat") is not None:
            return {"building_id": building_id, "lat": c["lat"], "lng": c["lng"]}
    return {"error": err or f"unknown building_id {building_id}"}


# ------------------------------------------------------------ georeferencing
# Ortho extracts are EPSG:3857 (Web Mercator); pixel size is in mercator metres.


def _merc(lat: float, lng: float) -> tuple[float, float]:
    x = math.radians(lng) * R_EARTH
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R_EARTH
    return x, y


def _unmerc(x: float, y: float) -> tuple[float, float]:
    lng = math.degrees(x / R_EARTH)
    lat = math.degrees(2 * math.atan(math.exp(y / R_EARTH)) - math.pi / 2)
    return lat, lng


def px_to_latlng(georef: dict, x: float, y: float) -> dict:
    """Pixel (x right, y down, origin top-left) -> {lat, lng}."""
    mx = georef["origin_x"] + x * georef["px_size_merc_x"]
    my = georef["origin_y"] - y * georef["px_size_merc_y"]
    lat, lng = _unmerc(mx, my)
    return {"lat": round(lat, 7), "lng": round(lng, 7)}


def latlng_to_px(georef: dict, lat: float, lng: float) -> dict:
    """{lat,lng} -> pixel {x, y} on the cached ortho/context image."""
    mx, my = _merc(lat, lng)
    return {
        "x": round((mx - georef["origin_x"]) / georef["px_size_merc_x"], 1),
        "y": round((georef["origin_y"] - my) / georef["px_size_merc_y"], 1),
    }


def _georef_for_extract(w: int, h: int, lat: float, lng: float, size_m: float) -> dict:
    """Georef for an ortho/extract JPEG requested with wkt=POINT + bbox-dimensions.

    Verified against the GeoTIFF variant of the same request: output is EPSG:3857, the requested point
    sits exactly at pixel (w/2, h/2), and pixel size is the native web-mercator zoom resolution
    (156543.0339/2^z merc-m; z=21 -> 0.0746455 merc-m ~= 6.2-6.5 cm ground in LA/Houston).
    """
    est = (size_m / math.cos(math.radians(lat))) / max(w, 1)
    z = round(math.log2(156543.03392804097 / est))
    px = 156543.03392804097 / (2 ** z)
    if abs(px - est) / est > 0.05:  # not a native zoom (resampled) -> trust measured
        px = est
    cx, cy = _merc(lat, lng)
    g = {
        "crs": "EPSG:3857",
        "width": w,
        "height": h,
        "origin_x": cx - (w / 2) * px,
        "origin_y": cy + (h / 2) * px,
        "px_size_merc_x": px,
        "px_size_merc_y": px,
        "zoom": z,
        "gsd_m": round(px * math.cos(math.radians(lat)), 4),
    }
    nw = px_to_latlng(g, 0, 0)
    se = px_to_latlng(g, w, h)
    g["bounds"] = {"north": nw["lat"], "south": se["lat"], "west": nw["lng"], "east": se["lng"]}
    g["center_px"] = latlng_to_px(g, lat, lng)
    g["note"] = "x right / y down from top-left. Use latlng_to_px / px_to_latlng (Web Mercator affine)."
    return g


# ------------------------------------------------------------------ ortho


def _pick_ortho_collection(lat: float, lng: float) -> dict | None:
    r = _get(
        "ortho/collections",
        {
            "wkt": _wkt_pt(lat, lng),
            "layer": "urban,urban-r",
            "include": "layer,collection,first-capture-date,last-capture-date,max-zoom,product-type",
            "order-by": "collection-last-capture-date-desc",
        },
    )
    feats = []
    if r.status_code == 200:
        feats = [f.get("properties", {}) for f in r.json().get("features", [])]
    feats = [f for f in feats if f.get("product-type", "final-ortho") == "final-ortho"] or feats
    if not feats:  # fall back to wide-area
        r = _get(
            "ortho/collections",
            {"wkt": _wkt_pt(lat, lng), "layer": "wide-area",
             "include": "layer,collection,first-capture-date,last-capture-date,max-zoom,product-type",
             "order-by": "collection-last-capture-date-desc"},
        )
        if r.status_code == 200:
            feats = [f.get("properties", {}) for f in r.json().get("features", [])]
    if not feats:
        return None
    feats.sort(key=lambda f: f.get("last-capture-date") or "", reverse=True)
    return feats[0]


def _fetch_ortho(bid: str, lat: float, lng: float, view: str) -> dict:
    from PIL import Image

    size = VIEW_SIZES_M[view]
    coll = _pick_ortho_collection(lat, lng)
    if not coll:
        return {"error": f"no Vexcel ortho coverage at {lat},{lng}"}
    r = _get(
        "ortho/extract",
        {
            "wkt": _wkt_pt(lat, lng),
            "layer": coll["layer"],
            "collection": coll["collection"],
            "bbox-dimensions": f"{size},{size}",
            "image-format": "jpeg",
        },
        timeout=180,
    )
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        return {"error": f"ortho/extract failed: {_err_text(r)}"}
    im = Image.open(io.BytesIO(r.content))
    georef = _georef_for_extract(im.size[0], im.size[1], lat, lng, size)
    fname = f"{view}.jpg"
    d = _bdir(bid)
    (d / fname).write_bytes(r.content)  # keep Vexcel's original JPEG bytes
    # downscaled preview for VLMs / dashboard thumbnails (same georef scaled by preview_scale)
    pv = im.convert("RGB")
    pv.thumbnail((1600, 1600))
    pv.save(d / f"{view}_1600.jpg", "JPEG", quality=88)
    tile_id = f"{coll['collection']}/{coll['layer']}/{view}@{lat:.6f},{lng:.6f}"
    res = {
        "building_id": bid,
        "view": view,
        "tile_id": tile_id,
        "image_path": str(d / fname),
        "image_url": _url(bid, fname),
        "lat": lat,
        "lng": lng,
        "extent_m": size,
        "gsd_m": georef["gsd_m"],
        "captured_at": coll.get("last-capture-date"),
        "capture_window": [coll.get("first-capture-date"), coll.get("last-capture-date")],
        "collection": coll["collection"],
        "layer": coll["layer"],
        "georef": georef,
        "preview_path": str(d / f"{view}_1600.jpg"),
        "preview_url": _url(bid, f"{view}_1600.jpg"),
        "preview_scale": round(pv.size[0] / im.size[0], 6),
        "orientation": "north-up, top-down orthomosaic",
        "cite": {"src": "vexcel", "id": tile_id, "conf": 0.95, "bbox": None, "url": _url(bid, fname)},
    }
    _write_json(d / f"{view}.json", res)
    return res


def vexcel_tile_at(lat: float, lng: float, view: str = "ortho", building_id: str | None = None) -> dict:
    try:
        bid = building_id or _pt_id(lat, lng)
        v = (view or "ortho").strip()
        if v.upper() in DIRS or v.lower().startswith("oblique"):
            d = v.split("_")[-1].upper()[:1] if "_" in v else v.upper()[:1]
            return vexcel_oblique_at(lat, lng, d if d in DIRS else "N", bid)
        v = v.lower()
        if v in ("ortho_context", "wide"):
            v = "context"
        if v not in VIEW_SIZES_M:
            return {"error": f"unknown view {view!r}; use ortho|context|N|E|S|W"}
        meta = VX_CACHE / _safe_id(bid) / f"{v}.json"
        if not _live():
            cached = _read_json(meta)
            if cached and Path(cached.get("image_path", "")).exists() and _same_pt(cached, lat, lng):
                cached["cached"] = True
                return cached
        return _fetch_ortho(bid, float(lat), float(lng), v)
    except Exception as e:
        # last resort: stale cache
        try:
            cached = _read_json(VX_CACHE / _safe_id(building_id or _pt_id(lat, lng)) / f"{view}.json")
            if cached:
                cached["cached"] = True
                cached["warning"] = f"live fetch failed: {e}"
                return cached
        except Exception:
            pass
        return {"error": f"vexcel_tile failed: {e}"}


def vexcel_tile(building_id: str, view: str = "ortho") -> dict:
    """Top-down ortho (view='ortho' ~120m, 'context' ~300m) or oblique (view='N'|'E'|'S'|'W')."""
    try:
        b = _resolve(building_id)
        if "error" in b:
            return b
        return vexcel_tile_at(b["lat"], b["lng"], view, building_id)
    except Exception as e:
        return {"error": f"vexcel_tile failed: {e}"}


# ---------------------------------------------------------------- oblique


def _fetch_oblique(bid: str, lat: float, lng: float, direction: str) -> dict:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = None

    pt = f"oblique-{DIRS[direction]}"
    base = {
        "wkt": _wkt_pt(lat, lng),
        "product-type": pt,
        "order-by": "collection-last-capture-date-desc,image-center-distance-asc",
    }
    q = None
    for layer in ("urban", "urban-r", "wide-area", None):
        params = dict(base, **{"include": "image-name,capture-date,collection,product-type,layer", "total-records": 1})
        if layer:
            params["layer"] = layer
        r = _get("oriented/query", params)
        if r.status_code == 200:
            feats = r.json().get("features", [])
            if feats:
                q = feats[0]["properties"]
                break
    if not q:
        return {"error": f"no {pt} imagery at {lat},{lng}"}
    r = _get(
        "oriented/extract",
        {
            "wkt": _wkt_pt(lat, lng),
            "image-name": q["image-name"],
            "bbox-dimensions": f"{OBLIQUE_SIZE_M},{OBLIQUE_SIZE_M}",
            "crop": "bbox",  # REQUIRED with image-name, else the full ~150MP frame comes back
            "image-format": "jpeg",
        },
        timeout=180,
    )
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
        return {"error": f"oriented/extract failed: {_err_text(r)}"}
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content))).convert("RGB")
    fname = f"oblique_{direction}.jpg"
    d = _bdir(bid)
    im.save(d / fname, "JPEG", quality=90)
    res = {
        "building_id": bid,
        "view": f"oblique_{direction}",
        "direction": direction,
        "product_type": pt,
        "camera_looking": DIRS[direction],
        # verified visually: oblique-south has image-top = south and shows the building's NORTH facade
        "shows_facade": {"N": "south", "E": "west", "S": "north", "W": "east"}[direction],
        "image_top": DIRS[direction],
        "tile_id": q["image-name"],
        "image_path": str(d / fname),
        "image_url": _url(bid, fname),
        "lat": lat,
        "lng": lng,
        "extent_m": OBLIQUE_SIZE_M,
        "width": im.size[0],
        "height": im.size[1],
        "center_px": {"x": im.size[0] / 2, "y": im.size[1] / 2},
        "captured_at": q.get("capture-date"),
        "collection": q.get("collection"),
        "layer": q.get("layer"),
        "orientation": "natural (aircraft forward-up); building at image centre; not georectified - "
        "pixel coords are image-relative only",
        "cite": {"src": "vexcel", "id": q["image-name"], "conf": 0.9, "bbox": None, "url": _url(bid, fname)},
    }
    _write_json(d / f"oblique_{direction}.json", res)
    return res


def vexcel_oblique_at(lat: float, lng: float, direction: str = "N", building_id: str | None = None) -> dict:
    try:
        bid = building_id or _pt_id(lat, lng)
        dr = (direction or "N").strip().upper()[:1]
        if dr not in DIRS:
            return {"error": f"direction must be N|E|S|W, got {direction!r}"}
        meta = VX_CACHE / _safe_id(bid) / f"oblique_{dr}.json"
        if not _live():
            cached = _read_json(meta)
            if cached and Path(cached.get("image_path", "")).exists() and _same_pt(cached, lat, lng):
                cached["cached"] = True
                return cached
        return _fetch_oblique(bid, float(lat), float(lng), dr)
    except Exception as e:
        cached = _read_json(VX_CACHE / _safe_id(building_id or _pt_id(lat, lng)) / f"oblique_{str(direction)[:1].upper()}.json")
        if cached:
            cached["cached"] = True
            cached["warning"] = f"live fetch failed: {e}"
            return cached
        return {"error": f"vexcel_oblique failed: {e}"}


def vexcel_oblique(building_id: str, direction: str = "N") -> dict:
    """Oblique (45-degree) view. direction N|E|S|W = Vexcel product oblique-<dir> (camera looking <dir>)."""
    try:
        b = _resolve(building_id)
        if "error" in b:
            return b
        return vexcel_oblique_at(b["lat"], b["lng"], direction, building_id)
    except Exception as e:
        return {"error": f"vexcel_oblique failed: {e}"}


# ------------------------------------------------------------ derived data


def _parse_wkt_polys(wkt: str) -> list[list[tuple[float, float]]]:
    """Return outer rings [(lng,lat),...] of a POLYGON/MULTIPOLYGON WKT."""
    rings = []
    if not wkt:
        return rings
    for grp in re.findall(r"\(\(([^()]+)\)", wkt):
        pts = []
        for p in grp.split(","):
            xy = p.strip().split()
            if len(xy) >= 2:
                pts.append((float(xy[0]), float(xy[1])))
        if pts:
            rings.append(pts)
    return rings


def _pip(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


def _dist_m(lat1, lng1, lat2, lng2) -> float:
    kx = 111320 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lng2 - lng1) * kx, (lat2 - lat1) * 110540)


def _ring_dist_m(lat, lng, ring) -> float:
    """Min distance (m) from point to polygon ring vertices/edges (0 if inside)."""
    if _pip(lng, lat, ring):
        return 0.0
    kx = 111320 * math.cos(math.radians(lat))
    ky = 110540
    px, py = 0.0, 0.0
    best = 1e18
    pts = [((x - lng) * kx, (y - lat) * ky) for x, y in ring]
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


def _ring_ring_dist_m(r1, r2) -> float:
    return min(_ring_dist_m(lat, lng, r2) for lng, lat in r1[:: max(1, len(r1) // 60)])


def _inside_point_near(lat: float, lng: float, ring, inset_m: float = 8.0) -> dict | None:
    """Point inside the footprint close to (lat,lng): nearest boundary point pushed inset_m inward."""
    if not ring:
        return None
    if _pip(lng, lat, ring):
        return {"lat": lat, "lng": lng}
    kx = 111320 * math.cos(math.radians(lat))
    ky = 110540
    pts = [((x - lng) * kx, (y - lat) * ky) for x, y in ring]
    best, bx, by = 1e18, 0.0, 0.0
    for i in range(len(pts)):
        ax, ay = pts[i]
        cx, cy = pts[(i + 1) % len(pts)]
        dx, dy = cx - ax, cy - ay
        t = 0.0 if dx == dy == 0 else max(0, min(1, (-ax * dx - ay * dy) / (dx * dx + dy * dy)))
        qx, qy = ax + t * dx, ay + t * dy
        dd = math.hypot(qx, qy)
        if dd < best:
            best, bx, by = dd, qx, qy
    if best == 0:
        return None
    for inset in (inset_m, inset_m / 2, 3.0, 1.5):
        ux, uy = bx / best, by / best
        px, py = bx + ux * inset, by + uy * inset
        plng, plat = lng + px / kx, lat + py / ky
        if _pip(plng, plat, ring):
            return {"lat": round(plat, 7), "lng": round(plng, 7)}
    return None


def _pct(vals: list[float], q: float) -> float:
    v = sorted(vals)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def _footprint_samples(lat: float, lng: float, target: dict, max_pts: int = 40) -> list[tuple[float, float]]:
    """(lat,lng) sample points inside the footprint: centroid, near-address point, and a grid."""
    ring = target.get("footprint_ring_lnglat")
    out = []
    c = target.get("roof_centroid")
    if c:
        out.append((c["lat"], c["lng"]))
    n = _inside_point_near(lat, lng, ring)
    if n:
        out.append((n["lat"], n["lng"]))
    if ring:
        xs = [x for x, _ in ring]
        ys = [y for _, y in ring]
        k = 9
        for i in range(k):
            for j in range(k):
                x = min(xs) + (max(xs) - min(xs)) * (i + 0.5) / k
                y = min(ys) + (max(ys) - min(ys)) * (j + 0.5) / k
                if _pip(x, y, ring):
                    out.append((y, x))
        # extra ring of points around the near-address point (merged blocks)
        if n:
            for dx, dy in ((8, 0), (-8, 0), (0, 8), (0, -8), (14, 14), (-14, -14), (14, -14), (-14, 14)):
                y = n["lat"] + dy / 110540
                x = n["lng"] + dx / (111320 * math.cos(math.radians(lat)))
                if _pip(x, y, ring):
                    out.append((y, x))
    return out[: max_pts + 10]


def _dsm_many(pts: list[tuple[float, float]]) -> list[float | None]:
    """DSM elevations for many points in one call (LINESTRING -> LINESTRING Z)."""
    if not pts:
        return []
    if len(pts) == 1:
        return [_elev("dsm/elevation", pts[0][0], pts[0][1])]
    wkt = "LINESTRING(" + ", ".join(f"{p[1]:.7f} {p[0]:.7f}" for p in pts) + ")"
    for layer in ("urban", "wide-area"):
        try:
            r = _get("dsm/elevation", {"wkt": wkt, "layer": layer})
        except Exception:
            continue
        if r.status_code != 200:
            continue
        w = r.json().get("wkt", "")
        m = re.search(r"\((.*)\)", w)
        if not m:
            continue
        zs = []
        for tok in m.group(1).split(","):
            parts = tok.split()
            zs.append(float(parts[2]) if len(parts) >= 3 else None)
        if len(zs) == len(pts):
            return zs
    return [None] * len(pts)


def _bearing_side(lat0, lng0, lat1, lng1) -> str:
    ang = math.degrees(math.atan2((lng1 - lng0) * math.cos(math.radians(lat0)), lat1 - lat0)) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((ang + 22.5) // 45) % 8]


def _g(d: dict, *path, default=None):
    for p in path:
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return d if d is not None else default


def _elev(path: str, lat: float, lng: float) -> float | None:
    try:
        r = _get(path, {"wkt": _wkt_pt(lat, lng), "layer": "urban"})
        if r.status_code != 200:
            r = _get(path, {"wkt": _wkt_pt(lat, lng), "layer": "wide-area"})
        if r.status_code != 200:
            return None
        m = re.search(r"POINT Z\s*\(\s*\S+\s+\S+\s+(-?[\d.]+)", r.json().get("wkt", ""))
        return float(m.group(1)) if m else None
    except Exception:
        return None


_CONDITION = {1: "severe", 2: "poor", 3: "fair", 4: "good", 5: "excellent"}


def _summ_structure(s: dict, lat: float, lng: float) -> dict:
    """Vexcel property/extract structures use flat dotted keys, e.g. 'roof-characteristics.material.class'."""
    rings = _parse_wkt_polys(s.get("footprint.wkt") or "")
    cpt = None
    m = re.search(r"\(\s*(-?[\d.]+)\s+(-?[\d.]+)", s.get("roof-characteristics.centroid.wkt") or "")
    if m:
        cpt = {"lat": float(m.group(2)), "lng": float(m.group(1))}
    cond = s.get("roof-characteristics.condition")
    objects = {}
    for k, v in s.items():
        if k.startswith("roof-objects.") and (k.endswith(".count") or k.endswith(".value")) and v is not None:
            objects[k.split(".")[1]] = v
    defects = {}
    for k, v in s.items():
        if k.startswith("roof-defects.") and k.endswith(".detected") and v:
            name = k[len("roof-defects."): -len(".detected")].replace("discoloration.types.", "")
            defects[name] = s.get(k[: -len(".detected")] + ".percent")
    out = {
        "footprint_wkt": s.get("footprint.wkt"),
        "footprint_area_m2": s.get("footprint.area"),
        "footprint_ring_lnglat": rings[0] if rings else None,
        "roof_centroid": cpt,
        "roof_material": s.get("roof-characteristics.material.class"),
        "roof_material_score": s.get("roof-characteristics.material.score"),
        "roof_shape": s.get("roof-characteristics.shape.value"),
        "roof_shape_score": s.get("roof-characteristics.shape.score"),
        "roof_condition_1to5": cond,
        "roof_condition_label": _CONDITION.get(int(round(cond))) if isinstance(cond, (int, float)) else None,
        "roof_objects": objects,
        "roof_defects_pct": defects,
        "roof_tree_cover_pct": s.get("roof-characteristics.tree-cover.percent"),
        "building_type": s.get("building-type.class"),
        "building_type_score": s.get("building-type.score"),
        "primary_structure": s.get("primary-structure"),
        "ground_elev_m": s.get("ground-elevation.value"),
        "max_roof_height_m": s.get("roof-characteristics.maximum-roof-height"),
        "eave_height_m": s.get("roof-characteristics.eave-height"),
        "stories_below_eave": s.get("roof-characteristics.number-of-stories-below-eave"),
        "defensible_space": {k.split(".", 1)[1]: v for k, v in s.items() if k.startswith("defensible-space.")},
    }
    out["distance_to_point_m"] = round(_ring_dist_m(lat, lng, rings[0]), 1) if rings else None
    return out


def _fetch_roof(bid: str, lat: float, lng: float) -> dict:
    r = _get("property/extract", {"wkt": _wkt_pt(lat, lng), "buffer-meter": 60})
    if r.status_code != 200:
        return {"error": f"property/extract: {_err_text(r)}"}
    raw = r.json()
    d = _bdir(bid)
    _write_json(d / "property_raw.json", raw)
    feats = raw.get("features", [])
    structs = []
    meta = {}
    for f in feats:
        p = f.get("properties", {})
        if not meta:
            meta = {k: v for k, v in p.items() if k.startswith("metadata")}
        for s in p.get("structures", []) or []:
            structs.append(_summ_structure(s, lat, lng))
    if not structs:
        return {"error": f"no Vexcel structure data at {lat},{lng}"}
    # target = structure containing/nearest to point, prefer larger footprints among ties
    structs.sort(key=lambda s: ((s["distance_to_point_m"] if s["distance_to_point_m"] is not None else 1e9),
                                -(s["footprint_area_m2"] or 0)))
    target = structs[0]
    # ignore tiny sheds as the target when a big building is within 15 m
    if (target["footprint_area_m2"] or 0) < 40:
        bigger = [s for s in structs if (s["footprint_area_m2"] or 0) >= 40 and (s["distance_to_point_m"] or 1e9) <= 15]
        if bigger:
            target = bigger[0]
    # height = DSM - ground, sampled on a grid inside the footprint in ONE dsm/elevation call (LINESTRING Z).
    # Footprints > 5000 m2 are often merged downtown blocks -> use samples within 25 m of the address point.
    ground = target.get("ground_elev_m")
    if ground is None:
        ground = _elev("dtm/elevation", lat, lng)
    pts = _footprint_samples(lat, lng, target)
    zs = _dsm_many(pts) if pts and ground is not None else []
    hs = [(p, z - ground) for p, z in zip(pts, zs) if z is not None]
    area = target.get("footprint_area_m2") or 0
    near = [h for p, h in hs if _dist_m(lat, lng, p[0], p[1]) <= 25]
    allh = [h for _, h in hs]
    target["height_p90_m"] = round(_pct(allh, 0.9), 1) if allh else None
    target["height_max_m"] = round(max(allh), 1) if allh else None
    target["height_near_address_m"] = round(_pct(near, 0.75), 1) if near else None
    target["height_samples_n"] = len(allh)
    if area > 5000 and near:
        height, basis = target["height_near_address_m"], "p75 of DSM samples within 25 m of address (large/merged footprint)"
    else:
        height, basis = target["height_p90_m"], "p90 of DSM samples inside footprint"
    target["height_est_m"] = height
    target["height_basis"] = basis
    target["roof_elev_dsm_m"] = round(ground + height, 2) if height is not None and ground is not None else None
    target["stories_est"] = max(1, round(height / 3.8)) if height and height > 2 else None
    # exposures: other structures with footprint > 30 m2 within ~30 m of target
    exposures = []
    tr = target.get("footprint_ring_lnglat")
    tc = target.get("roof_centroid") or {"lat": lat, "lng": lng}
    if tr:
        for s in structs:
            if s is target or not s.get("footprint_ring_lnglat") or (s["footprint_area_m2"] or 0) < 30:
                continue
            gap = _ring_ring_dist_m(s["footprint_ring_lnglat"], tr)
            if gap <= 30:
                sc = s.get("roof_centroid") or {"lat": s["footprint_ring_lnglat"][0][1], "lng": s["footprint_ring_lnglat"][0][0]}
                exposures.append({
                    "side": _bearing_side(tc["lat"], tc["lng"], sc["lat"], sc["lng"]),
                    "gap_m": round(gap, 1),
                    "footprint_area_m2": s["footprint_area_m2"],
                    "roof_material": s["roof_material"],
                    "building_type": s["building_type"],
                    "roof_centroid": s.get("roof_centroid"),
                })
        exposures.sort(key=lambda e: e["gap_m"])
    coll = meta.get("metadata.collection") or _g(meta, "metadata", "collection")
    rid = f"{coll}/property@{lat:.6f},{lng:.6f}"
    conf = target.get("roof_material_score") or target.get("building_type_score") or 0.7
    res = {
        "building_id": bid,
        "lat": lat,
        "lng": lng,
        "target": target,
        "exposures": exposures[:12],
        "structure_count_within_60m": len(structs),
        "collection": coll,
        "ortho_date_estimate": meta.get("metadata.ortho-date-estimate"),
        "gsd_m": meta.get("metadata.gsd"),
        "notes": "AI-derived Vexcel elements (property/extract). height_est_m = DSM (near-address point inside footprint, else roof centroid) - ground elevation; "
        "dense-downtown footprints may merge adjacent row buildings into one block polygon; "
        "stories_est = height/3.7m (inference). roof_condition 1=severe..5=excellent.",
        "cite": {"src": "vexcel", "id": rid, "conf": round(float(conf), 2), "bbox": None,
                 "url": _url(bid, "property_raw.json")},
    }
    _write_json(d / "roof.json", res)
    return res


def vexcel_roof_at(lat: float, lng: float, building_id: str | None = None) -> dict:
    try:
        bid = building_id or _pt_id(lat, lng)
        if not _live():
            cached = _read_json(VX_CACHE / _safe_id(bid) / "roof.json")
            if cached and _same_pt(cached, lat, lng):
                cached["cached"] = True
                return cached
        return _fetch_roof(bid, float(lat), float(lng))
    except Exception as e:
        cached = _read_json(VX_CACHE / _safe_id(building_id or _pt_id(lat, lng)) / "roof.json")
        if cached:
            cached["cached"] = True
            cached["warning"] = f"live fetch failed: {e}"
            return cached
        return {"error": f"vexcel_roof failed: {e}"}


def vexcel_roof(building_id: str) -> dict:
    """AI roof attributes (material, shape, condition, rooftop objects/defects), building type,
    DSM-derived height/stories estimate, and adjacent-structure exposures (side + gap in metres)."""
    try:
        b = _resolve(building_id)
        if "error" in b:
            return b
        return vexcel_roof_at(b["lat"], b["lng"], building_id)
    except Exception as e:
        return {"error": f"vexcel_roof failed: {e}"}


def vexcel_footprint(building_id: str) -> dict:
    """Building footprint polygon in lat/lng and in pixel coords of the cached ortho/context tiles
    (draw it, or use its pixel bbox as a citation bbox)."""
    try:
        roof = vexcel_roof(building_id)
        if "error" in roof:
            return roof
        ring = roof["target"].get("footprint_ring_lnglat")
        if not ring:
            return {"error": "no footprint geometry"}
        out = {
            "building_id": building_id,
            "footprint_latlng": [[lat, lng] for lng, lat in ring],
            "footprint_area_m2": roof["target"].get("footprint_area_m2"),
            "on_images": {},
            "cite": roof["cite"],
        }
        b = _resolve(building_id)
        for view in ("ortho", "context"):
            t = vexcel_tile(building_id, view) if "error" not in b else {"error": "unresolved"}
            if "georef" not in t:
                continue
            pts = [latlng_to_px(t["georef"], lat, lng) for lng, lat in ring]
            xs = [p["x"] for p in pts]
            ys = [p["y"] for p in pts]
            out["on_images"][view] = {
                "tile_id": t["tile_id"],
                "image_url": t["image_url"],
                "polygon_px": [[p["x"], p["y"]] for p in pts],
                "bbox_px": [min(xs), min(ys), max(xs), max(ys)],
            }
        return out
    except Exception as e:
        return {"error": f"vexcel_footprint failed: {e}"}


__all__ = [
    "vexcel_tile", "vexcel_tile_at", "vexcel_oblique", "vexcel_oblique_at",
    "vexcel_roof", "vexcel_roof_at", "vexcel_footprint", "latlng_to_px", "px_to_latlng",
]
