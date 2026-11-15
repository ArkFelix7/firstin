"""LLM mode: deepagents planner + 5 subagents, virtual FS, HITL interrupt on publish_preplan.

Verified against deepagents==0.7.38 / langgraph 1.2 / langchain 1.5:
- create_deep_agent(model, tools, system_prompt=, subagents=[{name, description, system_prompt, tools}],
  middleware=[TodoListMiddleware()]  # write_todos is NOT included by default in 0.7.x
  interrupt_on={"publish_preplan": True}, checkpointer=MemorySaver())
- stream: agent.astream(input, cfg, stream_mode=["updates"], subgraphs=True) yields (ns, mode, chunk);
  ns == () for the planner, ("tools:<task-uuid>",) inside a subagent; chunk = {node_name: update}.
  Subagent AIMessages carry .name == subagent name. Files arrive as update["files"][path] = FileData.
  Interrupt arrives as chunk["__interrupt__"] = (Interrupt(value={"action_requests": [...], ...}),).
- resume: agent.astream(Command(resume={"decisions": [{"type": "approve"}]}), same cfg)
  or {"type": "reject", "message": "..."}  (HumanInTheLoopMiddleware, batched mode).
"""
from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from langchain.agents.middleware import TodoListMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from . import config
from .pipeline import compact, evidence_from, evidence_path, image_of, save_replay, summarize
from .plan_builder import build_plan
from .runs import Run
from .tools import hazard_rules, registry, sources, vision
from .tools.validator import validate_plan as _validate

SUBAGENT_NAMES = ["costar-analyst", "aerial-analyst", "interior-analyst", "hazard-reasoner", "validator"]


def _prompt(name: str) -> str:
    return (config.PROMPTS_DIR / f"{name}.md").read_text()


def _file_json(files: dict, path: str) -> Any:
    fd = (files or {}).get(path)
    if not fd:
        return None
    content = fd.get("content") if isinstance(fd, dict) else fd
    if isinstance(content, list):
        content = "\n".join(content)
    try:
        return json.loads(content)
    except Exception:  # noqa: BLE001
        return None


def _file_data(obj: Any) -> dict:
    from deepagents.backends.utils import create_file_data

    return create_file_data(json.dumps(obj, indent=1, default=str))


