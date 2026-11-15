"""FirstIn FastAPI agent server (CONTRACTS.md). Run from repo root:
    agent/.venv/bin/uvicorn agent.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import re
import traceback
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import config
from .auth import AccessCodeMiddleware
from .plan_builder import no_dash, stairs_text, top_hazards
from .runs import RUNS, Run, new_run
from .tools import publish as publish_mod
from .tools import registry
from .tools.render import cite_str
from .tools.validator import VERIFY

app = FastAPI(title="FirstIn agent server", version="0.1")
# Auth first so CORS (added after = outermost) still answers preflights and decorates 401s.
# No-op unless FIRSTIN_ACCESS_CODE is set (agent/auth.py).
app.add_middleware(AccessCodeMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", *config.cors_origins()],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)
config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
config.OUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/cache", StaticFiles(directory=str(config.CACHE_DIR)), name="cache")
app.mount("/static/out", StaticFiles(directory=str(config.OUT_DIR)), name="out")


class PreplanReq(BaseModel):
    building_id: str | None = None
    address: str | None = None
    mode: str | None = None  # "offline" | "agent" (override; default from env/key)
    notify: bool = True  # false: do not text the officer (Photon /notify) for this run (automated/test runs)


class ApproveReq(BaseModel):
    approved_by: str | None = "officer"
    decision: str = "approve"
    edits: dict[str, Any] | None = None
    reason: str | None = None


class AskReq(BaseModel):
    plan_id: str | None = None
    question: str


# ------------------------------------------------------------------ basics
@app.get("/health")
def health():
    return {"ok": True, "mode": "offline" if config.offline_mode() else "agent", "model": config.model_name(),
            "has_key": config.has_api_key(), "buildings": len(registry.list_buildings()), "runs": len(RUNS)}


@app.get("/buildings")
def buildings(featured: bool | None = None, q: str | None = None, city: str | None = None, type: str | None = None,
              limit: int | None = None, offset: int = 0):
    """Bare list (backward compatible). No params -> full registry. ?featured=true / ?q= / ?city= / ?type= filter."""
    if featured is None and not q and not city and not type and limit is None and not offset:
        return registry.list_buildings()
    if (q or city) and (limit is None or limit > 500):
        limit = 500
    _, items = registry.search(q, city, type, featured, limit, offset)
    return items


@app.get("/buildings/search")
def buildings_search(q: str | None = None, city: str | None = None, type: str | None = None,
                     featured: bool | None = None, limit: int = 20, offset: int = 0):
    """{total, items}: lightweight fields only, ranked (address prefix first, featured first)."""
    limit = max(1, min(limit, 500))
    total, items = registry.search(q, city, type, featured, limit, offset)
    return {"total": total, "items": [registry.light(b) for b in items]}


@app.get("/runs")
def runs():
    return [{"run_id": r.run_id, "building_id": r.building_id, "status": r.status, "mode": r.mode,
             "created_at": r.created_at, "events": len(r.events)} for r in RUNS.values()]


# ------------------------------------------------------------------ run lifecycle
async def _drive(run: Run):
    try:
        if run.mode == "agent":
            from .agent import run_agent

            await run_agent(run)
        else:
            from .pipeline import run_offline

            await run_offline(run)
    except Exception as e:  # noqa: BLE001
        run.status = "ERROR"
        await run.emit("error", {"message": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=4)})
        await run.emit("done", {"status": "ERROR"})


@app.post("/preplan")
async def preplan(req: PreplanReq):
    b = registry.get_building(req.building_id) if req.building_id else None
    if not b and (req.address or req.building_id):
        r = registry.resolve_building(req.address or req.building_id)
        b = None if r.get("error") else {k: v for k, v in r.items() if k != "cite"}
    if not b:
        raise HTTPException(404, f"unknown building {req.building_id or req.address}")
    mode = req.mode or ("offline" if config.offline_mode() else "agent")
    if mode == "agent" and not config.has_api_key():
        mode = "offline"
    run = new_run(b, mode)
    run.extra["notify"] = bool(req.notify)
    run.task = asyncio.create_task(_drive(run))
    return {"run_id": run.run_id, "mode": mode, "notify": run.extra["notify"], "stream_url": f"/stream/{run.run_id}"}


def _run(run_id: str) -> Run:
    r = RUNS.get(run_id)
    if not r:
        raise HTTPException(404, f"unknown run {run_id}")
    return r


@app.get("/stream/{run_id}")
async def stream(run_id: str, request: Request):
    run = _run(run_id)
    last = request.headers.get("last-event-id")
    start = int(last) + 1 if last and last.isdigit() else 0

    async def gen():
        i = start
        while True:
            if await request.is_disconnected():
                return
            evs = await run.wait_events(i, timeout=15)
            for ev in evs:
                yield {"id": str(ev["seq"]), "data": json.dumps(ev, default=str)}
            i += len(evs)
            if run.finished and i >= len(run.events):
                return

    return EventSourceResponse(gen(), ping=10)


@app.get("/events/{run_id}")
def events(run_id: str, after: int = -1):
    """Non-streaming replay of the event log (debug / polling fallback)."""
    run = _run(run_id)
    return run.events[after + 1:]


def _load_plan(plan_id: str) -> tuple[dict | None, Run | None]:
    run = RUNS.get(plan_id)
    if run and run.plan:
        return run.plan, run
    return publish_mod.load_plan(plan_id), run


@app.get("/plan/{run_id}")
def plan(run_id: str):
    p, run = _load_plan(run_id)
    if not p and not run:
        raise HTTPException(404, f"unknown run {run_id}")
    if not p:
        return {"plan_id": run_id, "status": "RUNNING" if run.status == "RUNNING" else run.status, "mode": run.mode,
                "building": {"address": run.building.get("address"), "building_id": run.building_id}}
    out = dict(p)
    if run:
        out["status"] = p.get("status") if p.get("status") in ("APPROVED", "REJECTED") else (
            "PENDING_APPROVAL" if run.status == "PENDING_APPROVAL" else p.get("status", "DRAFT"))
        out["run_status"] = run.status
        out["mode"] = run.mode
        if run.validation:
            out.setdefault("validation", run.validation)
    return out


@app.post("/approve/{run_id}")
async def approve(run_id: str, req: ApproveReq):
    run = _run(run_id)
    if run.status != "PENDING_APPROVAL" or run.approval is None or run.approval.done():
        raise HTTPException(409, f"run {run_id} is {run.status}, not awaiting approval")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision must be approve|reject")
    body = req.model_dump()
    p = run.apply_decision(body)
    run.approval.set_result(body)
    return {"ok": True, "run_id": run_id, "status": p.get("status"), "approved_by": p.get("approved_by"),
            "voice_brief": p.get("voice_brief")}


def _abs(request: Request, url: str | None) -> str | None:
    if not url or url.startswith("http"):
        return url
    base = config.public_api_url() or str(request.base_url)
    return base.rstrip("/") + url


@app.get("/incab/active")
def incab_active(request: Request):
    s = publish_mod.active_summary()
    if not s:
        raise HTTPException(404, "no approved plan yet")
    s = no_dash(dict(s))
    p = publish_mod.load_plan(str(s.get("plan_id")))
    if p:  # recompute from the plan: distinct (merged) hazards; never an era-inferred construction
        from .plan_builder import _era_only_construction, top_hazards_detail

        s["top_hazards_detail"] = top_hazards_detail(p)
        s["top_hazards"] = top_hazards(p)
        if _era_only_construction((p.get("building") or {}).get("construction")):
            s["construction"] = s["construction_detail"] = VERIFY
    for k in ("audio_url", "pdf_url", "html_url"):
        s[k] = _abs(request, s.get(k))
    return s


@app.get("/preplan/{run_id}/html", response_class=HTMLResponse)
def plan_html(run_id: str):
    f = config.OUT_DIR / run_id / "preplan.html"
    if not f.exists():
        raise HTTPException(404, "not rendered yet (approve first)")
    return FileResponse(f)


# ------------------------------------------------------------------ voice Q&A
TOPICS: list[tuple[str, list[str]]] = [
    (r"standpipe|hose (valve|connection)", ["stairs_standpipe", "interior.fire_protection.standpipe"]),
    (r"stair", ["stairs"]),
    (r"fdc|fire department connection|siamese", ["interior.fire_protection.fdc"]),
    (r"alarm|facp|panel", ["interior.fire_protection.alarm_panel"]),
    (r"sprinkler|riser", ["interior.fire_protection.sprinkler_riser"]),
    (r"knox", ["interior.fire_protection.knox_box"]),
    (r"elevator|lift", ["interior.elevators"]),
    (r"electric|power|breaker|shut ?off|utility|utilities", ["interior.utilities.electrical_room", "interior.utilities.mechanical_room"]),
    (r"gas|mechanical|boiler", ["interior.utilities.mechanical_room", "hazards"]),
    (r"roof", ["access.roof_access", "building.roof"]),
    (r"hydrant|water supply", ["access.hydrants"]),
    (r"stag|park|apparatus|where.*(engine|truck)", ["access.staging"]),
    (r"road|alley|access", ["access.access_roads", "access.roof_access"]),
    (r"hazard|chemical|danger|chlorine|flammab|battery|lithium|hazmat|asbestos|collapse", ["hazards"]),
    (r"tenant|occupan|who|business|company", ["occupancy.tenants", "occupancy.occupant_load_estimate"]),
    (r"exposure|adjacent|next door|neighbo", ["exposures"]),
    (r"stor(y|ies)|floors|tall|height|levels", ["building.stories"]),
    (r"built|year|old|age", ["building.year_built"]),
    (r"construct|frame|truss|material", ["building.construction"]),
    (r"size|square|area|big", ["building.sq_ft"]),
]


def _get_path(plan: dict, path: str):
    node: Any = plan
    for k in path.split("."):
        node = node.get(k) if isinstance(node, dict) else None
    return node


def _say(path: str, node) -> str | None:
    label = path.split(".")[-1].replace("_", " ")
    if node is None:
        return None
    if isinstance(node, dict) and "value" in node:
        if node["value"] == VERIFY:
            return f"{label}: not in the plan, verify on site"
        return f"{label}: {node['value']} (source {cite_str(node.get('cite'))})"
    if isinstance(node, list):
        if path == "hazards":
            return "Hazards: " + "; ".join(top_hazards({"hazards": node}, 4)) if node else "No hazards on record, verify on site"
        if path == "exposures":
            return "Exposures: " + "; ".join(f"{e.get('side')}: {e.get('desc')}" for e in node)
        if path == "occupancy.tenants":
            return "Tenants: " + "; ".join(f"{t.get('name')} ({t.get('use')}" + (f", floor {t['floor']}" if t.get("floor") else "") + ")" for t in node[:6])
    return None


def keyword_answer(plan: dict, q: str) -> str:
    ql = q.lower()
    out: list[str] = []
    for rx, paths in TOPICS:
        if not re.search(rx, ql):
            continue
        for p in paths:
            if p == "stairs" or p == "stairs_standpipe":
                st = _get_path(plan, "interior.stairwells")
                if isinstance(st, list) and st:
                    if p == "stairs_standpipe":
                        sp = [s for s in st if s.get("standpipe")]
                        if sp:
                            out.append("Standpipe in " + ", ".join(s["loc"] for s in sp) + f" (source {cite_str(sp[0].get('cite'))})")
                    else:
                        out.append("Stairwells: " + (stairs_text(plan) or "verify on site"))
                elif p == "stairs":
                    out.append("Stairwells: not in the plan, verify on site")
                continue
            s = _say(p, _get_path(plan, p))
            if s and s not in out:
                out.append(s)
        if out:
            break
    if not out:
        return "That isn't in the plan. Verify on site."
    return ". ".join(out[:3]) + "."


def llm_answer(plan: dict, q: str) -> str | None:
    if not config.has_api_key() or config.offline_mode():
        return None
    try:
        import anthropic

        slim = {k: v for k, v in plan.items() if k not in ("media", "validation", "sources", "events")}
        resp = anthropic.Anthropic().messages.create(
            model=config.vision_model_name(), max_tokens=400,
            system=("You answer firefighters' questions about ONE building using ONLY the pre-incident plan JSON provided. "
                    "Answer in 1-2 short spoken sentences, no markdown, no em dashes. Mention the source layer (CoStar, aerial, scan) when helpful. "
                    "If the plan doesn't contain the answer or the field is VERIFY ON SITE, say it's not in the plan and to verify on site. "
                    "Never use outside knowledge or guess."),
            messages=[{"role": "user", "content": f"PLAN JSON:\n{json.dumps(slim, default=str)[:60000]}\n\nQUESTION: {q}"}],
        )
        if resp.stop_reason == "refusal":
            return None
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip() or None
    except Exception:  # noqa: BLE001
        return None


@app.post("/ask")
async def ask(req: AskReq):
    pid = req.plan_id or (publish_mod.active_summary() or {}).get("plan_id")
    if not pid:
        raise HTTPException(404, "no plan")
    p, run = _load_plan(pid)
    if not p:
        raise HTTPException(404, f"unknown plan {pid}")
    status = p.get("status")
    if run and run.status == "PENDING_APPROVAL":
        status = "PENDING_APPROVAL"
    if status not in ("APPROVED", "PENDING_APPROVAL"):
        return {"answer": "That plan isn't ready yet. Verify on site.", "plan_id": pid, "status": status, "source": "none"}
    ans = await asyncio.to_thread(llm_answer, p, req.question)
    src = "llm"
    if not ans:
        ans, src = keyword_answer(p, req.question), "keyword"
    return {"answer": no_dash(ans), "plan_id": pid, "status": status, "source": src}
