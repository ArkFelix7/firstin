"""Deterministic hazard inference from tenants + construction era + roof description.

Every hazard carries an inference citation with `from` pointing at the evidence
fields that triggered it (CONTRACTS citation object).
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from .. import config


@lru_cache(maxsize=1)
def load_rules() -> dict:
    return yaml.safe_load(config.HAZARDS_YAML.read_text())


def _kw_hit(text: str, keywords: list[str]) -> str | None:
    t = f" {text.lower()} "
    for k in keywords:
        k = k.lower()
        # word-start match for all keywords ("dental" must not hit "Occidental"); short ones whole-word
        rx = rf"\b{re.escape(k)}\b" if len(k) <= 4 else rf"\b{re.escape(k)}"
        if re.search(rx, t, re.I):
            return k
    return None


def _code_hit(code, prefixes: list[str]) -> str | None:
    if code is None:
        return None
    c = re.sub(r"\D", "", str(code))
    for p in prefixes or []:
        if c and c.startswith(str(p)):
            return str(p)
    return None


def _floor_loc(t: dict) -> str | None:
    f = t.get("floor")
    if f in (None, ""):
        return None
    return f"Floor {f}" + (f", suite {t['suite']}" if t.get("suite") else "")


LIGHTWEIGHT_EVIDENCE = re.compile(r"\b(wood|frame|lightweight|truss|joist|i-joist|engineered|podium|type v)", re.I)
HEAVY_CONSTRUCTION = re.compile(r"\b(concrete|steel|masonry|tilt|brick|reinforced)", re.I)
# scan-panorama evidence must name the structure itself (bare "frame" also matches door/window frames)
LIGHTWEIGHT_SCAN = re.compile(r"\b(wood[- ]fram\w*|wood (roof |floor )?truss\w*|engineered (wood|lumber|joist)\w*|i-joists?|"
                              r"open[- ]web (wood )?joists?|lightweight (wood|truss|construction|framing))", re.I)
REDEVELOPED = re.compile(r"\b(redevelop|historic|conver|adaptive reuse|originally built|restor)", re.I)


# Rules that must match the tenant's CoStar-native classification (name, industry, the part of `use`
# before any ';' - costar.py appends description-derived keywords after it). E.g. "Global Importing
# Group" (use "Wholesaler (industrial space); coffee, distribution") must NOT fire the restaurant rule.
STRICT_RULES = {"restaurant_cooking"}
NOT_FOOD_SERVICE = re.compile(r"wholesal|distribut|import|manufactur|warehouse|logistic", re.I)


def strict_text(t: dict) -> str:
    use = str(t.get("use") or "").split(";")[0]
    txt = " ".join(str(x) for x in (t.get("name"), t.get("industry"), use) if x)
    # CoStar's broad sector label "Accommodation & Food Services" covers cleaners, hotels, caterers...: not specific
    return re.sub(r"accommodation\s*(&|and)\s*food services?", " ", txt, flags=re.I)


def match_hazards(tenants: list[dict] | None = None, year_built: int | None = None, roof: str | None = None,
                  interior: list[dict] | None = None, construction: str | None = None) -> dict:
    """Seed-rule hazard inference.

    tenants: [{name, use, naics?, sic?, floor?, cite?}] (CoStar tenants)
    year_built: int (CoStar)
    roof: free-text roof description (aerial analyst / Vexcel roof layer)
    construction: CoStar construction / material / description text. The modern "lightweight" era rule
      fires ONLY with construction evidence (wood/frame/truss...) and never for concrete/steel/masonry
      or redeveloped buildings: year_built alone is not enough.
    interior: [{text, sweep_id?, room?, floor?, cite?}] observations from Matterport VLM analysis
    Returns {"hazards": [{type, location, reason, rule, tactics, conf, cite}]}.
    """
    rules = load_rules()
    out: list[dict] = []
    tenants = tenants or []
    for i, t in enumerate(tenants):
        if not isinstance(t, dict):
            continue
        text = " ".join(str(t.get(k) or "") for k in ("name", "use", "industry"))
        strict = strict_text(t)
        for r in rules.get("tenant_rules", []):
            why = None
            if r["id"] in STRICT_RULES and NOT_FOOD_SERVICE.search(strict) and not re.search(r"restaurant|food service|cafe|bar\b", strict, re.I):
                continue
            kw = _kw_hit(strict if r["id"] in STRICT_RULES else text, r.get("keywords", []))
            if kw:
                why = f"tenant '{t.get('name')}' matches '{kw}'"
            elif (n := _code_hit(t.get("naics"), r.get("naics", []))):
                why = f"tenant '{t.get('name')}' NAICS {t.get('naics')} (prefix {n})"
            elif (s := _code_hit(t.get("sic"), r.get("sic", []))):
                why = f"tenant '{t.get('name')}' SIC {t.get('sic')} (prefix {s})"
            if not why:
                continue
            tcite = t.get("cite") or {}
            frm = [f"costar.tenants[{i}]"] + ([f"costar:{tcite['id']}"] if tcite.get("id") else [])
            out.append({
                "type": r["hazard"], "location": _floor_loc(t) or "VERIFY ON SITE",
                "tenant": t.get("name"), "reason": why, "rule": r["id"], "tactics": r.get("tactics"),
                "conf": r.get("conf", 0.5),
                "cite": {"src": "inference", "id": f"rule:{r['id']}", "conf": r.get("conf", 0.5),
                         "bbox": None, "url": None, "from": frm},
            })
    try:
        yb = int(year_built) if year_built not in (None, "") else None
    except (TypeError, ValueError):
        yb = None
    if yb:
        cons = construction or ""
        for r in rules.get("era_rules", []):
            frm, why = ["costar.year_built"], f"built {yb}"
            if "lightweight" in r["id"]:
                # needs CITED construction evidence: CoStar construction/description text, or a scan panorama that
                # explicitly shows wood framing / trusses. Never year_built alone (redevelopments keep old frames).
                if HEAVY_CONSTRUCTION.search(cons) or REDEVELOPED.search(cons):
                    continue
                m = LIGHTWEIGHT_EVIDENCE.search(cons)
                if m:
                    frm, why = frm + ["costar.construction"], f"built {yb}; CoStar construction text '{m.group(0)}'"
                else:
                    hits = [o for o in (interior or []) if isinstance(o, dict) and LIGHTWEIGHT_SCAN.search(str(o.get("text") or ""))]
                    if not hits:
                        continue
                    kw = LIGHTWEIGHT_SCAN.search(str(hits[0].get("text"))).group(0)
                    frm = frm + [f"matterport:{o.get('sweep_id') or (o.get('cite') or {}).get('id')}" for o in hits[:3]]
                    why = f"built {yb}; scan panorama shows '{kw}'"
            if r["year_min"] <= yb < r["year_max"]:
                out.append({
                    "type": r["hazard"], "location": "Building-wide", "reason": why,
                    "rule": r["id"], "tactics": r.get("tactics"), "conf": r["conf"],
                    "cite": {"src": "inference", "id": f"rule:{r['id']}", "conf": r["conf"], "bbox": None,
                             "url": None, "from": frm},
                })
    if roof:
        for r in rules.get("roof_rules", []):
            kw = _kw_hit(roof, r.get("keywords", []))
            if kw:
                vx_part, _, cs_part = roof.partition("; CoStar:")
                frm = []
                if _kw_hit(vx_part, [kw]):
                    frm.append("vexcel.roof_type")
                if cs_part and _kw_hit(cs_part, [kw]):
                    frm += ["costar.construction", "costar.description_flags"]
                frm = frm or ["vexcel.roof_type"]
                out.append({
                    "type": r["hazard"], "location": "Roof", "reason": f"roof described as '{kw}'",
                    "rule": r["id"], "tactics": r.get("tactics"), "conf": r["conf"],
                    "cite": {"src": "inference", "id": f"rule:{r['id']}", "conf": r["conf"], "bbox": None,
                             "url": None, "from": frm},
                })
    for obs in interior or []:
        if not isinstance(obs, dict):
            continue
        text = str(obs.get("text") or "")
        for r in rules.get("interior_rules", []):
            kw = _kw_hit(text, r.get("keywords", []))
            if not kw:
                continue
            c = obs.get("cite") or {}
            loc = ", ".join(x for x in (str(obs.get("area") or obs.get("room") or "").strip(),
                                         f"Floor {obs['floor']}" if obs.get("floor") else "") if x)
            out.append({
                "type": r["hazard"], "location": loc or "VERIFY ON SITE", "reason": f"scan panorama shows '{kw}'",
                "rule": r["id"], "tactics": r.get("tactics"), "conf": r["conf"],
                "cite": {"src": "inference", "id": f"rule:{r['id']}", "conf": r["conf"], "bbox": c.get("bbox"),
                         "url": c.get("url"), "from": [f"matterport:{obs.get('sweep_id') or c.get('id')}"]},
            })
    # dedupe same rule + same location
    seen, uniq = set(), []
    for h in sorted(out, key=lambda h: -h["conf"]):
        k = (h["rule"], h.get("tenant")) if h["rule"].startswith("interior_") else (h["rule"], h["location"], h.get("tenant"))
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return {"hazards": merge_hazards(uniq), "rules_version": "seed-1"}


# ---------------------------------------------------------------- merge duplicates
_FLOOR_LOC = re.compile(r"^Floor (\S+?)(?:, suites? (.+))?$")


def _floor_key(f: str):
    return (0, float(f)) if re.fullmatch(r"-?\d+(\.\d+)?", f) else (1, f)


def combine_locations(locs: list) -> str:
    """['Floor 1, suite 110', 'Floor 1', 'Floor 1, suite 130'] -> 'Floor 1, suites 110, 130';
    ['Floor 2', 'Floor 4'] -> 'Floors 2, 4'. Other strings are joined with '; '."""
    locs = [str(x).strip() for x in dict.fromkeys(locs) if x and str(x).strip() and x != "VERIFY ON SITE"]
    if not locs:
        return "VERIFY ON SITE"
    floors: dict[str, list] = {}
    other: list[str] = []
    for loc in locs:
        m = _FLOOR_LOC.match(loc)
        if m:
            floors.setdefault(m.group(1), [])
            # "" marks a tenant on this floor without a suite number
            floors[m.group(1)] += [x.strip() for x in m.group(2).split(",") if x.strip()] if m.group(2) else [""]
        else:
            other.append(loc)
    parts = []
    fl = sorted(floors, key=_floor_key)
    if len(fl) > 1 and not any(x for v in floors.values() for x in v):
        parts.append("Floors " + ", ".join(fl))
    else:
        for f in fl:
            su = list(dict.fromkeys(x for x in floors[f] if x))
            incl = "incl. " if su and "" in floors[f] else ""
            parts.append(f"Floor {f}" + (f", {incl}suite{'s' if len(su) > 1 else ''} {', '.join(su)}" if su else ""))
    parts += [o for o in other if o not in parts]
    if "Building-wide" in parts and len(parts) > 1:
        parts.remove("Building-wide")
    return "; ".join(parts)


def _hz_key(h: dict) -> str:
    return re.sub(r"\s+", " ", str(h.get("type") or "")).strip().lower()


def merge_hazards(hazards: list | None) -> list:
    """One hazard per rule/type: same-type hazards from several tenants (or several scan panoramas) become ONE
    item with a combined location ('Floor 1, suites 110, 130'), `tenants` + `basis` ('tenants A, B, C') and the
    union of every source cite in `cite.from`. Order = first (highest-ranked) occurrence. Idempotent."""
    if not isinstance(hazards, list):
        return hazards
    groups: dict[str, list] = {}
    order: list = []
    for h in hazards:
        if not isinstance(h, dict) or not h.get("type"):
            order.append(h)
            continue
        k = _hz_key(h)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(h)
    out = []
    for k in order:
        if not isinstance(k, str):
            out.append(k)
            continue
        hs = groups[k]
        if len(hs) == 1:
            out.append(hs[0])
            continue
        best = max(hs, key=lambda h: h.get("conf") or 0)
        tenants: list[str] = []
        for h in hs:
            for t in (h.get("tenants") or ([h["tenant"]] if h.get("tenant") else [])):
                if t and t not in tenants:
                    tenants.append(t)
        frm: list = []
        for h in hs:
            for f in ((h.get("cite") or {}).get("from") or []):
                if f not in frm:
                    frm.append(f)
        reasons = list(dict.fromkeys(str(h.get("reason")) for h in hs if h.get("reason")))
        conf = max((h.get("conf") or 0) for h in hs)
        m = {**best, "location": combine_locations([h.get("location") for h in hs]),
             "reason": "; ".join(reasons) or best.get("reason"), "conf": conf,
             "cite": {**(best.get("cite") or {}), "conf": conf, "from": frm or (best.get("cite") or {}).get("from")},
             "merged": sum(int(h.get("merged") or 1) for h in hs)}
        if tenants:
            m["tenants"] = tenants
            m["tenant"] = ", ".join(tenants)
            m["basis"] = f"tenant{'s' if len(tenants) > 1 else ''} {', '.join(tenants)}"
        else:
            m.pop("tenant", None)
            m["basis"] = f"{m['merged']} observations"
        out.append(m)
    return out
