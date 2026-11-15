"""Deterministic OFFLINE pipeline (no API key / FIRSTIN_OFFLINE=1).

Calls the same tools in the same order as the deep agent, uses cached VLM answers only,
rule-based hazards, the deterministic plan builder + validator, and emits the SAME SSE
event sequence (todo / subagent_start / tool_call / tool_result / evidence / plan /
interrupt / published / done) with realistic pacing (~25-35 s to the interrupt).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any, Callable

from . import config
from .plan_builder import build_plan, condense, interior_observations, no_dash
from .runs import Run
from .tools import hazard_rules, registry, sources, vision
from .tools.validator import validate_plan

TODOS = [
    "Resolve building + pull registry record",
    "NFPA 1660 §Building: construction, stories, area, era (CoStar)",
    "NFPA 1660 §Occupancy: tenants, uses, occupant load (CoStar)",
    "NFPA 1660 §Access: roof, staging, hydrants, exposures (Vexcel aerial + VLM)",
    "NFPA 1660 §Interior: stairs, elevators, utilities, fire protection (Matterport + VLM)",
    "NFPA 1660 §Hazards: tenant-mix + construction-era inference",
    "Assemble /plan/draft.json",
    "Validate: cite every field or VERIFY ON SITE",
    "Officer approval -> publish to in-cab unit",
]

STAIR_FIRST = re.compile(r"stair|elec|mech|utility|lobby|entr|corridor|hall|riser|pump", re.I)


TOOL_SOURCE = {
    "costar_property": "costar", "costar_tenants": "costar",
    "vexcel_tile": "vexcel", "vexcel_roof": "vexcel", "vexcel_footprint": "vexcel", "vexcel_oblique": "vexcel",
    "analyze_aerial_image": "vexcel",
    "matterport_model": "matterport", "matterport_panoramas": "matterport", "analyze_interior_image": "matterport",
    "describe_image": "vision", "match_hazards": "hazards", "add_hazards": "hazards",
}


def evidence_path(tool: str, n: int = 0) -> str | None:
    """Virtual-FS path where a data tool's result is auto-saved (same in agent + offline mode)."""
    src = TOOL_SOURCE.get(tool)
    if not src:
        return None
    return f"/evidence/{src}/{tool}{'' if n == 0 else f'_{n + 1}'}.json"


def pick_panos(plist: list[dict], n: int) -> list[dict]:
    """Diverse pano selection: one per (room, scan) first, fire-relevant rooms first."""
    plist = sorted(plist, key=lambda p: 0 if STAIR_FIRST.search(str(p.get("room") or "")) else 1)
    seen, first, rest = set(), [], []
    for p in plist:
        k = (p.get("room"), p.get("scan") or p.get("model_id"))
        (rest if k in seen else first).append(p)
        seen.add(k)
    return (first + rest)[:n]


def roof_text(vx: dict) -> str | None:
    """Roof description for hazard rules: Vexcel AI roof layer + VLM roof_type."""
    t = ((vx.get("roof") or {}).get("target") or {}) if isinstance(vx.get("roof"), dict) else {}
    parts = [str(t.get(k)) for k in ("roof_shape", "roof_material") if t.get(k)]
    if (t.get("roof_objects") or {}).get("solar"):
        parts.append("solar")
    for k, v in (t.get("roof_defects_pct") or {}).items():
        if isinstance(v, (int, float)) and v >= {"water-pooling": 3}.get(k, 1) and k in ("structural-damage", "water-pooling", "rust", "missing-material"):
            parts.append(k.replace("-", " "))
    vlm = (((vx.get("analysis") or {}).get("findings") or {}).get("roof_type") or {})
    if isinstance(vlm, dict) and vlm.get("value"):
        parts.append(str(vlm["value"]))
    return " ".join(parts) or None


