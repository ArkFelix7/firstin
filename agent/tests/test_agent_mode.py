"""LLM-mode wiring test with a scripted fake chat model (no API key needed).

Exercises the real deepagents graph: todos, task->subagent, custom tools, virtual FS,
HITL interrupt on publish_preplan, Command(resume=...) and the SSE translation.
"""
import time

from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage


class FakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def tc(name, args, i):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"t{i}", "type": "tool_call"}])


def script(run_id):
    return iter([
        tc("write_todos", {"todos": [{"content": "Building (CoStar)", "status": "in_progress"},
                                     {"content": "Validate", "status": "pending"}]}, 1),
        tc("resolve_building", {"query": "test-001"}, 2),
        tc("task", {"description": "CoStar for test-001", "subagent_type": "costar-analyst"}, 3),
        # costar-analyst subagent
        tc("costar_property", {"building_id": "test-001"}, 4),
        AIMessage(content="4-story office built 1978."),
        # planner
        tc("assemble_plan_draft", {}, 6),
        tc("task", {"description": "validate /plan/draft.json", "subagent_type": "validator"}, 7),
        # validator subagent
        tc("validate_plan", {}, 8),
        AIMessage(content="12 cited, 9 VERIFY ON SITE."),
        # planner
        tc("publish_preplan", {"plan_id": run_id}, 9),
        AIMessage(content="Published."),
    ])


def test_agent_mode_with_fake_model(sandbox, monkeypatch):
    import langchain.chat_models as cm

    from agent import config, main, runs

    monkeypatch.setattr(config, "has_api_key", lambda: True)
    monkeypatch.setattr(config, "offline_mode", lambda: False)
    holder = {}
    orig_new_run = runs.new_run

    def new_run(b, mode):
        r = orig_new_run(b, mode)
        holder["model"] = FakeModel(messages=script(r.run_id))
        return r

    monkeypatch.setattr(main, "new_run", new_run)
    monkeypatch.setattr(cm, "init_chat_model", lambda *a, **k: holder["model"])

    with TestClient(main.app) as c:
        r = c.post("/preplan", json={"building_id": "test-001", "mode": "agent"}).json()
        rid = r["run_id"]
        assert r["mode"] == "agent"
        for _ in range(200):
            evs = c.get(f"/events/{rid}").json()
            if any(e["type"] in ("interrupt", "done") for e in evs):
                break
            time.sleep(0.05)
        kinds = [e["type"] for e in evs]
        assert "error" not in kinds, [e["payload"] for e in evs if e["type"] == "error"]
        assert "interrupt" in kinds
        assert "todo" in kinds
        starts = [e["payload"]["name"] for e in evs if e["type"] == "subagent_start"]
        assert starts == ["costar-analyst", "validator"]
        ev = [e for e in evs if e["type"] == "evidence"]
        assert ev and ev[0]["payload"]["path"] == "/evidence/costar/costar_property.json" and ev[0]["payload"]["source"] == "costar"
        sub_calls = [e["payload"] for e in evs if e["type"] == "tool_call" and e["payload"]["tool"] == "costar_property"]
        assert sub_calls and sub_calls[0]["agent"] == "costar-analyst"
        assert c.get(f"/plan/{rid}").json()["status"] == "PENDING_APPROVAL"

        assert c.post(f"/approve/{rid}", json={"approved_by": "Lt. Kim", "decision": "approve"}).status_code == 200
        for _ in range(200):
            evs = c.get(f"/events/{rid}").json()
            if any(e["type"] == "done" for e in evs):
                break
            time.sleep(0.05)
        kinds = [e["type"] for e in evs]
        assert "published" in kinds and kinds[-1] == "done", kinds
        assert evs[-1]["payload"]["status"] == "APPROVED"
        assert c.get("/incab/active").json()["plan_id"] == rid
