"""Matterport tools (see CONTRACTS.md).

Cache-first: reads agent/cache/matterport/<building_id>/{model.json,panos.json}.
Live (GraphQL https://api.matterport.com/api/models/graph) when FIRSTIN_LIVE=1 or on cache miss.
Never raises: returns {"error": ...} on failure.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

CACHE = ROOT / "agent" / "cache" / "matterport"
REGISTRY = ROOT / "agent" / "cache" / "buildings.json"
STATIC_PREFIX = "/static/cache/matterport"

# room_filter synonyms -> Matterport room tags / words to match
SYNONYMS = {
    "stair": ["staircase", "stairs", "stair"],
    "electrical": ["utility", "electrical", "mechanical", "basement"],
    "mechanical": ["utility", "mechanical", "electrical", "basement"],
    "utility": ["utility", "laundry", "basement", "mechanical"],
    "lobby": ["lobby", "entrance", "foyer", "mail"],
    "entrance": ["entrance", "foyer", "lobby"],
    "entry": ["entrance", "foyer", "lobby"],
    "hall": ["hallway", "corridor"],
    "corridor": ["hallway", "corridor"],
    "garage": ["garage", "parking"],
    "kitchen": ["kitchen", "dining"],
    "storage": ["storage", "closet", "basement"],
}


def _live() -> bool:
    return os.environ.get("FIRSTIN_LIVE") == "1"


def _show_url(model_id: str, sweep_label: str | None = None) -> str:
    url = f"https://my.matterport.com/show/?m={model_id}"
    if sweep_label not in (None, ""):
        url += f"&ss={sweep_label}"  # Showcase start-sweep deep link (sweep number label)
    return url


def _cite(model_id: str, id_: str | None = None, sweep_label: str | None = None, conf: float = 0.9) -> dict:
    return {"src": "matterport", "id": id_ or model_id, "conf": conf, "bbox": None,
            "url": _show_url(model_id, sweep_label), "from": None}


def _registry_entry(building_id: str) -> dict | None:
    try:
        for b in json.loads(REGISTRY.read_text()):
            if b.get("building_id") == building_id:
                return b
    except Exception:
        pass
    return None


def _refresh_live(building_id: str) -> dict | None:
    """Re-fetch metadata (and panoramas) from the live API into the cache. Returns meta or None."""
    try:
        from agent.scripts import mp_cache  # lazy: needs httpx, PIL, numpy
        pick = next((p for p in mp_cache.PICKS if p["building_id"] == building_id), None)
        if pick is None:
            b = _registry_entry(building_id)
            if not b or not b.get("matterport_model_ids"):
                return None
            # registry lists model ids richest-first (registry_build.py); cap so a 20-scan property
            # still generates in ~15-30 s on a cold cache
            cap = int(os.environ.get("FIRSTIN_MP_MAX_MODELS", "6"))
            pick = {"building_id": building_id, "address": b.get("address"), "city": b.get("city"),
                    "name": b.get("name") or b.get("address"), "model_ids": b["matterport_model_ids"][:cap]}
        return mp_cache.cache_building(pick)
    except Exception as e:  # noqa: BLE001
        return {"_live_error": f"{type(e).__name__}: {e}"}


def _load(building_id: str, want_live: bool) -> tuple[dict | None, dict | None, str | None]:
    bdir = CACHE / building_id
    live_err = None
    if want_live or not (bdir / "model.json").exists():
        meta = _refresh_live(building_id)
        if isinstance(meta, dict) and meta.get("_live_error"):
            live_err = meta["_live_error"]
    try:
        meta = json.loads((bdir / "model.json").read_text())
    except Exception:
        msg = f"no Matterport data for building {building_id}"
        return None, None, msg + (f" (live fetch failed: {live_err})" if live_err else "")
    try:
        panos = json.loads((bdir / "panos.json").read_text())
    except Exception:
        panos = {"panos": []}
    return meta, panos, None


def _bfloor(md: dict, seq) -> int | None:
    """Best-effort building floor (1-based). Single-floor suite scans use the floor inferred from the suite name."""
    if seq is None:
        return None
    hint = md.get("building_floor_hint")
    if hint and len(md.get("floors") or []) <= 1:
        return hint
    if hint and len(md.get("floors") or []) > 1:
        return hint + seq
    return seq + 1


def _primary(models: list[dict]) -> dict:
    return max(models, key=lambda m: m.get("sweep_count", 0))


def matterport_model(building_id: str) -> dict:
    """Building interior summary: floors, rooms (label, floor, bounds, id), mattertags, sweep_count, cite."""
    try:
        meta, _, err = _load(building_id, _live())
        if err:
            return {"error": err, "building_id": building_id}
        models = meta.get("models") or []
        if not models:
            return {"error": "no models cached", "building_id": building_id}
        prim = _primary(models)
        floors, rooms, tags, plans, scans = [], [], [], [], []
        for md in models:
            mid = md["model_id"]
            scans.append({"model_id": mid, "name": md.get("name"), "sweep_count": md.get("sweep_count"),
                          "floors": len(md.get("floors") or []), "building_floor_hint": md.get("building_floor_hint"),
                          "url": _show_url(mid), "created": md.get("created")})
            for f in md.get("floors") or []:
                floors.append({"model_id": mid, "scan": md.get("name"), "id": f["id"], "label": f.get("label"),
                               "model_floor_seq": f["sequence"], "floor": _bfloor(md, f["sequence"]),
                               "area_sqft": f.get("area_sqft")})
            for r in md.get("rooms") or []:
                rooms.append({"id": r["id"], "label": r.get("label"), "tags": r.get("tags"),
                              "floor": _bfloor(md, r.get("floor")), "model_floor_seq": r.get("floor"),
                              "bounds": r.get("bounds"), "area_sqft": r.get("area_sqft"),
                              "dims_ft": [r.get("width_ft"), r.get("depth_ft"), r.get("height_ft")],
                              "openings": r.get("openings"), "model_id": mid, "scan": md.get("name"),
                              "cite": _cite(mid, r["id"], conf=0.7)})
            for t in md.get("mattertags") or []:
                tags.append({"id": t["id"], "label": t.get("label"), "description": t.get("description"),
                             "floor": _bfloor(md, t.get("floor")), "position": t.get("position"), "model_id": mid,
                             "cite": _cite(mid, t["id"], conf=0.85)})
            for p in md.get("floorplans") or []:
                plans.append({"model_id": mid, "floor": _bfloor(md, p.get("floor")), "kind": p.get("kind"),
                              "image_path": str(CACHE / building_id / p["file"]),
                              "image_url": f"{STATIC_PREFIX}/{building_id}/{p['file']}",
                              "cite": _cite(mid, conf=0.9)})
        return {
            "building_id": building_id,
            "model_id": prim["model_id"],
            "model_ids": [m["model_id"] for m in models],
            "name": meta.get("name") or prim.get("name"),
            "address": meta.get("address") or prim.get("address"),
            "floors": floors,
            "rooms": rooms,
            "mattertags": tags,
            "sweep_count": sum(m.get("sweep_count", 0) for m in models),
            "scans": scans,
            "floorplans": plans,
            "notes": ("Room labels come from Matterport auto room-tagging (may be imperfect). Positions/bounds are "
                      "Matterport model-space metres (x,y plan). 'floor' is best-effort building floor; suite scans "
                      "infer floor from suite number."),
            "cite": _cite(prim["model_id"], conf=0.9),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "building_id": building_id}


def _matches(p: dict, room_filter: str) -> bool:
    q = room_filter.lower().strip()
    words = set([q])
    for k, syn in SYNONYMS.items():
        if k in q or q in k:
            words.update(syn)
    hay = " ".join([str(p.get("room") or ""), " ".join(p.get("room_tags") or []), str(p.get("model_name") or "")]).lower()
    return any(w in hay for w in words)


def matterport_panoramas(building_id: str, room_filter: str | None = None, limit: int = 6) -> dict:
    """Cached equirectangular panoramas: {panos: [{sweep_id, floor, room, image_path, image_url, position, cite}], cite}."""
    try:
        meta, panos, err = _load(building_id, _live())
        if err:
            return {"error": err, "building_id": building_id}
        models = {m["model_id"]: m for m in meta.get("models") or []}
        items = panos.get("panos") or []
        if room_filter:
            items = [p for p in items if _matches(p, room_filter)]
        out = []
        for p in items[: max(0, int(limit))]:
            md = models.get(p["model_id"], {})
            path = CACHE / building_id / p["file"]
            if not path.exists():
                continue
            out.append({
                "sweep_id": p["sweep_id"],
                "floor": _bfloor(md, p.get("floor")) if md else p.get("floor"),
                "room": p.get("room"),
                "room_tags": p.get("room_tags"),
                "scan": p.get("model_name"),
                "model_id": p["model_id"],
                "image_path": str(path),
                "image_url": f"{STATIC_PREFIX}/{building_id}/{p['file']}",
                "projection": p.get("projection"),
                "position": p.get("position"),
                "cite": _cite(p["model_id"], p["sweep_id"], p.get("sweep_label"), conf=0.9),
            })
        prim = _primary(list(models.values())) if models else {"model_id": None}
        res = {"building_id": building_id, "panos": out, "cite": _cite(prim["model_id"], conf=0.9)}
        if room_filter and not out:
            res["note"] = f"no cached panorama matched room_filter={room_filter!r}; available rooms: " + \
                ", ".join(sorted({str(p.get('room')) for p in panos.get('panos') or []}))
        return res
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "building_id": building_id}


__all__ = ["matterport_model", "matterport_panoramas"]
