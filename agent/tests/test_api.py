import json
import time

from fastapi.testclient import TestClient


def _events(client, run_id, until, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        evs = client.get(f"/events/{run_id}").json()
        if any(e["type"] == until for e in evs):
            return evs
        time.sleep(0.05)
    raise AssertionError(f"no {until} event; got {[e['type'] for e in evs]}")


def test_full_offline_flow(sandbox):
    from agent.main import app

    with TestClient(app) as c:
        assert c.get("/buildings").json()[0]["building_id"] == "test-001"
        assert c.get("/incab/active").status_code == 404
        r = c.post("/preplan", json={"building_id": "test-001"}).json()
        rid = r["run_id"]
        assert r["mode"] == "offline"
        evs = _events(c, rid, "interrupt")
        kinds = [e["type"] for e in evs]
        for k in ("todo", "subagent_start", "subagent_end", "tool_call", "tool_result", "evidence", "plan", "interrupt"):
            assert k in kinds, k
        assert {e["payload"]["name"] for e in evs if e["type"] == "subagent_start"} == {
            "costar-analyst", "aerial-analyst", "interior-analyst", "hazard-reasoner", "validator"}
        assert all(set(e) >= {"type", "ts", "payload"} for e in evs)

        p = c.get(f"/plan/{rid}").json()
        assert p["status"] == "PENDING_APPROVAL"
        assert p["building"]["year_built"]["value"] == 1978
        assert p["access"]["roof_access"]["value"] == "VERIFY ON SITE"  # no aerial
        assert any("Chlorine" in h["type"] for h in p["hazards"])
        assert len(p["interior"]["stairwells"]) == 2

        # Q&A before approval is allowed
        a = c.post("/ask", json={"plan_id": rid, "question": "Where's the alarm panel?"}).json()
        assert "Fire Alarm Panel" in a["answer"]

        r = c.post(f"/approve/{rid}", json={"approved_by": "Capt. Reyes", "decision": "approve",
                                            "edits": {"access.hydrants": "Hydrant at NE corner of Main St"}})
        assert r.status_code == 200, r.text
        evs = _events(c, rid, "done")
        assert "published" in [e["type"] for e in evs]

        p = c.get(f"/plan/{rid}").json()
        assert p["status"] == "APPROVED" and p["approved_by"] == "Capt. Reyes"
        assert p["access"]["hydrants"]["cite"]["src"] == "officer"

        a = c.get("/incab/active").json()
        assert a["plan_id"] == rid and a["year_built"] == 1978 and a["top_hazards"]
        assert a["audio_url"] is None or a["audio_url"].startswith("http")
        ans = c.post("/ask", json={"plan_id": rid, "question": "where is the hydrant?"}).json()["answer"]
        assert "NE corner" in ans
        assert c.post(f"/approve/{rid}", json={"decision": "approve"}).status_code == 409


def test_sse_stream_replays(sandbox):
    from agent.main import app

    with TestClient(app) as c:
        rid = c.post("/preplan", json={"building_id": "test-001"}).json()["run_id"]
        _events(c, rid, "interrupt")
        c.post(f"/approve/{rid}", json={"decision": "reject", "reason": "wrong building"})
        _events(c, rid, "done")
        with c.stream("GET", f"/stream/{rid}") as s:
            body = "".join(s.iter_text())
        datas = [json.loads(l[5:]) for l in body.splitlines() if l.startswith("data:")]
        assert datas[0]["type"] == "log" and datas[-1]["type"] == "done"
        assert datas[-1]["payload"]["status"] == "REJECTED"


def test_unknown_building(sandbox):
    from agent.main import app

    with TestClient(app) as c:
        assert c.post("/preplan", json={"building_id": "nope"}).status_code == 404


def test_buildings_filters_and_search(sandbox):
    from agent.main import app

    with TestClient(app) as c:
        assert isinstance(c.get("/buildings").json(), list)
        assert c.get("/buildings?featured=true").json() == []
        assert c.get("/buildings?q=100 Test").json()[0]["building_id"] == "test-001"
        r = c.get("/buildings/search?q=100&limit=5").json()
        assert r["total"] == 1 and set(r["items"][0]) >= {"building_id", "address", "lat", "lng", "featured"}
        assert c.get("/buildings/search?q=zzz").json() == {"total": 0, "items": []}