# ---------------------------------------------------------------------------- tools
def make_tools(run: Run) -> dict[str, Any]:
    raw: dict[str, list] = run.extra.setdefault("raw", {})

    def T(fn, name, desc, limit: int = 8000):
        """Wrap a plain tool fn: record raw result, auto-save it to /evidence/<source>/<tool>[_n].json
        (virtual FS, via Command) and return a compact JSON ToolMessage. The LLM never re-types evidence."""
        sig = inspect.signature(fn)
        params = [p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in sig.parameters.values()]
        params.append(inspect.Parameter("runtime", inspect.Parameter.KEYWORD_ONLY, annotation=ToolRuntime))
        hints = {p.name: p.annotation for p in sig.parameters.values()}

        def f(**kw):
            rt = kw.pop("runtime")
            res = fn(**kw)
            n = len(raw.setdefault(name, []))
            raw[name].append({"args": kw, "result": res})
            msg = ToolMessage(content=json.dumps(compact(_llm_view(res), limit), default=str), tool_call_id=rt.tool_call_id, name=name)
            path = evidence_path(name, n)
            if not path:
                return Command(update={"messages": [msg]})
            return Command(update={"files": {path: _file_data(res)}, "messages": [msg]})

        f.__name__ = name
        f.__doc__ = desc
        f.__signature__ = sig.replace(parameters=params, return_annotation=Command)
        f.__annotations__ = {**{k: (v if v is not inspect.Parameter.empty else Any) for k, v in hints.items()},
                             "runtime": ToolRuntime, "return": Command}
        return tool(name, description=desc)(f)

    def _match_hazards() -> dict:
        ev = evidence_from(run, {}, with_llm_hazards=False)
        return ev["hazards"]

    def _add_hazards(hazards: list[dict]) -> dict:
        """hazards: [{type, location, reason, conf, cite: {src: "inference", id, conf, from: [...]}}]"""
        ok = [h for h in hazards if isinstance(h, dict) and h.get("type")]
        return {"hazards": ok, "added": len(ok)}

    t = {
        "resolve_building": T(registry.resolve_building, "resolve_building",
                              "Resolve a building_id or address to the demo registry record (lat/lng, ids, which layers exist)."),
        "costar_property": T(sources.costar_property, "costar_property",
                             "CoStar property record for building_id: year_built, stories, rba_sqft, class, type, construction, with cite."),
        "costar_tenants": T(sources.costar_tenants, "costar_tenants",
                            "CoStar tenant roster for building_id: name, use, NAICS/SIC, floor, SF, each with cite."),
        "vexcel_tile": T(sources.vexcel_tile, "vexcel_tile",
                         "Vexcel aerial image for building_id (view='ortho'). Returns tile_id, image_path, preview_path, preview_scale, image_url, cite."),
        "vexcel_oblique": T(sources.vexcel_oblique, "vexcel_oblique",
                            "Vexcel oblique aerial for building_id; direction N|E|S|W is where the CAMERA LOOKS, so 'N' shows the building's SOUTH facade (see shows_facade)."),
        "vexcel_roof": T(sources.vexcel_roof, "vexcel_roof",
                         "Vexcel AI roof/structure layer for building_id: roof material/shape/condition(1-5), roof objects (AC, vents, skylights, solar), defects, building type, height_est_m (DSM), stories_est (inference), exposures [{side, gap_m, building_type}] within 30 m.", 4000),
        "vexcel_footprint": T(sources.vexcel_footprint, "vexcel_footprint",
                              "Vexcel building footprint polygon (lat/lng) + pixel polygon/bbox on the cached ortho/context images.", 2000),
        "matterport_model": T(sources.matterport_model, "matterport_model",
                              "Matterport digital twin metadata for building_id: floors, labelled rooms, mattertags, sweep_count, cite.", 5000),
        "matterport_panoramas": T(sources.matterport_panoramas, "matterport_panoramas",
                                  "Matterport panorama images for building_id (optional room_filter, limit): sweep_id, floor, room, scan, image_path."),
        "analyze_aerial_image": T(vision.analyze_aerial_image, "analyze_aerial_image",
                                  "Send an aerial image to the vision model with the canonical fire-preplan aerial question. For vexcel_tile results pass image_path AND preview_path + preview_scale. For obliques pass shows_facade. Returns roof_type, roof_access, staging, hydrants, exposures, access_roads with pixel bboxes + conf."),
        "analyze_interior_image": T(vision.analyze_interior_image, "analyze_interior_image",
                                    "Send a Matterport panorama (local image_path) to the vision model to detect stairs, standpipes, alarm panel, FDC, electrical room, exits, roof structure, hazardous storage, with pixel bboxes + conf."),
        "describe_image": T(_describe, "describe_image",
                            "Ask the vision model a custom question about a local image. Returns answer + detections [{label,bbox,conf}]."),
        "match_hazards": T(_match_hazards, "match_hazards",
                           "Run the seed hazard rules over ALL evidence gathered so far (CoStar tenants + year built, Vexcel roof layer + VLM roof, Matterport pano observations). No arguments. Every hazard cites `from`."),
        "add_hazards": T(_add_hazards, "add_hazards",
                         "Add hazards the seed rules missed. Each needs {type, location, reason, conf<=0.6, cite: {src: 'inference', id: 'llm:<name>', conf, from: [evidence fields]}}."),
    }

    @tool("assemble_plan_draft", description="Deterministically assemble /plan/draft.json (README §7 schema) from all evidence + hazards. Call once after the analysts and the hazard-reasoner finished. Do not hand-edit the plan.")
    def assemble_plan_draft(runtime: ToolRuntime) -> Command:
        ev = evidence_from(run, runtime.state.get("files") or {})
        plan = build_plan(run.run_id, run.building, ev, mode=run.mode)
        return Command(update={
            "files": {"/plan/draft.json": _file_data(plan)},
            "messages": [ToolMessage(content=json.dumps({"path": "/plan/draft.json", "sources": plan["sources"],
                                                         "hazards": [h["type"] for h in plan["hazards"]]}),
                                     tool_call_id=runtime.tool_call_id)],
        })

    @tool("validate_plan", description="Validate /plan/draft.json: deterministically enforce cite-or-VERIFY-ON-SITE on every leaf (fixing violations), write /plan/final.json, return the issues fixed.")
    def validate_plan_tool(runtime: ToolRuntime, path: str = "/plan/draft.json") -> Command:
        plan = _file_json(runtime.state.get("files") or {}, path)
        if plan is None:
            return Command(update={"messages": [ToolMessage(content=f"error: {path} missing or not JSON",
                                                            tool_call_id=runtime.tool_call_id)]})
        res = _validate(plan)
        msg = {"ok": res["ok"], "stats": res["stats"], "issues": res["issues"][:20],
               "verify_on_site": res["verify_on_site"][:40]}
        return Command(update={
            "files": {"/plan/final.json": _file_data(res["plan"])},
            "messages": [ToolMessage(content=json.dumps(msg), tool_call_id=runtime.tool_call_id)],
        })

    @tool("publish_preplan", description="Publish the validated plan to the in-cab unit (PDF + voice brief). Requires officer approval (pauses the run).")
    async def publish_preplan(plan_id: str) -> str:
        res = await run.do_publish()
        return json.dumps({k: v for k, v in res.items() if k != "incab"}, default=str)

    t["assemble_plan_draft"] = assemble_plan_draft
    t["validate_plan"] = validate_plan_tool
    t["publish_preplan"] = publish_preplan
    return t


