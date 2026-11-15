"""Deterministic evidence -> NFPA 1660-style pre-plan (README §7) + voice brief + in-cab summary.

Used by the offline pipeline, and as the safety net in LLM mode when the planner's
/plan/*.json is missing or malformed. Only ever copies facts that exist in evidence;
anything missing becomes VERIFY ON SITE.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import config
from .tools.validator import VERIFY, validate_plan

V = {"value": VERIFY, "cite": None}

STAIR_RX = re.compile(r"\bstair", re.I)
ELEV_RX = re.compile(r"\belevator|\blift\b", re.I)
ELEC_RX = re.compile(r"\belectric|\belec\b|\bswitchgear|\bpanel room|\bmeter room", re.I)
MECH_RX = re.compile(r"\bmechanical|\bboiler|\bmech\b|\butility|\bhvac|\bpump room|\bsprinkler room|\briser room", re.I)
FP_KEYS = {
    "fdc": re.compile(r"\bfdc\b|fire department connection|siamese", re.I),
    "alarm_panel": re.compile(r"\bfacp\b|alarm (control )?panel|fire alarm|annunciator", re.I),
    "sprinkler_riser": re.compile(r"riser|sprinkler (valve|control)", re.I),
    "standpipe": re.compile(r"standpipe|hose valve|hose connection", re.I),
    "knox_box": re.compile(r"knox", re.I),
}


_SKIP_DASH_KEYS = {"cite", "url", "image_url", "image_path", "id", "media"}


def no_dash(x: Any, _key: str | None = None) -> Any:
    """Remove em/en dashes from user-facing text: ' — ' -> ', ', bare '—' -> '-'. Recurses into dicts/lists."""
    if isinstance(x, str):
        return re.sub(r"\s*[—–]\s*", lambda m: ", " if m.group(0).strip() != m.group(0) else "-", x).replace(", ,", ",")
    if isinstance(x, dict):
        return {k: (v if k in _SKIP_DASH_KEYS else no_dash(v, k)) for k, v in x.items()}
    if isinstance(x, list):
        return [no_dash(v) for v in x]
    return x


def _get(d: Any, *path, default=None):
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        else:
            return default
    return default if d is None else d


def _ok(d: Any) -> bool:
    return isinstance(d, dict) and not d.get("error")


def _field(value, cite) -> dict:
    if value in (None, "", []):
        return dict(V)
    return {"value": value, "cite": cite}


def _costar_cite(prop: dict, field: str, conf: float | None = None) -> dict:
    c = dict(prop.get("cite") or {})
    return {"src": "costar", "id": c.get("id") or prop.get("costar_id"), "conf": conf or c.get("conf", 0.95),
            "bbox": None, "url": None, "from": [f"costar.{field}"]}


def _vx_cite(tile: dict, f: dict | None, conf=None) -> dict:
    f = f or {}
    return {"src": "vexcel", "id": tile.get("tile_id") or _get(tile, "cite", "id"),
            "conf": f.get("conf", conf if conf is not None else 0.6), "bbox": f.get("bbox"),
            "url": tile.get("image_url"), "from": None}


def _mp_cite(model_id, sweep_or_room, conf=0.8, bbox=None, url=None) -> dict:
    return {"src": "matterport", "id": sweep_or_room or model_id, "conf": conf, "bbox": bbox, "url": url,
            "from": None, "model_id": model_id}


def _rc(r: dict, model_id, conf=0.8) -> dict:
    """Citation for a Matterport room/tag: the tool's own cite (has deep link) else a built one."""
    c = r.get("cite") if isinstance(r, dict) else None
    if "bounds" in r or "tags" in r:  # auto-tagged room labels are often wrong in commercial space
        conf = min(conf, 0.6)
    if isinstance(c, dict) and c.get("id"):
        return {**c, "conf": min(c.get("conf") or conf, conf), "model_id": r.get("model_id") or model_id}
    return _mp_cite(model_id, r.get("id") or r.get("sid"), conf)


def _rlabel(r: dict) -> str:
    return " ".join([str(r.get("label") or "")] + [str(t) for t in (r.get("tags") or [])])


def era_construction(year: int | None) -> str | None:
    if not year:
        return None
    if year < 1940:
        return "Likely ordinary (masonry) construction (era-inferred)"
    if year < 1980:
        return "Likely non-combustible steel/concrete frame (era-inferred)"
    return "Possible lightweight/engineered components (era-inferred)"


def _floor_label(f) -> str:
    if f in (None, ""):
        return ""
    s = str(f)
    return f"Floor {s}" if s.isdigit() else s


def condense(text, max_words: int = 12) -> str | None:
    """First clause of a VLM sentence, no parentheticals, <= max_words words."""
    if not text:
        return None
    t = re.sub(r"\s*\([^)]*\)", "", str(text)).strip()
    t = re.split(r"(?<=[a-z0-9])\. |; | — | - |, where |, which |, so ", t)[0].strip().rstrip(".")
    w = t.split()
    out = " ".join(w[:max_words]).rstrip(",;:")
    return out + ("…" if len(w) > max_words else "")


