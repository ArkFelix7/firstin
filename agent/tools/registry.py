"""Demo building registry (agent/cache/buildings.json, written by the data teammate).

Parsed once and cached keyed on the file's mtime (the registry is ~3k buildings / 1.8 MB).
"""
from __future__ import annotations

import json
import re

from .. import config

_CACHE: dict = {"key": None, "list": [], "by_id": {}}

LIGHT_FIELDS = ("building_id", "name", "address", "city", "lat", "lng", "property_type", "stories", "year_built",
                "cached", "featured", "costar_id")


def _load() -> dict:
    p = config.REGISTRY_PATH
    try:
        st = p.stat()
    except OSError:
        return {"key": None, "list": [], "by_id": {}}
    key = (str(p), st.st_mtime_ns, st.st_size)
    if _CACHE["key"] == key:
        return _CACHE
    try:
        data = json.loads(p.read_text())
    except Exception:  # noqa: BLE001 - mid-write / bad file: keep the previous parse
        return _CACHE
    if isinstance(data, dict):
        data = data.get("buildings", [])
    data = data if isinstance(data, list) else []
    _CACHE.update(key=key, list=data, by_id={b.get("building_id"): b for b in data if isinstance(b, dict)})
    return _CACHE


def list_buildings() -> list[dict]:
    return _load()["list"]


def get_building(building_id: str) -> dict | None:
    return _load()["by_id"].get(building_id)


def light(b: dict) -> dict:
    return {k: b.get(k) for k in LIGHT_FIELDS}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(s or "").lower()).strip()


def search(q: str | None = None, city: str | None = None, type_: str | None = None, featured: bool | None = None,
           limit: int | None = None, offset: int = 0) -> tuple[int, list[dict]]:
    """Filter + rank registry buildings. Rank: address prefix > name prefix > id match > substring.
    Featured first within a rank. Returns (total, page)."""
    rows = list_buildings()
    qn = _norm(q)
    cn = _norm(city)
    tn = _norm(type_)
    out = []
    for b in rows:
        if featured is not None and bool(b.get("featured")) != featured:
            continue
        if cn and cn not in _norm(b.get("city")):
            continue
        if tn and tn not in _norm(b.get("property_type")):
            continue
        rank = 0
        if qn:
            addr, name = _norm(b.get("address")), _norm(b.get("name"))
            ids = (str(b.get("building_id") or "").lower(), str(b.get("costar_id") or "").lower())
            if addr.startswith(qn):
                rank = 0
            elif name.startswith(qn):
                rank = 1
            elif q.strip().lower() in ids:
                rank = 2
            elif qn in addr or qn in name:
                rank = 3
            else:
                continue
        out.append((rank, 0 if b.get("featured") else 1, 0 if b.get("cached") else 1, b))
    out.sort(key=lambda x: x[:3])
    total = len(out)
    page = [x[3] for x in out[offset: (offset + limit) if limit else None]]
    return total, page


def resolve_building(query: str) -> dict:
    """Resolve a building_id or free-text address to a registry entry."""
    b = get_building(query)
    if b:
        return {**b, "cite": {"src": "registry", "id": b["building_id"], "conf": 1.0}}
    q = re.sub(r"[^a-z0-9 ]", "", query.lower())
    for b in list_buildings():
        a = re.sub(r"[^a-z0-9 ]", "", str(b.get("address", "")).lower())
        if q and a and (q in a or a in q):
            return {**b, "cite": {"src": "registry", "id": b["building_id"], "conf": 0.9}}
    return {"error": f"no registry building matches '{query}'"}