_BULKY = ("ring", "wkt", "polygon", "georef", "raw", "defensible_space", "capture_window", "on_images")


def _llm_view(x: Any, depth: int = 0) -> Any:
    """Drop geometry/raw blobs the LLM doesn't need (full results are still saved as evidence)."""
    if isinstance(x, dict):
        return {k: _llm_view(v, depth + 1) for k, v in x.items() if not any(b in k for b in _BULKY)}
    if isinstance(x, list):
        return [_llm_view(v, depth + 1) for v in x]
    return x


def _describe(image_path: str, question: str) -> dict:
    """Ask the vision model a custom question about a local image."""
    return vision.describe_image(image_path, question)


def _model(name: str, effort: str | None):
    from langchain.chat_models import init_chat_model

    kw: dict[str, Any] = {"max_tokens": 16000}
    if effort:
        kw["output_config"] = {"effort": effort}
    return init_chat_model(name if ":" in name else f"anthropic:{name}", **kw)


def build_agent(run: Run):
    import os

    from deepagents import create_deep_agent
    from deepagents.middleware.filesystem import FilesystemMiddleware

    t = make_tools(run)
    model = _model(config.model_name(), os.environ.get("FIRSTIN_EFFORT", "medium") or None)
    sub_name = os.environ.get("FIRSTIN_SUBAGENT_MODEL") or config.model_name()
    sub_model = _model(sub_name, os.environ.get("FIRSTIN_SUBAGENT_EFFORT", "low") or None)

    def fs(*tools):  # restrict built-in file tools (no edit loops / parallel mutations)
        return [FilesystemMiddleware(tools=sorted({"read_file", *tools}))]

    subagents = [
        {"name": "costar-analyst", "description": "Pulls building attributes, tenants and occupancy from CoStar (results auto-saved to /evidence/costar/).",
         "system_prompt": _prompt("costar"), "tools": [t["costar_property"], t["costar_tenants"]],
         "model": sub_model, "middleware": fs("ls")},
        {"name": "aerial-analyst", "description": "Analyzes Vexcel aerial imagery + AI roof layer with the vision model: roof, access, staging, hydrants, exposures (auto-saved to /evidence/vexcel/).",
         "system_prompt": _prompt("aerial"), "tools": [t["vexcel_roof"], t["vexcel_tile"], t["vexcel_oblique"], t["analyze_aerial_image"]],
         "model": sub_model, "middleware": fs("ls")},
        {"name": "interior-analyst", "description": "Analyzes the Matterport twin (rooms, tags, panoramas via vision model): stairs, elevators, utility rooms, fire protection, storage (auto-saved to /evidence/matterport/).",
         "system_prompt": _prompt("interior"), "tools": [t["matterport_model"], t["matterport_panoramas"], t["analyze_interior_image"]],
         "model": sub_model, "middleware": fs("ls")},
        {"name": "hazard-reasoner", "description": "Runs seed hazard rules over all evidence and adds cited extensions the rules missed.",
         "system_prompt": _prompt("hazards"), "tools": [t["match_hazards"], t["add_hazards"]],
         "model": sub_model, "middleware": fs("ls", "read_file")},
        {"name": "validator", "description": "Runs the deterministic cite-or-VERIFY-ON-SITE validator on /plan/draft.json (writes /plan/final.json) and reports issues.",
         "system_prompt": _prompt("validator"), "tools": [t["validate_plan"]],
         "model": sub_model, "middleware": fs("read_file")},
    ]
    return create_deep_agent(
        model=model,
        tools=[t["resolve_building"], t["assemble_plan_draft"], t["publish_preplan"]],
        system_prompt=_prompt("planner"),
        subagents=subagents,
        middleware=[TodoListMiddleware(), *fs("ls")],
        interrupt_on={"publish_preplan": True},
        checkpointer=MemorySaver(),
        name="firstin-planner",
    )


