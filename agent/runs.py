"""In-memory run registry + per-run event log (SSE fan-out) + approval plumbing."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import config
from .plan_builder import finalize, no_dash, voice_brief
from .tools import publish as publish_mod
from .tools import render

EVENT_TYPES = {"todo", "subagent_start", "subagent_end", "tool_call", "tool_result", "evidence", "plan",
               "interrupt", "published", "log", "error", "done"}


@dataclass
class Run:
    run_id: str
    building_id: str
    building: dict
    mode: str
    status: str = "RUNNING"  # RUNNING | PENDING_APPROVAL | APPROVED | REJECTED | ERROR | DONE
    events: list[dict] = field(default_factory=list)
    plan: dict | None = None
    validation: dict | None = None
    evidence: dict = field(default_factory=dict)
    files: dict = field(default_factory=dict)  # virtual FS mirror: path -> parsed content
    published: dict | None = None
    created_at: float = field(default_factory=time.time)
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)
    approval: asyncio.Future | None = None
    task: asyncio.Task | None = None
    finished: bool = False
    extra: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- events
    async def emit(self, type_: str, payload: dict | None = None) -> dict:
        assert type_ in EVENT_TYPES, type_
        ev = {"type": type_, "ts": time.time(), "seq": len(self.events), "run_id": self.run_id, "mode": self.mode,
              "payload": no_dash(_jsonable(payload or {}))}
        async with self.cond:
            self.events.append(ev)
            if type_ == "done":
                self.finished = True
            self.cond.notify_all()
        return ev

    async def wait_events(self, after: int, timeout: float = 15.0) -> list[dict]:
        async with self.cond:
            if len(self.events) <= after and not self.finished:
                try:
                    await asyncio.wait_for(self.cond.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
            return self.events[after:]

    # ---------------------------------------------------------------- plan
    async def set_draft(self, plan: dict, path: str = "/plan/draft.json") -> dict:
        plan = dict(plan)
        plan["status"] = "DRAFT"
        self.plan = plan
        render.write_json(plan, "draft.json")
        xc = (plan.get("building") or {}).get("cross_check")
        if isinstance(xc, dict) and xc.get("note") and not self.extra.get("xc_logged"):
            self.extra["xc_logged"] = True
            await self.emit("log", {"agent": "planner", "message": xc["note"], "kind": "cross_check", "agree": xc.get("agree")})
        await self.emit("plan", {"path": path, "status": "DRAFT", "plan": plan})
        return plan

    async def set_validated(self, plan: dict, path: str = "/plan/final.json") -> dict:
        res = finalize(plan)
        p = res["plan"]
        p["plan_id"] = self.run_id
        p["status"] = "PENDING_APPROVAL"
        p["mode"] = self.mode
        self.plan, self.validation = p, {k: res[k] for k in ("ok", "issues", "verify_on_site", "stats")}
        self.status = "PENDING_APPROVAL"
        render.write_json(p, "final.json")
        await self.emit("plan", {"path": path, "status": "PENDING_APPROVAL", "plan": p, "validation": self.validation})
        return p

    async def request_approval(self) -> None:
        loop = asyncio.get_running_loop()
        self.approval = loop.create_future()
        await self.emit("interrupt", {
            "plan_id": self.run_id, "action": "publish_preplan", "allowed_decisions": ["approve", "reject"],
            "message": "Officer approval required before publishing to the in-cab unit.",
            "validation": self.validation, "plan": self.plan,
            "approve_url": f"/approve/{self.run_id}",
        })
        if self.extra.get("notify", True):
            notify_photon(self.run_id, self.plan or {})
        else:
            await self.emit("log", {"agent": "planner", "message": "Officer notification skipped (notify=false)."})

    def apply_decision(self, body: dict) -> dict:
        """Apply officer decision + edits to self.plan (sync, before resuming). Returns plan."""
        plan = dict(self.plan or {})
        by = body.get("approved_by") or "officer"
        edits = body.get("edits") or {}
        if edits:
            plan = apply_edits(plan, edits, by)
            plan["edits"] = edits
        if body.get("decision", "approve") == "reject":
            plan["status"] = "REJECTED"
            plan["rejected_reason"] = body.get("reason") or body.get("message")
            self.status = "REJECTED"
        else:
            res = finalize(plan)
            plan = res["plan"]
            plan["status"] = "APPROVED"
            plan["approved_by"] = by
            plan["approved_at"] = time.time()
            plan["voice_brief"] = (edits.get("voice_brief") if isinstance(edits.get("voice_brief"), str)
                                   else voice_brief(plan))
            self.status = "APPROVED"
        self.plan = plan
        render.write_json(plan, "final.json")
        return plan

    async def do_publish(self) -> dict:
        res = await asyncio.to_thread(publish_mod.publish_preplan, self.run_id)
        if not res.get("error"):
            self.published = res
            self.plan = publish_mod.load_plan(self.run_id)
            await self.emit("published", {**res, "approved_by": (self.plan or {}).get("approved_by"),
                                          "voice_brief": (self.plan or {}).get("voice_brief")})
        return res


def notify_photon(run_id: str, plan: dict) -> None:
    """Tell the Photon iMessage bridge an approval is pending (photon/README.md). Never blocks, fails silently."""
    import os
    import threading
    import urllib.request

    from .plan_builder import no_dash, top_hazards

    url = os.getenv("PHOTON_URL", "http://localhost:8010")
    if not url or url.lower() in ("off", "0", "none"):
        return

    def _go():
        try:
            body = {"run_id": run_id, "plan_id": run_id, "address": (plan.get("building") or {}).get("address"),
                    "summary": no_dash((plan.get("voice_brief") or "")[:300]), "top_hazards": top_hazards(plan)}
            urllib.request.urlopen(urllib.request.Request(url.rstrip("/") + "/notify", data=json.dumps(body).encode(),
                                                          headers={"content-type": "application/json"}), timeout=5)
        except Exception as e:  # noqa: BLE001
            print("[photon] notify skipped:", e)

    threading.Thread(target=_go, daemon=True).start()


def apply_edits(plan: dict, edits: dict, by: str) -> dict:
    """edits: {"access.hydrants": "Hydrant NE corner"} or nested dicts. Scalars become officer-cited fields."""
    import copy

    plan = copy.deepcopy(plan)
    officer_cite = {"src": "officer", "id": by, "conf": 1.0, "bbox": None, "url": None, "from": None}
    for path, value in _flatten_edits(edits):
        if path in ("voice_brief", "officer_note"):
            plan[path] = value
            continue
        keys = path.split(".")
        node = plan
        for k in keys[:-1]:
            if isinstance(node, list):
                node = node[int(k)]
            else:
                node = node.setdefault(k, {})
        last = keys[-1]
        if isinstance(value, dict) and ("value" in value or "cite" in value):
            new = {**value, "cite": value.get("cite") or officer_cite}
        elif isinstance(value, list):
            new = [dict(v, cite=v.get("cite") or officer_cite) if isinstance(v, dict) else v for v in value]
        else:
            new = {"value": value, "cite": officer_cite}
        if isinstance(node, list):
            node[int(last)] = new
        else:
            node[last] = new
    return plan


def _flatten_edits(edits: dict, prefix: str = ""):
    for k, v in edits.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and not ("value" in v or "cite" in v) and v:
            yield from _flatten_edits(v, path)
        else:
            yield path, v


def _jsonable(x: Any) -> Any:
    try:
        json.dumps(x)
        return x
    except TypeError:
        return json.loads(json.dumps(x, default=str))


RUNS: dict[str, Run] = {}


def new_run(building: dict, mode: str) -> Run:
    rid = f"{building.get('building_id', 'b')}-{uuid.uuid4().hex[:8]}"
    r = Run(run_id=rid, building_id=building.get("building_id"), building=building, mode=mode)
    RUNS[rid] = r
    (config.OUT_DIR / rid).mkdir(parents=True, exist_ok=True)
    return r