# ---------------------------------------------------------------- sections
def _roof_target(vx: dict) -> tuple[dict, dict]:
    roof = vx.get("roof") if _ok(vx.get("roof")) else {}
    return roof, (roof.get("target") or {}) if roof else {}


def _roof_cite(roof: dict, field: str, conf: float) -> dict:
    c = dict(roof.get("cite") or {})
    return {"src": "vexcel", "id": c.get("id"), "conf": conf, "bbox": None, "url": c.get("url"),
            "from": [f"vexcel.{field}"]}


def roof_desc(t: dict) -> str | None:
    if not t or not (t.get("roof_shape") or t.get("roof_material")):
        return None
    s = f"{(t.get('roof_shape') or '').title()} {t.get('roof_material') or ''} roof".strip()
    if t.get("roof_condition_1to5") is not None:
        s += f", condition {t.get('roof_condition_label') or ''} ({t['roof_condition_1to5']:.0f}/5)"
    obj = t.get("roof_objects") or {}
    parts = [f"{obj[k]} {k.replace('-', ' ')}{'s' if obj[k] != 1 else ''}" for k in ("ac-unit", "roof-vent", "skylight", "chimney")
             if isinstance(obj.get(k), (int, float)) and obj.get(k)]
    if obj.get("solar"):
        parts.append("SOLAR PV")
    if parts:
        s += "; " + ", ".join(parts)
    defects = [k.replace("-", " ") for k, v in (t.get("roof_defects_pct") or {}).items()
               if isinstance(v, (int, float)) and v >= 1 and k in ("water-pooling", "rust", "structural-damage", "tarp", "missing-material")]
    if defects:
        s += "; defects: " + ", ".join(defects)
    return s


def _pf(prop: dict, key: str, conf: float = 0.9) -> dict:
    """CoStar field -> plan field, using costar.py's per-field cite (real conf + source `field` path)."""
    f = (prop.get("fields") or {}).get(key) if isinstance(prop.get("fields"), dict) else None
    if isinstance(f, dict) and f.get("value") not in (None, "", []) and isinstance(f.get("cite"), dict):
        return {"value": f["value"], "cite": {**f["cite"], "from": f["cite"].get("from") or [f"costar.{key}"]}}
    v = prop.get(key)
    if v in (None, "", []) or isinstance(v, (dict, list)):
        return dict(V)
    return {"value": v, "cite": _costar_cite(prop, key, conf)}


def _elevators_text(e) -> str | None:
    if isinstance(e, dict):
        parts = [f"{v} {k}" for k, v in e.items() if isinstance(v, (int, float)) and v]
        return ", ".join(parts) if parts else "none recorded"
    return str(e) if e not in (None, "") else None


def height_cross_check(prop: dict, t: dict) -> dict | None:
    """CoStar height (or stories x 12 ft) vs Vexcel DSM height. Returns a note dict or None."""
    vx_m = t.get("height_est_m")
    if not vx_m:
        return None
    if prop.get("height_ft"):
        cs_m, basis = float(prop["height_ft"]) * 0.3048, f"CoStar height {prop['height_ft']} ft"
    elif prop.get("stories"):
        cs_m, basis = float(prop["stories"]) * 12 * 0.3048, f"CoStar {prop['stories']} fl x 12 ft"
    else:
        return None
    ratio = min(cs_m, vx_m) / max(cs_m, vx_m)
    agree = ratio >= 0.85
    return {"agree": agree, "ratio": round(ratio, 2), "costar_m": round(cs_m, 1), "vexcel_m": round(float(vx_m), 1),
            "note": (f"cross-check: {basis} = {cs_m:.1f} m vs Vexcel DSM {float(vx_m):.1f} m: "
                     + (f"agree {ratio * 100:.0f}%" if agree else f"DISAGREE ({ratio * 100:.0f}%); trusting CoStar, verify on site"))}


