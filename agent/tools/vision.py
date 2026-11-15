"""VLM image analysis (Anthropic Messages API), cached on disk.

describe_image(image_path, question) -> {answer, findings, detections:[{label,bbox,conf}], ...}
bbox is in PIXELS of the source image: [x0, y0, x1, y1]; img_w/img_h are returned.

Cache key = sha1(image bytes + question) -> agent/cache/vision/<key>.json. Offline mode
only ever reads the cache, so the offline demo replays real VLM answers once
`make warm-vision` has been run with an API key. Always use the canonical questions
below (AERIAL_QUESTION / INTERIOR_QUESTION) so live and offline runs share cache keys.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from pathlib import Path

from .. import config

AERIAL_QUESTION = """You are a fire-service pre-incident planning analyst looking at a top-down (or oblique) aerial image of a commercial building. The target building is the one at the image centre.
Report ONLY what is visible. If something cannot be seen, set value to null.
Return JSON with keys:
 "roof_type": flat/pitched/barrel/sawtooth etc + material cues (HVAC units, skylights, parapet),
 "roof_access": likely ladder/aerial placement side and what is adjacent (alley, lot, street),
 "staging": best apparatus staging area (side + description),
 "hydrants": visible hydrants (often not visible from air -> null),
 "exposures": list of adjacent buildings with side (N/E/S/W, image-up = north unless stated), approx stories, approx gap in feet,
 "access_roads": streets/alleys/driveways serving the building,
 "fdc": any visible fire department connection (usually null from air).
