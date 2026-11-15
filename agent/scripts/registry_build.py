"""Build agent/cache/buildings.json for every CoStar commercial property that has a Matterport scan.

Usage (from firstin/):  agent/.venv/bin/python -m agent.scripts.registry_build [--dry-run]

Output = [featured entries, kept exactly as-is] + [one `costar-<PropertyId>` entry per remaining property],
the rest sorted by city then address. Only small CoStar summary fields are copied (no tenant detail);
the full CoStar record is still read lazily by agent/tools/costar.py from the git-ignored kit.

lat/lng: CoStar primaryAddress lat/lng; else Matterport geolocation (agent/data/matterport_index.json); else skip.
`matterport_geolocation` is also set when a scan's geolocation is within 400 m, because agent/tools/vexcel.py
prefers it (it lands inside the true footprint more often than parcel/geocode points).
Model ids are ordered by sweep count (desc) so tools that cap the number of models fetch the richest scans first.

Also writes agent/cache/buildings_index.json (slim: id, name, address, city, lat, lng, type, flags) when
buildings.json exceeds 2 MB.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict

from agent import config
from agent.tools import costar

REG = config.CACHE_DIR / "buildings.json"
SLIM = config.CACHE_DIR / "buildings_index.json"
MP_INDEX = config.AGENT_DIR / "data" / "matterport_index.json"
CITY = {"houston": "Houston", "los angeles": "Los Angeles"}
SLIM_KEYS = ("building_id", "name", "address", "city", "lat", "lng", "property_type", "stories", "featured", "cached")


def _dist_m(a, b, c, d) -> float:
    k = math.pi / 180
    x = (d - b) * k * math.cos((a + c) / 2 * k)
    return math.hypot(x, (c - a) * k) * 6371000


def _title(s) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() if w[:1].isalpha() else w.lower() for w in str(s or "").split())


def _name(bn, street, address) -> str:
    if bn and street and re.match(r"^(building|bldg|suite|unit|phase)\b", bn, re.I):
        return f"{street} ({bn})"  # "Building 3" alone is useless in a picker
    return bn or street or address


def _address(r: dict) -> tuple[str, str | None]:
    a = r.get("primaryAddress") or {}
    street = " ".join(str(x) for x in (a.get("streetNumber"), a.get("streetDirection"),
                                        _title(a.get("streetName")) or None, a.get("streetType")) if x)
    zip5 = str(a.get("postcode") or "")[:5]
    return f"{street}, {a.get('city')}, {a.get('state')} {zip5}".strip().rstrip(","), street or None


def _year_built(r: dict):
    ys = [e["year"] for e in r.get("constructionEvents") or [] if e.get("eventType") == 2 and e.get("year")]
    return min(ys) if ys else None


def _num(v):
    try:
        f = float(v)
        return int(f) if f > 0 else None
    except (TypeError, ValueError):
        return None


def build(dry_run: bool = False) -> dict:
    existing = json.loads(REG.read_text()) if REG.exists() else []
    featured = [b for b in existing if not str(b.get("building_id", "")).startswith("costar-")]
    for b in featured:
        b.setdefault("featured", True)
        b.setdefault("cached", True)
    prev = {b["building_id"]: b for b in existing}
    taken = {str(b.get("costar_id")) for b in featured if b.get("costar_id")}
    taken_ids = {b["building_id"] for b in featured}

    models: dict[str, list[str]] = defaultdict(list)
    city_of: dict[str, str] = {}
    with open(costar.kit_dir() / "commercial-properties.csv", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid, mid = (row.get("PropertyId") or "").strip(), (row.get("MatterportModelId") or "").strip()
            if pid and mid and mid not in models[pid]:
                models[pid].append(mid)
                city_of.setdefault(pid, CITY.get((row.get("City") or "").strip().lower(), (row.get("City") or "").title()))

    mp = {m["id"]: m for m in json.loads(MP_INDEX.read_text())["models"]} if MP_INDEX.exists() else {}
    pidx = costar._property_index()
    stats = defaultdict(int)
    rest = []
    for pid, mids in models.items():
        if pid in taken:
            stats["already_featured"] += 1
            continue
        off = pidx.get(int(pid))
        if off is None:
            stats["not_in_kit"] += 1
            continue
        r = costar._read_at(costar._data("commercial-property"), [off])[0]
        a = r.get("primaryAddress") or {}
        mids = sorted(mids, key=lambda m: -(mp.get(m, {}).get("sweeps") or 0))
        geo = next(({"lat": mp[m]["lat"], "lng": mp[m]["lng"]} for m in mids
                    if m in mp and mp[m].get("lat") is not None and mp[m].get("lng") is not None), None)
        lat, lng, src = a.get("latitude"), a.get("longitude"), "costar"
        if lat is None or lng is None:
            if not geo:
                stats["no_coords"] += 1
                continue
            lat, lng, src = geo["lat"], geo["lng"], "matterport"
        if geo and _dist_m(lat, lng, geo["lat"], geo["lng"]) > 400:
            geo = None  # scan geolocation disagrees with CoStar; don't let vexcel.py prefer it
            stats["mp_geo_far"] += 1
        address, street = _address(r)
        bid = f"costar-{pid}"
        p = prev.get(bid, {})
        e = {
            "building_id": bid,
            "name": _name(r.get("buildingName"), street, address),
            "address": address,
            "city": city_of.get(pid) or CITY.get(str(a.get("city") or "").lower(), a.get("city")),
            "lat": round(float(lat), 7), "lng": round(float(lng), 7), "geocode_source": src,
            "matterport_geolocation": geo,
            "costar_id": pid,
            "matterport_model_ids": mids,
            "property_type": costar.PROPERTY_TYPE.get(r.get("propertyType")),
            "stories": r.get("numStoriesAboveGrade"),
            "year_built": _year_built(r),
            "rba_sqft": _num(r.get("rentableBuildingAreaSquareFeet")) or _num(r.get("grossBuildingAreaSquareFeet")),
            "has": {"costar": True, "vexcel": True, "matterport": True},
            "cached": bool(p.get("cached", False)),
            "featured": bool(p.get("featured", False)),
        }
        for k in ("vexcel_lat", "vexcel_lng", "demo_note"):  # keep manual overrides across rebuilds
            if k in p:
                e[k] = p[k]
        rest.append(e)
        stats["entries"] += 1

    # curated pre-cached costar-* buildings are featured too: put them right after the original 5
    cur = [e for e in rest if e["featured"] and e["building_id"] not in taken_ids]
    rest = [e for e in rest if not (e["featured"] and e["building_id"] not in taken_ids)]
    key = lambda e: (e["city"] or "", re.sub(r"^\d+\s*", "", e["address"]).lower(), e["address"])
    out = featured + sorted(cur, key=key) + sorted(rest, key=key)
    stats.update(total=len(out), featured=len(featured) + len(cur))
    if not dry_run:
        text = "[\n" + ",\n".join(json.dumps(b, ensure_ascii=False) for b in out) + "\n]\n"
        REG.write_text(text)
        stats["bytes"] = len(text.encode())
        if stats["bytes"] > 2_000_000:
            slim = [{k: b.get(k) for k in SLIM_KEYS} for b in out]
            SLIM.write_text(json.dumps(slim, separators=(",", ":")))
            stats["slim_bytes"] = SLIM.stat().st_size
    return dict(stats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    print(json.dumps(build(ap.parse_args().dry_run), indent=1))


if __name__ == "__main__":
    main()