def building_section(b: dict, costar: dict, aerial: dict, vx: dict | None = None) -> dict:
    prop = costar.get("property") if _ok(costar.get("property")) else {}
    roof, t = _roof_target(vx or {})
    out = {"address": b.get("address"), "building_id": b.get("building_id"), "name": b.get("name"), "city": b.get("city"),
           "lat": b.get("lat"), "lng": b.get("lng"),
           "costar_id": prop.get("costar_id") or b.get("costar_id")}
    out["stories"] = _pf(prop, "stories", 0.95)
    if out["stories"]["value"] == VERIFY and t.get("stories_est"):
        out["stories"] = {"value": t["stories_est"], "approx": True,
                          "basis": f"~{t.get('height_est_m')} m roof height (Vexcel DSM) / ~3.7 m per story",
                          "cite": {"src": "inference", "id": "vexcel-dsm-stories", "conf": 0.5, "bbox": None,
                                   "url": (roof.get("cite") or {}).get("url"), "from": ["vexcel.height_est_m"]}}
    out["height_ft"] = _pf(prop, "height_ft", 0.85)
    out["height_m"] = _field(t.get("height_est_m"), _roof_cite(roof, "height_est_m", 0.75)) if t.get("height_est_m") else dict(V)
    xc = height_cross_check(prop, t) if prop else None
    if xc:
        for k in ("stories", "height_m", "height_ft"):
            f = out.get(k)
            if isinstance(f, dict) and f.get("cite"):
                f["agreement"] = xc["note"]
                if xc["agree"] and f["cite"].get("conf") is not None:
                    f["cite"] = {**f["cite"], "conf": round(min(0.99, float(f["cite"]["conf"]) + 0.03), 2)}
        out["cross_check"] = xc
    out["year_built"] = _pf(prop, "year_built", 0.95)
    out["year_renovated"] = _pf(prop, "year_renovated", 0.85)
    area = _pf(prop, "rba_sqft", 0.93)
    out["sq_ft"] = area if area["value"] != VERIFY else _pf(prop, "gba_sqft", 0.93)
    out["footprint_m2"] = (_field(round(t["footprint_area_m2"]), _roof_cite(roof, "footprint_area_m2", 0.85))
                           if t.get("footprint_area_m2") else dict(V))
    out["building_class"] = _pf(prop, "building_class", 0.9)
    if prop.get("property_type"):
        out["property_type"] = _pf(prop, "property_type", 0.95)
    elif t.get("building_type"):
        out["property_type"] = _field(str(t["building_type"]).replace("_", "/"),
                                      _roof_cite(roof, "building_type", float(t.get("building_type_score") or 0.7)))
    else:
        out["property_type"] = dict(V)
    cons = _pf(prop, "construction", 0.85)
    if cons["value"] == VERIFY:
        cons = _pf(prop, "construction_material", 0.85)
    tilt = any("tilt" in str(f) for f in (prop.get("description_flags") or [])) or "tilt" in str(cons.get("value", "")).lower()
    if tilt and cons["value"] != VERIFY:
        mat = _pf(prop, "construction_material", 0.85)
        base = mat if mat["value"] != VERIFY else cons
        frm = list((base["cite"] or {}).get("from") or []) + ["costar.description_flags"]
        cons = {"value": "Concrete tilt-up" + (f" (CoStar material: {mat['value']})" if mat["value"] != VERIFY else ""),
                "cite": {**base["cite"], "from": frm}}
    if cons["value"] != VERIFY:
        out["construction"] = cons
    else:
        era = era_construction(prop.get("year_built"))
        frm = ["costar.year_built"]
        if t.get("roof_shape") or _get(aerial, "findings", "roof_type", "value"):
            frm.append("vexcel.roof")
        out["construction"] = _field(era, {"src": "inference", "id": "era-construction", "conf": 0.4,
                                           "bbox": None, "url": None, "from": frm})
    # never turn "unknown" into "No"
    sp = prop.get("sprinklers")
    out["sprinklers"] = _pf(prop, "sprinklers", 0.85) if sp not in (None, "", "Unknown", "unknown") else dict(V)
    el = _elevators_text(prop.get("elevators"))
    ef = _pf(prop, "elevators", 0.85)
    out["elevators_costar"] = ({"value": el, "cite": ef["cite"]} if el and ef.get("cite") else
                               ({"value": el, "cite": _costar_cite(prop, "elevators", 0.85)} if el else dict(V)))
    out["loading_docks"] = _pf(prop, "loading_docks", 0.85)
    out["power"] = _pf(prop, "power", 0.85)
    out["owner"] = _pf(prop, "owner", 0.8)
    fl = prop.get("floors")
    out["floors"] = ({"value": len([f for f in fl if isinstance(f, dict) and f.get("floor")]) or len(fl),
                      "cite": _costar_cite(prop, "floors", 0.75)} if isinstance(fl, list) and fl else dict(V))
    vroof = _get(aerial, "findings", "roof_type") or {}
    tile = aerial.get("_tile") or {}
    if roof_desc(t):
        out["roof"] = {"value": roof_desc(t), "cite": _roof_cite(roof, "roof", float(t.get("roof_material_score") or 0.85))}
    elif vroof.get("value"):
        out["roof"] = _field(vroof.get("value"), _vx_cite(tile, vroof))
    else:
        out["roof"] = dict(V)
    return out


TENANT_KEYS = ("name", "use", "industry", "floor", "suite", "naics", "sic", "sqft", "employees", "move_in",
               "future_move_in", "cite")