Each of roof_type, roof_access, staging, hydrants, access_roads, fdc is an object {"value": str|null, "conf": 0-1, "bbox": [x0,y0,x1,y1] pixels or null}.
"exposures" is a list of {"side": str, "desc": str, "conf": 0-1, "bbox": [...]}."""

INTERIOR_QUESTION = """You are a fire-service pre-incident planning analyst looking at a 360/interior panorama from a building's 3D scan.
Identify ONLY clearly visible fire-relevant features: stairwell/stair door, elevator, standpipe/hose valve, fire department connection, fire alarm control panel, sprinkler heads/riser, fire extinguisher, electrical room/panel, exit sign/exit door, gas meter, hazardous material storage (drums, chemical containers, pallets of product), roof hatch/ladder.
Return JSON: {"room_guess": str|null, "findings": {"<feature>": {"value": short description, "conf": 0-1, "bbox": [x0,y0,x1,y1] pixels or null}}}.
Omit features that are not visible. Do not guess."""

_JSON_TAIL = (
    "\n\nRespond with ONLY a JSON object (no prose, no markdown fences). "
    'Include also "summary" (one sentence) and "detections": a flat list of {"label", "bbox", "conf"} for every boxed item.'
)


def _cache_key(image_bytes: bytes, question: str) -> str:
    h = hashlib.sha1()
    h.update(image_bytes)
    h.update(question.encode())
    return h.hexdigest()


def _media_type(path: Path) -> str:
    return {".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")


def _image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return im.size
    except Exception:  # noqa: BLE001
        return None, None


def _prepare_bytes(path: Path) -> tuple[bytes, str, float]:
    """Return (bytes_to_send, media_type, scale) - downsizes huge images (API limit ~8000px / 5MB)."""
    raw = path.read_bytes()
    try:
        from PIL import Image
        import io

        with Image.open(path) as im:
            w, h = im.size
            if max(w, h) <= 2000 and len(raw) < 4_500_000:
                return raw, _media_type(path), 1.0
            scale = 2000 / max(w, h)
            im2 = im.convert("RGB").resize((int(w * scale), int(h * scale)))
            buf = io.BytesIO()
            im2.save(buf, format="JPEG", quality=88)
            return buf.getvalue(), "image/jpeg", scale
    except Exception:  # noqa: BLE001
        return raw, _media_type(path), 1.0


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"summary": text}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"summary": text}


def _rescale(obj, s: float):
    if s == 1.0:
        return obj
    if isinstance(obj, dict):
        return {k: (_rescale_bbox(v, s) if k == "bbox" else _rescale(v, s)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rescale(v, s) for v in obj]
    return obj


def _rescale_bbox(b, s):
    if isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) for x in b):
        return [round(x / s) for x in b]
    return b


def cached_answer(image_path: str, question: str) -> dict | None:
    p = Path(image_path)
    if not p.exists():
        return None
    f = config.VISION_CACHE_DIR / f"{_cache_key(p.read_bytes(), question)}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:  # noqa: BLE001
            return None
    return None


def describe_image(image_path: str, question: str, allow_live: bool | None = None) -> dict:
    """Ask the VLM a question about a local image. Returns structured detections with pixel bboxes + conf."""
    p = Path(image_path)
    if not p.is_absolute() and not p.exists():
        p = (config.ROOT / image_path)
    if not p.exists():
        return {"error": f"image not found: {image_path}"}
    w, h = _image_size(p)
    hit = cached_answer(str(p), question)
    if hit:
        return {**hit, "cached": True}
    if allow_live is None:
        allow_live = config.has_api_key()
    if not allow_live:
        return {"error": "no cached vision answer and no API key (offline)", "image_path": str(p),
                "image_url": config.static_url(p), "img_w": w, "img_h": h, "detections": []}
    try:
        import anthropic

        data, media, scale = _prepare_bytes(p)
        client = anthropic.Anthropic()
        size_note = f"\nThe image you see is {int((w or 0) * scale)}x{int((h or 0) * scale)} pixels; give bboxes in those pixel coordinates."
        resp = client.messages.create(
            model=config.vision_model_name(),
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()}},
                    {"type": "text", "text": question + size_note + _JSON_TAIL},
                ],
            }],
        )
        if resp.stop_reason == "refusal":
            return {"error": "vision model refused", "detections": []}
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        parsed = _rescale(_parse_json(text), scale)
    except Exception as e:  # noqa: BLE001 - never raise
        return {"error": f"vision call failed: {type(e).__name__}: {e}", "detections": []}
    out = {
        "answer": parsed.get("summary"),
        "findings": {k: v for k, v in parsed.items() if k not in ("summary", "detections")},
        "detections": parsed.get("detections") or [],
        "image_path": str(p),
        "image_url": config.static_url(p),
        "img_w": w,
        "img_h": h,
        "model": config.vision_model_name(),
        "question_sha1": hashlib.sha1(question.encode()).hexdigest()[:10],
        "created_at": time.time(),
    }
    config.VISION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (config.VISION_CACHE_DIR / f"{_cache_key(p.read_bytes(), question)}.json").write_text(json.dumps(out, indent=1))
    return {**out, "cached": False}


OBLIQUE_NOTE = ("\nThis is an OBLIQUE (angled) aerial photo; the visible facade of the target building is its "
                "{facade} side. Report sides relative to the building (N/E/S/W), not the image.")


def analyze_aerial_image(image_path: str, preview_path: str | None = None, preview_scale: float | None = None,
                         shows_facade: str | None = None) -> dict:
    """Canonical aerial survey (roof, access, staging, hydrants, exposures) of a Vexcel image.

    If preview_path/preview_scale are given (Vexcel 1600px preview), the VLM sees the preview and
    bboxes are scaled back to full-resolution `image_path` pixels. shows_facade marks obliques.
    """
    q = AERIAL_QUESTION + (OBLIQUE_NOTE.format(facade=shows_facade) if shows_facade else "")
    src = preview_path if preview_path and Path(preview_path).exists() else image_path
    res = describe_image(src, q)
    if src != image_path and not res.get("error") and preview_scale:
        res = _rescale(res, float(preview_scale))
        res["preview_path"], res["image_path"] = src, image_path
        res["image_url"] = config.static_url(image_path)
        w, h = _image_size(Path(image_path))
        res["img_w"], res["img_h"] = w, h
    return res


def analyze_interior_image(image_path: str) -> dict:
    """Canonical fire-feature scan (stairs, standpipe, FACP, electrical...) of a Matterport panorama."""
    return describe_image(image_path, INTERIOR_QUESTION)