def summarize(res: Any) -> str:
    if not isinstance(res, dict):
        return str(res)[:160]
    if res.get("error"):
        return f"error: {res['error']}"
    bits = []
    for k in ("address", "year_built", "stories", "rba_sqft", "property_type", "tile_id", "shows_facade", "model_id", "sweep_count"):
        if res.get(k) not in (None, ""):
            bits.append(f"{k}={res[k]}")
    if "tenants" in res and isinstance(res["tenants"], list):
        bits.append(f"{len(res['tenants'])} tenants")
    if "panos" in res:
        bits.append(f"{len(res['panos'])} panoramas")
    if "rooms" in res:
        bits.append(f"{len(res['rooms'])} rooms")
    if isinstance(res.get("target"), dict):
        t = res["target"]
        bits.append(f"roof {t.get('roof_shape')}/{t.get('roof_material')} cond {t.get('roof_condition_1to5')}, "
                    f"height ~{t.get('height_est_m')} m, {len(res.get('exposures') or [])} exposures")
    if "footprint_area_m2" in res:
        bits.append(f"footprint {res['footprint_area_m2']:.0f} m2")
    if "hazards" in res:
        bits.append(f"{len(res['hazards'])} hazards: " + "; ".join(h.get("type", "?") if isinstance(h, dict) else str(h) for h in res["hazards"][:3]))
    if "detections" in res:
        bits.append(f"{len(res['detections'])} detections" + (" (cached VLM)" if res.get("cached") else ""))
        if res.get("answer"):
            bits.append(str(res["answer"])[:120])
    if "stats" in res:
        bits.append(json.dumps(res["stats"]))
    return ", ".join(bits) or "ok"


def compact(res: Any, limit: int = 6000) -> Any:
    s = json.dumps(res, default=str)
    if len(s) <= limit:
        return res
    if isinstance(res, dict):
        out = {}
        for k, v in res.items():
            vs = json.dumps(v, default=str)
            out[k] = v if len(vs) < 1500 else (v[:8] if isinstance(v, list) else f"<{len(vs)} chars>")
        return out
    return s[:limit]


def image_of(res: Any) -> str | None:
    if isinstance(res, dict):
        if res.get("image_url"):
            return res["image_url"]
        if res.get("image_path"):
            return config.static_url(res["image_path"])
    return None


NOT_A_HAZARD = re.compile(r"discrepanc|mismatch|inconsisten|conflict(ing)? (data|record)|data quality|^unknown|^unverified|not detected|no .{0,30}detected", re.I)


def evidence_from(run: Run, files: dict | None = None, with_llm_hazards: bool = True) -> dict:
    """Evidence for the deterministic builder, from raw tool results (ground truth) recorded in
    run.extra["raw"] by BOTH the agent tool wrappers and the offline pipeline."""
    raw = run.extra.get("raw", {})

    def last(name):
        xs = raw.get(name) or []
        return xs[-1]["result"] if xs else {"error": f"{name} not called"}

    panos = last("matterport_panoramas")
    by_path = {p.get("image_path"): p for p in ((panos.get("panos") or []) if isinstance(panos, dict) else [])}
    analyses = []
    for x in raw.get("analyze_interior_image", []):
        p = by_path.get(x["args"].get("image_path"), {})
        analyses.append({"sweep_id": p.get("sweep_id"), "room": p.get("room"), "floor": p.get("floor"),
                         "scan": p.get("scan"), "model_id": p.get("model_id"), "image_url": p.get("image_url"), "result": x["result"]})
    aer = [x for x in raw.get("analyze_aerial_image", []) if not x["args"].get("shows_facade")]
    obl = []
    for x in raw.get("vexcel_oblique", []):
        an = next((y["result"] for y in raw.get("analyze_aerial_image", [])
                   if y["args"].get("image_path") == (x["result"] or {}).get("image_path")), None)
        obl.append({"tile": x["result"], "analysis": an})
    vx = {"tile": last("vexcel_tile"), "roof": last("vexcel_roof"), "footprint": last("vexcel_footprint"),
          "analysis": aer[-1]["result"] if aer else {"error": "aerial image not analyzed"}, "obliques": obl}
    mp = {"model": last("matterport_model"), "panoramas": panos, "pano_analyses": analyses}
    ten = last("costar_tenants")
    prop = last("costar_property")
    roof = roof_text(vx) or ""
    cons_text = ""
    if isinstance(prop, dict) and not prop.get("error"):
        cons_text = " ".join(str(x) for x in (prop.get("construction"), prop.get("construction_material"),
                                              " ".join(prop.get("description_flags") or []).replace("_", " "),
                                              (prop.get("description") or "")[:600]) if x)
        flags = " ".join(str(f).replace("_", " ") for f in (prop.get("description_flags") or []))
        cs = f"{prop.get('construction') or prop.get('construction_material') or ''} {flags}".strip()
        if cs:
            roof = f"{roof}; CoStar: {cs}"
    hz = hazard_rules.match_hazards((ten or {}).get("tenants") if isinstance(ten, dict) else None,
                                    (prop or {}).get("year_built") if isinstance(prop, dict) else None,
                                    roof or None, interior_observations(mp), construction=cons_text or None)
    if with_llm_hazards:
        have = {h["type"] for h in hz["hazards"]}
        for x in raw.get("add_hazards", []):
            for h in (x["result"] or {}).get("hazards", []):
                if isinstance(h, dict) and NOT_A_HAZARD.search(str(h.get("type", ""))):
                    continue  # data-quality notes (e.g. "height discrepancy") are not hazards
                if isinstance(h, dict) and h.get("type") not in have:
                    h = no_dash(h)
                    hz["hazards"].append(h)
                    have.add(h["type"])
    ev = {"costar": {"property": prop, "tenants": ten}, "vexcel": vx, "matterport": mp, "hazards": hz}
    run.evidence.update(ev)
    return ev