def occupancy_section(costar: dict) -> dict:
    tenants_raw = costar.get("tenants") if _ok(costar.get("tenants")) else {}
    tenants = []
    for t in (tenants_raw or {}).get("tenants", []):
        x = {k: t.get(k) for k in TENANT_KEYS}
        x["use"] = x.get("use") or x.get("industry") or VERIFY
        tenants.append(x)
    prop = costar.get("property") if _ok(costar.get("property")) else {}
    ol = (tenants_raw or {}).get("occupant_load_estimate")
    if isinstance(ol, dict) and ol.get("cite") and ol.get("value") not in (None, ""):
        load = ol
    else:
        load = dict(V)
        rba = prop.get("rba_sqft") or prop.get("gba_sqft")
        if rba:
            ptype = str(prop.get("property_type") or "").lower()
            factor = {"office": 150, "retail": 60, "industrial": 500, "flex": 300, "warehouse": 500}.get(
                next((k for k in ("office", "retail", "industrial", "flex", "warehouse") if k in ptype), ""), 200)
            n = int(float(rba) / factor)
            load = {"value": f"~{n:,} max (IBC ~{factor} sf/occupant, {ptype or 'mixed'} use)",
                    "cite": {"src": "inference", "id": "occupant-load", "conf": 0.45, "bbox": None, "url": None,
                             "from": ["costar.rba_sqft", "costar.property_type"]}}
    return {"tenants": tenants or dict(V), "occupant_load_estimate": load}


def access_section(aerial: dict, vx: dict | None = None) -> tuple[dict, list]:
    tile = aerial.get("_tile") or {}
    f = aerial.get("findings") or {}
    out = {}
    for key in ("roof_access", "staging", "hydrants", "access_roads"):
        node = f.get(key) or {}
        out[key] = _field(node.get("value"), _vx_cite(tile, node)) if node.get("value") else dict(V)
    exposures = []
    roof, _t = _roof_target(vx or {})
    for i, e in enumerate(roof.get("exposures") or []):
        gap = e.get("gap_m")
        desc = f"{str(e.get('building_type') or 'structure').replace('_', '/')} building, {e.get('roof_material') or '?'} roof"
        if e.get("footprint_area_m2"):
            desc += f", ~{e['footprint_area_m2'] * 10.764:,.0f} sf footprint"
        if gap is not None:
            desc += f", ~{gap * 3.281:.0f} ft away"
        exposures.append({"side": e.get("side") or "?", "desc": desc, "gap_m": gap,
                          "cite": {**_roof_cite(roof, f"exposures[{i}]", 0.85)}})
    for e in f.get("exposures") or []:
        d = str(e.get("desc") or e.get("value") or "") if isinstance(e, dict) else ""
        if d and NO_BUILDING.search(d) and not re.search(r"pallet|debris|storage|yard|combustible|trailer|tank", d, re.I):
            continue
        if d and NON_BUILDING.search(d) and not BUILDING.search(d) and not re.search(r"pallet|debris|storage|yard|combustible|vehicle|trailer|tank", d, re.I):
            continue  # parking lots / streets are not fire-spread exposures
        if isinstance(e, dict) and (e.get("desc") or e.get("value")):
            exposures.append({"side": e.get("side") or "?", "desc": e.get("desc") or e.get("value"),
                              "cite": _vx_cite(tile, e)})
    return out, exposures


