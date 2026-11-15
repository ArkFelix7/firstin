"""Deterministic cite-or-VERIFY-ON-SITE validator for pre-plans (README §7 schema).

Rules
- A *field* is a dict with a "value" key. If value != VERIFY ON SITE it must carry a
  valid cite; otherwise it is downgraded to {"value": "VERIFY ON SITE", "cite": null}.
- A *fact item* is a dict inside a list (tenants, stairwells, hazards, exposures) or any
  dict carrying a "cite" key. Without a valid cite it is kept but flagged
  "verify_on_site": true (we never present it as fact).
- Bare scalars at fact positions are wrapped: "VERIFY ON SITE" -> field; any other
  uncited scalar -> downgraded to VERIFY ON SITE (original kept in "unverified").
- Valid cite: src in VALID_SRC; conf (if present) in [0,1]; inference needs non-empty
  "from"; other sources need an id (or sweep/tile alias).
"""
from __future__ import annotations

import copy
from typing import Any

VERIFY = "VERIFY ON SITE"
VALID_SRC = {"costar", "vexcel", "matterport", "inference", "officer", "registry"}
# keys that are metadata, not facts
META_TOP = {"plan_id", "building_id", "status", "approved_by", "approved_at", "created_at", "mode",
            "voice_brief", "validation", "verify_on_site", "sources", "nfpa_sections", "summary", "notes",
            "edits", "rejected_reason", "media", "cross_checks"}
META_ANY = {"address", "costar_id", "name", "building_name", "lat", "lng", "city", "cite", "conf", "reason",
            "rule", "tactics", "tenant", "image_url", "thumb_url", "model_id", "unverified", "verify_on_site",
            "loc", "side", "desc", "type", "location", "use", "floor", "suite", "sqft", "naics", "sic",
            "standpipe", "label", "room", "sweep_id", "building_id", "model_id", "approx", "basis", "gap_m", "agreement", "cross_check", "employees", "move_in", "future_move_in", "industry", "short"}


def cite_problem(c: Any) -> str | None:
    if not isinstance(c, dict):
        return "missing cite"
    src = c.get("src")
    if src not in VALID_SRC:
        return f"invalid src {src!r}"
    conf = c.get("conf")
    if conf is not None:
        try:
            if not 0.0 <= float(conf) <= 1.0:
                return f"conf out of range {conf}"
        except (TypeError, ValueError):
            return f"bad conf {conf!r}"
    if src == "inference":
        if not c.get("from"):
            return "inference cite without 'from'"
    elif not (c.get("id") or c.get("sweep") or c.get("tile") or c.get("record_id")):
        return f"{src} cite without id"
    return None


def _normalize_cite(c: dict) -> dict:
    c = dict(c)
    if not c.get("id"):
        c["id"] = c.get("sweep") or c.get("tile") or c.get("record_id")
    for k in ("conf", "bbox", "url", "from"):
        c.setdefault(k, None)
    return c


class _V:
    def __init__(self):
        self.issues: list[dict] = []
        self.flagged: list[str] = []
        self.cited = 0

    def field(self, node: dict, path: str) -> dict:
        val = node.get("value")
        if val in (None, "", VERIFY) or (isinstance(val, str) and val.strip().upper() == VERIFY):
            out = {**node, "value": VERIFY, "cite": None}
            self.flagged.append(path)
            return out
        prob = cite_problem(node.get("cite"))
        if prob:
            self.issues.append({"path": path, "problem": prob, "action": "downgraded to VERIFY ON SITE"})
            self.flagged.append(path)
            return {"value": VERIFY, "cite": None, "unverified": val}
        self.cited += 1
        return {**node, "cite": _normalize_cite(node["cite"])}

    def item(self, node: dict, path: str) -> dict:
        out = {}
        for k, v in node.items():
            out[k] = v if k in META_ANY or k == "value" else self.walk(v, f"{path}.{k}")
        prob = cite_problem(node.get("cite"))
        if prob:
            self.issues.append({"path": path, "problem": prob, "action": "flagged verify_on_site"})
            self.flagged.append(path)
            out["cite"] = None
            out["verify_on_site"] = True
        else:
            self.cited += 1
            out["cite"] = _normalize_cite(node["cite"])
            out.pop("verify_on_site", None)
        return out

    def walk(self, node: Any, path: str) -> Any:
        if isinstance(node, dict):
            if "value" in node:
                return self.field(node, path)
            if "cite" in node:
                return self.item(node, path)
            return {k: (v if k in META_ANY and not isinstance(v, (dict, list)) else self.walk(v, f"{path}.{k}"))
                    for k, v in node.items()}
        if isinstance(node, list):
            res = []
            for i, v in enumerate(node):
                p = f"{path}[{i}]"
                if isinstance(v, dict) and "value" not in v:
                    res.append(self.item(v, p))
                else:
                    res.append(self.walk(v, p))
            return res
        # bare scalar at a fact position
        if isinstance(node, str) and node.strip().upper() == VERIFY:
            self.flagged.append(path)
            return {"value": VERIFY, "cite": None}
        if node is None:
            self.flagged.append(path)
            return {"value": VERIFY, "cite": None}
        if isinstance(node, bool):
            return node
        self.issues.append({"path": path, "problem": "uncited scalar", "action": "downgraded to VERIFY ON SITE"})
        self.flagged.append(path)
        return {"value": VERIFY, "cite": None, "unverified": node}


def validate_plan(plan: dict) -> dict:
    """Validate + normalize a pre-plan. Returns {ok, plan, issues, verify_on_site, stats}.

    ok == True when no *uncited claims* were found (VERIFY ON SITE fields are fine).
    The returned plan is safe to show: every leaf is cited or VERIFY ON SITE.
    """
    if not isinstance(plan, dict):
        return {"ok": False, "plan": None, "issues": [{"path": "$", "problem": "plan is not an object"}],
                "verify_on_site": [], "stats": {}}
    v = _V()
    out: dict = {}
    for k, val in copy.deepcopy(plan).items():
        if k in META_TOP:
            out[k] = val
        elif k == "building" and isinstance(val, dict):
            out[k] = {bk: (bv if bk in META_ANY else v.walk(bv, f"building.{bk}")) for bk, bv in val.items()}
        else:
            out[k] = v.walk(val, k)
    out["verify_on_site"] = sorted(set(v.flagged))
    out["validation"] = {"ok": not v.issues, "issues": v.issues, "cited": v.cited, "flagged": len(set(v.flagged))}
    return {"ok": not v.issues, "plan": out, "issues": v.issues, "verify_on_site": out["verify_on_site"],
            "stats": {"cited": v.cited, "verify_on_site": len(set(v.flagged)), "issues": len(v.issues)}}