# ---------------------------------------------------------------- replay of real agent runs
def replay_path(building_id: str):
    return config.CACHE_DIR / "replay" / f"{building_id}.json"


def load_replay(building_id: str) -> dict:
    p = replay_path(building_id)
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def save_replay(run: Run) -> None:
    """After a real agent run: keep subagent summaries + LLM-added hazards so offline replays look identical."""
    import os

    if os.environ.get("FIRSTIN_SAVE_REPLAY", "1") in ("0", "false", "no"):
        return
    try:
        raw = run.extra.get("raw", {})
        data = {"run_id": run.run_id, "summaries": run.extra.get("summaries", {}),
                "add_hazards": [h for x in raw.get("add_hazards", []) for h in (x["result"] or {}).get("hazards", [])],
                "logs": run.extra.get("logs", [])[:12]}
        p = replay_path(run.building_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1, default=str))
    except Exception:  # noqa: BLE001
        pass


VISION_TOOLS = {"analyze_aerial_image", "analyze_interior_image", "describe_image"}


class Offline:
    def __init__(self, run: Run):
        self.run = run
        self.p = config.pace()
        self.n = 0
        self.raw = run.extra.setdefault("raw", {})
        self.replay = load_replay(run.building_id)

    async def sleep(self, a: float, b: float | None = None):
        if self.p > 0:
            await asyncio.sleep(self.p * (random.uniform(a, b) if b else a))

    async def tool(self, agent: str, name: str, fn: Callable, **kwargs):
        self.n += 1
        tid = f"call_{self.n:03d}"
        shown = {k: (v if len(json.dumps(v, default=str)) < 300 else f"<{len(json.dumps(v, default=str))} chars>")
                 for k, v in kwargs.items()}
        await self.run.emit("tool_call", {"id": tid, "agent": agent, "tool": name, "args": shown})
        await self.sleep(*((2.2, 3.6) if name in VISION_TOOLS else (0.5, 1.2)))
        res = await asyncio.to_thread(fn, **kwargs)
        n = len(self.raw.setdefault(name, []))
        self.raw[name].append({"args": kwargs, "result": res})
        await self.run.emit("tool_result", {"id": tid, "agent": agent, "tool": name,
                                            "ok": not (isinstance(res, dict) and res.get("error")),
                                            "summary": summarize(res), "image_url": image_of(res), "data": compact(res)})
        path = evidence_path(name, n)
        if path:
            self.run.files[path] = res
            await self.run.emit("evidence", {"path": path, "source": TOOL_SOURCE[name], "agent": agent,
                                             "content": compact(res, 20000)})
        return res

    async def todos(self, statuses: list[str]):
        await self.run.emit("todo", {"todos": [{"content": c, "status": s} for c, s in zip(TODOS, statuses)]})

    async def subagent(self, name: str, description: str, coro):
        self.n += 1
        sid = f"task_{self.n:03d}"
        await self.run.emit("subagent_start", {"id": sid, "name": name, "description": description})
        summary = await coro
        summary = (self.replay.get("summaries") or {}).get(name) or summary
        await self.sleep(0.8, 1.5)  # the analyst "writes" its summary
        await self.run.emit("subagent_end", {"id": sid, "name": name, "summary": summary})
        return summary

    # ------------------------------------------------------------ branches
    async def costar(self, bid: str) -> str:
        a = "costar-analyst"
        await self.sleep(1.0, 1.8)
        prop = await self.tool(a, "costar_property", sources.costar_property, building_id=bid)
        ten = await self.tool(a, "costar_tenants", sources.costar_tenants, building_id=bid)
        if prop.get("error"):
            await self.run.emit("log", {"agent": a, "message": f"CoStar: {prop['error']} -> building/occupancy fields will be VERIFY ON SITE"})
            return f"CoStar unavailable ({prop['error']}); fields flagged VERIFY ON SITE."
        nt = len(ten.get("tenants") or []) if isinstance(ten, dict) else 0
        return (f"{prop.get('stories') or '?'}-story {prop.get('property_type') or ''}, built {prop.get('year_built') or '?'}, "
                f"{prop.get('rba_sqft') or '?'} sf; {nt} tenants.")

    async def aerial(self, bid: str) -> str:
        a = "aerial-analyst"
        await self.sleep(1.0, 1.8)
        roof = await self.tool(a, "vexcel_roof", sources.vexcel_roof, building_id=bid)
        tile = await self.tool(a, "vexcel_tile", sources.vexcel_tile, building_id=bid, view="ortho")
        analysis: dict = {"error": "no tile"}
        if not tile.get("error") and tile.get("image_path"):
            analysis = await self.tool(a, "analyze_aerial_image", vision.analyze_aerial_image,
                                       image_path=tile["image_path"], preview_path=tile.get("preview_path"),
                                       preview_scale=tile.get("preview_scale"))
            if analysis.get("error"):
                await self.run.emit("log", {"agent": a, "message": f"VLM: {analysis['error']} -> using Vexcel AI roof/exposure layers; other access fields VERIFY ON SITE"})
        ob = await self.tool(a, "vexcel_oblique", sources.vexcel_oblique, building_id=bid, direction="N")
        if not ob.get("error") and ob.get("image_path"):
            await self.tool(a, "analyze_aerial_image", vision.analyze_aerial_image,
                            image_path=ob["image_path"], shows_facade=ob.get("shows_facade"))
        bits = []
        t = (roof or {}).get("target") or {}
        if t:
            bits.append(f"Roof {t.get('roof_shape')} {t.get('roof_material')}, ~{t.get('height_est_m')} m (~{t.get('stories_est')} stories est.)")
            bits.append(f"{len(roof.get('exposures') or [])} exposures within 30 m")
        f = analysis.get("findings") or {}
        if f:
            bits.append(f"roof access: {condense((f.get('roof_access') or {}).get('value'), 14)}")
        return "; ".join(bits) or "Aerial analysis unavailable; access fields VERIFY ON SITE"

    async def interior(self, bid: str) -> str:
        a = "interior-analyst"
        await self.sleep(1.0, 1.8)
        model = await self.tool(a, "matterport_model", sources.matterport_model, building_id=bid)
        panos = await self.tool(a, "matterport_panoramas", sources.matterport_panoramas, building_id=bid, room_filter=None, limit=12)
        plist = pick_panos((panos.get("panos") or []) if isinstance(panos, dict) else [], 4)
        ok = 0
        for p in plist:
            if p.get("image_path"):
                res = await self.tool(a, "analyze_interior_image", vision.analyze_interior_image, image_path=p["image_path"])
                ok += 0 if res.get("error") else 1
        if model.get("error"):
            return f"Matterport unavailable ({model['error']}); interior fields VERIFY ON SITE."
        return f"Scan {model.get('model_id')}: {len(model.get('rooms') or [])} rooms; {ok}/{len(plist)} panoramas analyzed."

    async def hazards(self) -> str:
        a = "hazard-reasoner"
        await self.sleep(1.0, 2.0)
        res = await self.tool(a, "match_hazards", lambda: evidence_from(self.run, with_llm_hazards=False)["hazards"])
        extra = self.replay.get("add_hazards") or []
        if extra:
            await self.sleep(1.5, 2.5)
            await self.tool(a, "add_hazards", lambda hazards: {"hazards": hazards, "added": len(hazards)}, hazards=extra)
        return f"{len(res['hazards']) + len(extra)} hazards: " + "; ".join(h["type"] for h in (res["hazards"] + extra)[:5])

    async def validator(self) -> str:
        a = "validator"
        await self.sleep(0.8, 1.4)
        res = await self.tool(a, "validate_plan", lambda path: validate_plan(self.run.files.get(path)), path="/plan/draft.json")
        self.run.files["/plan/final.json"] = res["plan"]
        await self.run.set_validated(res["plan"])
        s = res["stats"]
        return f"{s['cited']} cited facts, {s['verify_on_site']} VERIFY ON SITE, {s['issues']} downgraded. Wrote /plan/final.json"