def interior_section(mp: dict) -> dict:
    model = mp.get("model") if _ok(mp.get("model")) else {}
    model_id = model.get("model_id") or _get(model, "cite", "id")
    rooms = model.get("rooms") or []
    tags = model.get("mattertags") or []
    analyses = mp.get("pano_analyses") or []

    def tag_text(t):
        return f"{t.get('label', '')} {t.get('description', '')}" if isinstance(t, dict) else str(t)

    # stairwells: vision-verified pano detections first (specific, high conf), then auto-tagged room labels
    stairs: list[dict] = []
    covered = set()  # (model_id, floor) already represented by a pano-verified stair
    for a in analyses:
        fnd = _get(a, "result", "findings", "findings") or _get(a, "result", "findings") or {}
        if not isinstance(fnd, dict):
            continue
        stair_nodes = [v for k, v in fnd.items() if STAIR_RX.search(k) and isinstance(v, dict) and v.get("value")]
        hit_sp = any(FP_KEYS["standpipe"].search(k) or FP_KEYS["standpipe"].search(str(v)) for k, v in fnd.items())
        covered.add((a.get("scan"), str(a.get("floor"))))  # vision looked here: trust it over auto-tags
        if not stair_nodes:
            continue
        node = max(stair_nodes, key=lambda v: v.get("conf") or 0)
        what = condense(re.split(r" with | leading | that | on the | at the | to the ", str(node.get("value") or ""))[0], 6) or "Stair"
        where = ", ".join(x for x in (a.get("scan"), _floor_label(a.get("floor"))) if x)
        stairs.append({"loc": f"{what} ({where})" if where else what, "standpipe": hit_sp,
                       "cite": _mp_cite(a.get("model_id") or model_id, a.get("sweep_id"), node.get("conf", 0.7), node.get("bbox"),
                                        a.get("image_url"))})
        covered.add((a.get("scan"), str(a.get("floor"))))
    seen = set()
    for r in rooms:
        if not STAIR_RX.search(_rlabel(r)):
            continue
        lab = str(r.get("label") or "").strip()
        generic = lab.lower() in ("", "stairs", "stair", "staircase", "stairwell", "stairway")
        key = (lab.lower(), r.get("scan"), str(r.get("floor")))
        if key in seen or (generic and (r.get("scan"), str(r.get("floor"))) in covered):
            continue
        seen.add(key)
        where = ", ".join(x for x in (r.get("scan"), _floor_label(r.get("floor"))) if x)
        name = "Stair (scan room tag)" if generic else lab
        stairs.append({"loc": f"{name} ({where})" if where else name, "standpipe": False,
                       "room": r.get("id"), "cite": _rc(r, model_id, 0.85)})

    elev_rooms = [r for r in rooms if ELEV_RX.search(_rlabel(r))]
    elev_tags = [t for t in tags if isinstance(t, dict) and ELEV_RX.search(tag_text(t))]
    elevators = dict(V)
    if elev_tags and not elev_rooms:
        t0 = elev_tags[0]
        elevators = {"value": f"Elevators present: '{t0.get('label')}'" + (f" ({_floor_label(t0.get('floor'))})" if t0.get("floor") not in (None, "") else ""),
                     "cite": _rc(t0, model_id, 0.85)}
    if elev_rooms:
        floors = {}
        for r in elev_rooms:
            floors.setdefault(str(r.get("floor")), []).append(r)
        n = max(len(v) for v in floors.values())
        elevators = {"value": f"{n} elevator{'s' if n > 1 else ''} (scan room labels)",
                     "cite": _rc(elev_rooms[0], model_id, 0.75)}

    def room_field(rx, conf=0.8):
        for r in rooms:
            if rx.search(_rlabel(r)):
                return {"value": f"{str(r.get('label')).title()} room, {_floor_label(r.get('floor')) or 'floor ?'}",
                        "cite": _rc(r, model_id, conf)}
        for a in analyses:
            fnd = _get(a, "result", "findings", "findings") or _get(a, "result", "findings") or {}
            for k, v in (fnd.items() if isinstance(fnd, dict) else []):
                if rx.search(k) or rx.search(str(v)):
                    v = v if isinstance(v, dict) else {"value": str(v)}
                    return {"value": f"{v.get('value') or k}, {a.get('scan') or a.get('room') or ''} {_floor_label(a.get('floor'))}".strip(" ,"),
                            "cite": _mp_cite(model_id, a.get("sweep_id"), v.get("conf", 0.6), v.get("bbox"), a.get("image_url"))}
        return dict(V)

    fire = {}
    for key, rx in FP_KEYS.items():
        fld = dict(V)
        for t in tags:
            if rx.search(tag_text(t)):
                fld = {"value": f"{t.get('label')}" + (f", {_floor_label(t.get('floor'))}" if t.get("floor") not in (None, "") else ""),
                       "cite": _rc(t, model_id, 0.9)}
                break
        if fld["value"] == VERIFY:
            fld = room_field(rx, 0.65)
        fire[key] = fld

    return {
        "stairwells": stairs or dict(V),
        "elevators": elevators,
        "utilities": {"electrical_room": room_field(ELEC_RX), "mechanical_room": room_field(MECH_RX)},
        "fire_protection": fire,
    }


def _annotated(tile: dict) -> str | None:
    from pathlib import Path

    p = tile.get("image_path")
    if p and (Path(p).parent / "ortho_annotated.jpg").exists():
        return config.static_url(Path(p).parent / "ortho_annotated.jpg")
    return None