# ---------------------------------------------------------------------------- stream -> SSE
class Translator:
    def __init__(self, run: Run):
        self.run = run
        self.ns_agent: dict[str, str] = {}
        self.task_names: dict[str, str] = {}
        self.calls: dict[str, tuple[str, str]] = {}  # tool_call_id -> (agent, tool)
        self.seen_files: set = set()
        self.interrupted = False

    async def handle(self, ns: tuple, mode: str, chunk: Any) -> None:
        if mode != "updates" or not isinstance(chunk, dict):
            return
        key = ns[0] if ns else ""
        for node, upd in chunk.items():
            if node == "__interrupt__":
                if not ns:
                    self.interrupted = True
                    await on_interrupt(self.run, upd)
                continue
            if not isinstance(upd, dict):
                continue
            if "todos" in upd and not ns:
                await self.run.emit("todo", {"todos": upd["todos"]})
            if upd.get("files"):
                await self.files(upd["files"], self.ns_agent.get(key, "planner"))
            for m in upd.get("messages") or []:
                await self.message(m, ns, key)

    async def message(self, m, ns, key):
        if isinstance(m, AIMessage):
            agent = m.name or ("planner" if not ns else self.ns_agent.get(key, "subagent"))
            if ns and m.name:
                self.ns_agent[key] = m.name
            text = m.text if isinstance(m.text, str) else ""
            if text.strip():
                await self.run.emit("log", {"agent": agent if agent != "firstin-planner" else "planner", "message": text[:600]})
            for tc in m.tool_calls or []:
                if tc["name"] == "task" and not ns:
                    name = tc["args"].get("subagent_type", "?")
                    self.task_names[tc["id"]] = name
                    await self.run.emit("subagent_start", {"id": tc["id"], "name": name,
                                                           "description": tc["args"].get("description", "")})
                else:
                    a = "planner" if not ns else agent
                    self.calls[tc["id"]] = (a, tc["name"])
                    args = {k: (v if len(json.dumps(v, default=str)) < 400 else f"<{len(json.dumps(v, default=str))} chars>")
                            for k, v in (tc.get("args") or {}).items()}
                    await self.run.emit("tool_call", {"id": tc["id"], "agent": a, "tool": tc["name"], "args": args})
        elif isinstance(m, ToolMessage):
            if m.name == "task" and not ns:
                name = self.task_names.get(m.tool_call_id, "?")
                self.run.extra.setdefault("summaries", {})[name] = str(m.content)[:800]
                await self.run.emit("subagent_end", {"id": m.tool_call_id, "name": name, "summary": str(m.content)[:800]})
                return
            agent, tname = self.calls.get(m.tool_call_id, (self.ns_agent.get(key, "planner"), m.name))
            content = m.content if isinstance(m.content, str) else json.dumps(m.content, default=str)
            try:
                data = json.loads(content)
            except Exception:  # noqa: BLE001
                data = content[:2000]
            await self.run.emit("tool_result", {"id": m.tool_call_id, "agent": agent, "tool": tname,
                                                "ok": m.status != "error" and not (isinstance(data, dict) and data.get("error")),
                                                "summary": summarize(data) if isinstance(data, dict) else str(data)[:200],
                                                "image_url": image_of(data), "data": compact(data)})

    async def files(self, files: dict, agent: str):
        for path, fd in files.items():
            if fd is None:
                continue
            sig = (path, (fd or {}).get("modified_at"))
            if sig in self.seen_files:
                continue
            self.seen_files.add(sig)
            obj = _file_json({path: fd}, path)
            self.run.files[path] = obj
            if path.startswith("/evidence/"):
                parts = path.strip("/").split("/")
                src = parts[1] if len(parts) > 2 else parts[-1].removesuffix(".json")
                await self.run.emit("evidence", {"path": path, "source": src, "agent": agent,
                                                 "content": compact(obj if obj is not None else fd.get("content"), 20000)})
            elif path == "/plan/draft.json" and isinstance(obj, dict):
                await self.run.set_draft(obj)
            elif path == "/plan/final.json" and isinstance(obj, dict):
                await self.run.set_validated(obj)