async def run_offline(run: Run) -> None:
    o = Offline(run)
    bid = run.building_id
    st = ["pending"] * len(TODOS)
    await run.emit("log", {"agent": "planner", "message": f"FirstIn pre-plan run started for {run.building.get('address')}",
                           "mode": run.mode, "model": None})
    await o.sleep(2.0, 3.0)  # planner thinking
    st[0] = "in_progress"
    await o.todos(st)
    await o.tool("planner", "resolve_building", registry.resolve_building, query=bid)
    await o.sleep(1.5, 2.5)
    st[0] = "completed"
    st[1:5] = ["in_progress"] * 4
    await o.todos(st)

    await asyncio.gather(
        o.subagent("costar-analyst", f"Pull CoStar property + tenants for {bid}.", o.costar(bid)),
        o.subagent("aerial-analyst", f"Analyze Vexcel aerial for {bid}: roof, access, staging, hydrants, exposures.", o.aerial(bid)),
        o.subagent("interior-analyst", f"Analyze the Matterport twin for {bid}: stairs, elevators, utilities, fire protection, storage.", o.interior(bid)),
    )
    st[1:5] = ["completed"] * 4
    st[5] = "in_progress"
    await o.todos(st)
    await o.subagent("hazard-reasoner", "Infer hazards from tenant mix, construction era, roof and interior observations.", o.hazards())
    st[5] = "completed"
    st[6] = "in_progress"
    await o.todos(st)

    await o.sleep(1.0, 1.6)
    res = await o.tool("planner", "assemble_plan_draft",
                       lambda: build_plan(run.run_id, run.building, evidence_from(run), mode=run.mode))
    run.files["/plan/draft.json"] = res
    await run.set_draft(res)
    st[6] = "completed"
    st[7] = "in_progress"
    await o.todos(st)
    await o.subagent("validator", "Validate /plan/draft.json: every field cited or VERIFY ON SITE.", o.validator())
    st[7] = "completed"
    st[8] = "in_progress"
    await o.todos(st)

    # HITL: publish_preplan is gated -> interrupt
    o.n += 1
    pid = f"call_{o.n:03d}"
    await run.emit("tool_call", {"id": pid, "agent": "planner", "tool": "publish_preplan", "args": {"plan_id": run.run_id}})
    await run.request_approval()
    decision = await run.approval  # set by /approve
    if decision.get("decision") == "reject":
        await run.emit("tool_result", {"id": pid, "agent": "planner", "tool": "publish_preplan", "ok": False,
                                       "summary": f"Rejected by officer: {decision.get('reason') or ''}"})
        st[8] = "completed"
        await o.todos(st)
        await run.emit("done", {"status": "REJECTED"})
        return
    res = await run.do_publish()
    await run.emit("tool_result", {"id": pid, "agent": "planner", "tool": "publish_preplan", "ok": not res.get("error"),
                                   "summary": summarize(res) if res.get("error") else f"Published {res.get('pdf_url')}",
                                   "data": compact(res)})
    st[8] = "completed"
    await o.todos(st)
    await run.emit("done", {"status": run.status})