# ---------------------------------------------------------------- top level
def build_plan(plan_id: str, building: dict, evidence: dict, mode: str = "offline") -> dict:
    costar = evidence.get("costar") or {}
    vx = evidence.get("vexcel") or {}
    mp = evidence.get("matterport") or {}
    hz = evidence.get("hazards") or {}
    aerial = dict(vx.get("analysis") or {})
    aerial["_tile"] = vx.get("tile") if _ok(vx.get("tile")) else {}
    if aerial.get("error"):
        aerial["findings"] = {}
    access, exposures = access_section(aerial, vx)
    plan = {
        "plan_id": plan_id,
        "building_id": building.get("building_id"),
        "mode": mode,
        "building": building_section(building, costar, aerial, vx),
        "occupancy": occupancy_section(costar),
        "access": access,
        "interior": interior_section(mp),
        "hazards": [{k: h.get(k) for k in ("type", "location", "reason", "tactics", "conf", "cite", "tenant")}
                    for h in hz.get("hazards", [])],
        "exposures": exposures or dict(V),
        "media": {
            "aerial_url": _annotated(aerial["_tile"]) or aerial["_tile"].get("image_url"),
            "aerial_raw_url": aerial["_tile"].get("image_url"),
            "footprint": (vx.get("footprint") or {}).get("on_images") if _ok(vx.get("footprint")) else None,
            "obliques": [{"url": (o.get("tile") or {}).get("image_url"), "shows_facade": (o.get("tile") or {}).get("shows_facade")}
                         for o in vx.get("obliques") or [] if isinstance(o, dict)],
            "aerial_path": aerial["_tile"].get("image_path"),
            "pano_urls": [p.get("image_url") for p in (_get(mp, "panoramas", "panos") or []) if p.get("image_url")][:4],
            "matterport_model_id": _get(mp, "model", "model_id"),
            "matterport_sweeps": _get(mp, "model", "sweep_count"),
            "matterport_floors": len(_get(mp, "model", "floors", default=[]) or []),
        },
        "sources": {
            "costar": "ok" if _ok(costar.get("property")) else _get(costar, "property", "error", default="missing"),
            "vexcel": "ok" if _ok(vx.get("tile")) else _get(vx, "tile", "error", default="missing"),
            "vexcel_roof": "ok" if _ok(vx.get("roof")) else _get(vx, "roof", "error", default="missing"),
            "matterport": "ok" if _ok(mp.get("model")) else _get(mp, "model", "error", default="missing"),
            "vision_aerial": "ok" if aerial.get("findings") else (vx.get("analysis") or {}).get("error", "missing"),
        },
        "status": "DRAFT",
        "approved_by": None,
        "created_at": time.time(),
    }
    plan["voice_brief"] = voice_brief(plan)
    return plan


# ---------------------------------------------------------------- brief + summary
_NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
        11: "eleven", 12: "twelve"}


def val(node) -> Any:
    if isinstance(node, dict) and "value" in node:
        return None if node["value"] == VERIFY else node["value"]
    return node


def stairs_text(plan: dict) -> str | None:
    st = _get(plan, "interior", "stairwells")
    if not isinstance(st, list) or not st:
        return None
    parts = [s.get("loc", "?") + (" (standpipe)" if s.get("standpipe") else "") for s in st if not s.get("verify_on_site")]
    return ", ".join(parts[:4]) or None


def top_hazards_detail(plan: dict, n: int = 3) -> list[dict]:
    hz = [h for h in plan.get("hazards") or [] if isinstance(h, dict) and h.get("type")]
    hz.sort(key=lambda h: -(h.get("conf") or 0))
    out, seen = [], set()
    for h in hz:
        if h["type"] in seen:
            continue
        seen.add(h["type"])
        loc = h.get("location") if h.get("location") not in (None, "", VERIFY) else None
        out.append({"type": no_dash(h["type"]), "location": no_dash(loc) if loc else None, "conf": h.get("conf")})
    return out[:n]


def top_hazards(plan: dict, n: int = 3) -> list[str]:
    """Display strings 'Type (Location)'; see top_hazards_detail for structured items."""
    out = []
    for d in top_hazards_detail(plan, n):
        t = re.sub(r"\s*\([^)]*\)", "", d["type"]).strip()  # full text stays in top_hazards_detail
        out.append(t + (f" ({d['location']})" if d["location"] and d["location"] != "Building-wide" else ""))
    return out


_SIDES = {"N": "north", "S": "south", "E": "east", "W": "west", "NE": "northeast", "NW": "northwest",
          "SE": "southeast", "SW": "southwest"}


def _spoken(s: str) -> str:
    s = re.sub(r"\s*\([^)]*\)", "", str(s)).split(";")[0].strip()
    return s


NON_BUILDING = re.compile(r"parking|street|road|drive ?aisle|sidewalk|landscap|open lot|lawn|plaza|rail", re.I)
BUILDING = re.compile(r"building|structure|bldg|house|warehouse|apartment|condo|store|shop|garage|shed|commercial|wing|lean-to|canopy", re.I)


NO_BUILDING = re.compile(r"\bno (adjacent |nearby |other )?(buildings?|structures?)", re.I)


def is_building_exposure(e: dict) -> bool:
    d = f"{e.get('desc') or ''}"
    if NO_BUILDING.search(d):
        return False
    return bool(e.get("gap_m") is not None or BUILDING.search(d)) and not (NON_BUILDING.search(d) and not BUILDING.search(d))


_LEAD_FILLER = {"the", "best", "primary", "likely", "good", "recommended", "roof", "ladder", "aerial", "ladder/aerial",
                "aerial/ladder", "or", "and", "access", "placement", "point", "is", "are", "appears", "would", "be", "to",
                "only", "practical", "realistically", "possible", "probably", "via", "from", "on", "at", "along",
                "placements", "for", "ladders", "apparatus", "an", "a", "can", "should", "approach", "it", "best:",
                "aerials", "placed", "positioned", "staged", "set", "up", "raised", "trucks", "truck", "devices"}
_TAIL_STOP = {"in", "and", "or", "the", "of", "to", "at", "on", "with", "for", "a", "an", "from", "via", "along", "by"}