async def on_interrupt(run: Run, interrupts) -> None:
    """Make sure a validated plan exists (LLM's, else deterministic), then emit `interrupt`."""
    if run.status != "PENDING_APPROVAL" or not run.plan:
        plan = run.files.get("/plan/final.json") or run.files.get("/plan/draft.json")
        if not isinstance(plan, dict) or "building" not in plan:
            plan = build_plan(run.run_id, run.building, evidence_from(run, {}), mode=run.mode)
            await run.emit("log", {"agent": "planner", "message": "Using deterministic plan assembly (no valid /plan file)."})
        await run.set_validated(plan)
    save_replay(run)
    await run.request_approval()


async def run_agent(run: Run) -> None:
    agent = build_agent(run)
    cfg = {"configurable": {"thread_id": run.run_id}, "recursion_limit": 200}
    tr = Translator(run)
    await run.emit("log", {"agent": "planner", "message": f"FirstIn pre-plan run started for {run.building.get('address')}",
                           "mode": run.mode, "model": config.model_name()})
    msg = (f"Produce the pre-incident plan for building_id={run.building_id} "
           f"(address: {run.building.get('address')}). Run id / plan_id = {run.run_id}. "
           f"Layers available: {json.dumps(run.building.get('has') or {})}.")
    inp: Any = {"messages": [{"role": "user", "content": msg}]}
    try:
        while True:
            tr.interrupted = False
            async for ns, mode, chunk in agent.astream(inp, cfg, stream_mode=["updates"], subgraphs=True):
                await tr.handle(ns, mode, chunk)
            if not tr.interrupted:
                break
            decision = await run.approval
            if decision.get("decision") == "reject":
                inp = Command(resume={"decisions": [{"type": "reject", "message": decision.get("reason") or "Rejected by officer"}]})
            else:
                inp = Command(resume={"decisions": [{"type": "approve"}]})
    except Exception as e:  # noqa: BLE001
        import logging
        import traceback

        logging.getLogger("firstin.agent").exception("agent run %s failed", run.run_id)
        await run.emit("error", {"message": f"agent error: {type(e).__name__}: {e}", "recovering": True,
                                 "trace": traceback.format_exc(limit=6)})
    # Safety net: the LLM never reached publish_preplan -> do the HITL step ourselves.
    if run.status not in ("APPROVED", "REJECTED") and run.approval is None:
        await on_interrupt(run, None)
        decision = await run.approval
        if decision.get("decision") != "reject":
            await run.do_publish()
    elif run.status == "APPROVED" and not run.published:
        await run.do_publish()
    await run.emit("done", {"status": run.status})