def short_clause(text: str | None, max_words: int = 8) -> str | None:
    """Condense a long VLM sentence to one short clause, on WORD boundaries only.
    'Aerial or ladder access is only practical from the street frontage on the north/northwest, where ...'
      -> 'street frontage on the north/northwest'"""
    if not text:
        return None
    t = re.sub(r"\s*\([^)]*\)", "", str(text)).strip()
    first = re.split(r"[.;:]\s|,\s|\s(?:where|which|because|but|so|while)\s", t, maxsplit=1)[0]
    words = first.split()
    while words and words[0].lower().strip(",.") in _LEAD_FILLER:
        words.pop(0)
    if not words:  # sentence was all filler: fall back to the raw first clause
        words = first.split()
    words = words[:max_words]
    while words and words[-1].lower().strip(",.") in _TAIL_STOP:
        words.pop()
    out = " ".join(words).strip(" ,.;:")
    return out or None


def roof_access_short(plan: dict) -> str | None:
    """One short clause: '<access side/area>; solar PV on roof'. Uses the field's own `short` form if present."""
    node = _get(plan, "access", "roof_access")
    bits = []
    if isinstance(node, dict) and node.get("short") and node.get("value") != VERIFY:
        bits.append(str(node["short"]).strip())
    elif val(node):
        bits.append(short_clause(val(node), 8))
    if any("solar" in str(h.get("type", "")).lower() for h in plan.get("hazards") or [] if isinstance(h, dict)):
        bits.append("solar PV on roof")
    return "; ".join(b for b in bits if b) or None


def _hz_phrase(h: dict) -> str:
    t = _spoken(h.get("type", "")).lower()
    t = re.sub(r"^possible ", "", t)
    w = (condense(t.split(":")[0].replace(" / ", " or ").strip(), 5) or "").rstrip("…").split()
    while w and w[-1] in ("in", "and", "or", "the", "of", "to", "at", "on", "with", "for", "a"):
        w.pop()
    return " ".join(w)


def voice_brief(plan: dict, max_words: int = 60) -> str:
    """~20 s spoken brief (README §2 style), <= max_words. Only cited plan values, condensed."""
    b = plan.get("building", {})
    unit = config.unit_name()
    stories, year = val(b.get("stories")), val(b.get("year_built"))
    approx = isinstance(b.get("stories"), dict) and b["stories"].get("approx")
    ptype = condense(str(val(b.get("property_type")) or "building").lower().replace("/", " "), 3)
    desc = []
    if stories:
        try:
            n = int(stories)
            desc.append(f"{'about ' if approx else ''}{_NUM.get(n, str(n))}-story {ptype}")
        except (TypeError, ValueError):
            desc.append(ptype)
    else:
        desc.append(ptype)
    if year:
        desc.append(f"built {year}")
    cons = val(b.get("construction"))
    if cons and "era-inferred" not in str(cons):
        desc.append("concrete tilt-up" if "tilt" in str(cons).lower() else condense(re.sub(r"\s*\(.*", "", str(cons)).lower(), 4))
    # (priority, sentence) - lower priority number kept first when trimming
    sents: list[tuple[int, str]] = [(0, f"{unit}, {', '.join(desc)}")]
    hz = sorted([h for h in plan.get("hazards") or [] if isinstance(h, dict) and not h.get("verify_on_site")],
                key=lambda h: -(h.get("conf") or 0))
    th = [h for h in hz if h.get("tenant")]
    if th:
        h = th[0]
        loc = f", {h['location'].lower()}" if h.get("location") and h["location"] != VERIFY else ""
        sents.append((1, f"Tenant {h['tenant']}: possible {_hz_phrase(h)}{loc}"))
    other = sorted([h for h in hz if not h.get("tenant")],
                   key=lambda h: (0 if str((h.get("cite") or {}).get("id", "")).startswith("rule:") else 1, -(h.get("conf") or 0)))
    rest = sorted(other + th[1:], key=lambda h: (0 if str((h.get("cite") or {}).get("id", "")).startswith("rule:") else 1,
                                                 -(h.get("conf") or 0)))
    if rest:
        skip = {_hz_phrase(th[0])} if th else set()
        ph = [x for x in dict.fromkeys(_hz_phrase(h) for h in rest) if x and x not in skip][:3]
        if ph:
            sents.append((1, "Hazards: " + ", ".join(ph)))
    st = _get(plan, "interior", "stairwells")
    if isinstance(st, list) and st:
        n = len(st)
        sp = [x for x in st if x.get("standpipe")]
        sents.append((2, f"{_NUM.get(n, n)} stair{'s' if n > 1 else ''} in the scan" +
                      (f", standpipe in {condense(sp[0]['loc'], 4)}" if sp else "")))
    else:
        sents.append((4, "Stairs: verify on site"))
    ras = roof_access_short(plan)
    sents.append((2, f"Roof access: {ras}" if ras else "Roof access: verify on site"))
    ex = [e for e in (plan.get("exposures") or []) if isinstance(e, dict) and is_building_exposure(e)] \
        if isinstance(plan.get("exposures"), list) else []
    if ex:
        e = sorted(ex, key=lambda e: e.get("gap_m") if isinstance(e.get("gap_m"), (int, float)) else 999)[0]
        side = _SIDES.get(str(e.get("side", "")).upper(), str(e.get("side", "")).lower().replace("/", " to "))
        gap = e.get("gap_m")
        what = condense(str(e.get("desc", "")).split(",")[0], 4)
        sents.append((3, f"Exposure {side}: {what}" + (f", {gap * 3.281:.0f} feet" if isinstance(gap, (int, float)) else "")))
    if plan.get("officer_note"):
        sents.append((0, f"Officer note: {condense(plan['officer_note'], 15)}"))

    def render(items):
        return ". ".join(x[0].upper() + x[1:] for _, x in items if x).replace("…", "") + "."

    items = list(sents)
    while len(render(items).split()) > max_words and len(items) > 1:
        worst = max(range(len(items)), key=lambda i: (items[i][0], i))
        items.pop(worst)
    out = no_dash(render(items))
    w = out.split()
    if len(w) > max_words:
        out = " ".join(w[:max_words]).rstrip(",.;") + "."
    return out.replace("..", ".")


def construction_short(c) -> str | None:
    """Cab-friendly construction: 'Concrete tilt-up', 'Steel', 'Masonry'..."""
    if not c:
        return None
    t = str(c)
    if re.search(r"tilt", t, re.I):
        return "Concrete tilt-up"
    t = re.sub(r"\s*\(.*", "", t).strip()
    t = re.sub(r",?\s*era-inferred.*", "", t, flags=re.I).strip()
    return condense(t, 4) or None


def incab_summary(plan: dict, audio_url: str | None = None) -> dict:
    b = plan.get("building", {})
    return {
        "plan_id": plan.get("plan_id"),
        "building_id": plan.get("building_id"),
        "address": b.get("address"),
        "stories": val(b.get("stories")) or VERIFY,
        "year_built": val(b.get("year_built")) or VERIFY,
        "construction": construction_short(val(b.get("construction"))) or VERIFY,
        "construction_detail": val(b.get("construction")) or VERIFY,
        "top_hazards": top_hazards(plan),
        "top_hazards_detail": top_hazards_detail(plan),
        "stairs": stairs_text(plan) or VERIFY,
        "roof_access": val(_get(plan, "access", "roof_access")) or VERIFY,
        "roof_access_short": roof_access_short(plan) or VERIFY,
        "voice_brief": plan.get("voice_brief"),
        "audio_url": audio_url,
        "pdf_url": plan.get("pdf_url"),
        "html_url": plan.get("html_url"),
        "approved_by": plan.get("approved_by"),
        "approved_at": plan.get("approved_at"),
    }


def finalize(plan: dict) -> dict:
    """Validate + refresh brief. Returns the validator result (plan under 'plan')."""
    plan = dict(plan)
    it = plan.get("interior")
    if isinstance(it, dict) and isinstance(it.get("stairwells"), list):
        clean = []
        for x in it["stairwells"]:
            if not isinstance(x, dict) or x.get("value") == VERIFY:
                continue
            if not str(x.get("loc") or "").strip() or str(x.get("loc")).strip() == "?":
                x = {**x, "loc": "Stair (unlabeled)"}
            clean.append(x)
        plan["interior"] = {**it, "stairwells": clean or dict(V)}
    res = validate_plan(no_dash(plan))
    if res["plan"] is not None:
        res["plan"]["voice_brief"] = voice_brief(res["plan"])
    return res


def interior_observations(mp: dict) -> list[dict]:
    """Flatten Matterport VLM pano analyses into [{text, sweep_id, room, floor, cite}] for hazard rules."""
    out = []
    for a in (mp or {}).get("pano_analyses") or []:
        r = a.get("result") or {}
        if r.get("error"):
            continue
        texts = [str(r.get("answer") or "")]
        f = r.get("findings") or {}
        f = f.get("findings", f) if isinstance(f, dict) else {}
        for k, v in (f.items() if isinstance(f, dict) else []):
            texts.append(f"{k}: {v.get('value') if isinstance(v, dict) else v}")
        texts += [str(d.get("label")) for d in r.get("detections") or [] if isinstance(d, dict)]
        rg = (r.get("findings") or {}).get("room_guess") if isinstance(r.get("findings"), dict) else None
        area = a.get("scan") or condense(rg, 4) or a.get("room")
        out.append({"text": " | ".join(texts), "sweep_id": a.get("sweep_id"), "room": a.get("room"), "floor": a.get("floor"),
                    "area": area,
                    "cite": {"id": a.get("sweep_id"), "url": a.get("image_url"), "bbox": None}})
    return out
