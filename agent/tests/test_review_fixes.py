"""Regression tests for the demo-screenshot review fixes (punctuation, construction, merged hazards,
access wall consolidation, notify flag, concise roof access)."""
import json

from agent.plan_builder import (V, building_section, concise_field, finalize, interior_section, join_text, no_dash,
                                top_hazards, top_hazards_detail, voice_brief)
from agent.tools import access
from agent.tools.hazard_rules import combine_locations, match_hazards, merge_hazards
from agent.tools.validator import VERIFY

from .test_api import _events


# ---------------------------------------------------------------- 1. punctuation
def test_join_never_produces_punctuation_artifacts():
    assert join_text("so confidence is low.", "First Floor Lobby and Kitchen", "Floor 1") == \
        "so confidence is low. First Floor Lobby and Kitchen, Floor 1"
    assert join_text("a,", "", None, "b ,") == "a, b"
    for s in ("low., First", "a,, b", "a , b", "low — First", "x.,, y"):
        out = no_dash(s)
        assert ".," not in out and ",," not in out and " ," not in out, out


def test_matterport_finding_value_has_separate_location():
    mp = {"model": {"model_id": "m1", "rooms": [], "mattertags": []},
          "pano_analyses": [{"sweep_id": "s1", "scan": "First Floor Lobby and Kitchen", "floor": 1, "model_id": "m1",
                             "result": {"findings": {"alarm_panel": {
                                 "value": "Red wall-mounted box. It could be a fire alarm panel, so confidence is low.",
                                 "conf": 0.4}}}}]}
    fld = interior_section(mp)["fire_protection"]["alarm_panel"]
    assert ".," not in fld["value"] and ",," not in fld["value"] and " ," not in fld["value"]
    assert fld["value"].endswith("Location: First Floor Lobby and Kitchen, Floor 1")
    assert fld["location"] == "First Floor Lobby and Kitchen, Floor 1"


# ---------------------------------------------------------------- 2. construction
def test_construction_never_inferred_from_year():
    prop = {"costar_id": "C1", "year_built": 2021, "stories": 5, "property_type": "Office", "cite": {"id": "C1"}}
    b = building_section({"building_id": "hou-001"}, {"property": prop}, {"findings": {}})
    assert b["construction"]["value"] == VERIFY
    # an LLM/legacy plan carrying an era-inferred construction is downgraded on finalize
    plan = {"building": {"construction": {"value": "Possible lightweight/engineered components (era-inferred)",
                                          "cite": {"src": "inference", "id": "era-construction", "conf": 0.4,
                                                   "from": ["costar.year_built"]}}},
            "hazards": [{"type": "Possible lightweight engineered wood/truss construction", "location": "Building-wide",
                         "conf": 0.45, "cite": {"src": "inference", "id": "llm:lw", "conf": 0.45, "from": ["costar.year_built"]}}]}
    p = finalize(plan)["plan"]
    assert p["building"]["construction"]["value"] == VERIFY
    assert not p["hazards"] or not any("lightweight" in h["type"].lower() for h in p["hazards"])
    # CoStar construction is kept
    prop2 = {**prop, "construction": "Reinforced Concrete"}
    assert building_section({}, {"property": prop2}, {"findings": {}})["construction"]["value"] == "Reinforced Concrete"


def test_lightweight_hazard_needs_cited_construction_evidence():
    ids = lambda r: {h["rule"] for h in r["hazards"]}
    door = [{"text": "steel door frame and window frame in lobby", "sweep_id": "s1"}]
    assert "era_lightweight" not in ids(match_hazards([], 2022, interior=door))
    hit = match_hazards([], 2022, interior=[{"text": "exposed wood truss ceiling", "sweep_id": "s9"}])
    h = next(h for h in hit["hazards"] if h["rule"] == "era_lightweight")
    assert "matterport:s9" in h["cite"]["from"]
    h2 = next(h for h in match_hazards([], 2022, construction="Wood frame")["hazards"] if h["rule"] == "era_lightweight")
    assert "costar.construction" in h2["cite"]["from"]


# ---------------------------------------------------------------- 3. merged hazards
def _tenants():
    c = lambda i: {"src": "costar", "id": i, "conf": 0.9}
    return [{"name": "Cafe Ion", "use": "Restaurant", "floor": 1, "suite": "110", "cite": c("t1")},
            {"name": "The Lymbar", "use": "Restaurant", "floor": 1, "suite": "130", "cite": c("t2")},
            {"name": "Late August", "use": "Restaurant", "floor": 1, "cite": c("t3")}]


def test_same_rule_hazards_merge_into_one():
    hz = match_hazards(_tenants())["hazards"]
    cook = [h for h in hz if h["rule"] == "restaurant_cooking"]
    assert len(cook) == 1
    h = cook[0]
    assert h["tenants"] == ["Cafe Ion", "The Lymbar", "Late August"]
    assert h["basis"] == "tenants Cafe Ion, The Lymbar, Late August"
    assert h["location"] == "Floor 1, incl. suites 110, 130"
    assert {"costar:t1", "costar:t2", "costar:t3"} <= set(h["cite"]["from"])
    assert merge_hazards(hz) == hz  # idempotent
    assert combine_locations(["Floor 1, suite 110", "Floor 1, suite 130"]) == "Floor 1, suites 110, 130"
    assert combine_locations(["Floor 2", "Floor 4"]) == "Floors 2, 4"


def test_plan_outputs_use_distinct_hazards():
    dup = [{"type": "Cooking oil, gas lines, hood systems", "location": f"Floor 1, suite {s}", "tenant": n, "conf": 0.65,
            "cite": {"src": "inference", "id": "rule:restaurant_cooking", "conf": 0.65, "from": [f"costar:{n}"]}}
           for n, s in (("A", 110), ("B", 130), ("C", 140))]
    other = {"type": "Lithium-ion battery packs", "location": "Floor 1", "tenant": "D", "conf": 0.6,
             "cite": {"src": "inference", "id": "rule:li", "conf": 0.6, "from": ["costar:D"]}}
    plan = {"building": {}, "hazards": dup + [other]}
    th = top_hazards(plan)
    assert len(th) == 2 and sum("Cooking oil" in t for t in th) == 1
    assert top_hazards_detail(plan)[0]["basis"] == "tenants A, B, C"
    vb = voice_brief(plan)
    assert vb.lower().count("cooking oil") == 1 and "Tenants A, B and 1 more" in vb
    p = finalize(plan)["plan"]
    assert len(p["hazards"]) == 2


# ---------------------------------------------------------------- 4. access walls
def _e(i, side, a, b, conf=0.7, gsd=0.1):
    import math
    return {"id": i, "side": side, "px": [a, b], "len_m": round(math.hypot(b[0] - a[0], b[1] - a[1]) * gsd, 1),
            "conf": conf, "adjacent": "sidewalk then street to north", "clear_width_ft": 40}


def test_consolidate_merges_collinear_and_caps():
    gsd = 0.1
    edges = [_e(1, "N", [0, 0], [80, 1]), _e(2, "N", [85, 1], [200, 2]),   # collinear, 0.5 m gap -> one 20 m wall
             _e(3, "N", [0, 60], [60, 60]),                                  # 6 m: below 10 m
             _e(4, "E", [300, 0], [300, 200]), _e(5, "S", [0, 400], [300, 400]),
             _e(6, "W", [-100, 0], [-100, 150]), _e(7, "SE", [400, 400], [400, 520])]
    shown, merged = access.consolidate_edges(edges, gsd)
    n = next(e for e in merged if e["side"] == "N" and e["len_m"] > 15)
    assert sorted(n["merged_ids"]) == [1, 2] and 19 <= n["len_m"] <= 21
    assert len(shown) <= 4 and all(e["len_m"] >= 10 for e in shown)
    assert shown[0]["side"] == "S"  # 30 m x 0.7 ranks first
    ra = access.roof_access_text(shown, ["NE (neighboring building)"], 87.0, merged)
    assert ra["value"].startswith("High-rise (~87 m)") and ra["value"].count(" side from ") <= 3
    assert ra["detail"] and len(ra["value"].split()) <= 45


def test_cached_access_consolidation_real_buildings():
    from agent import config
    for bid, want in (("la-002", {"SW", "NW"}), ("la-003", None)):
        f = config.CACHE_DIR / "vexcel" / bid / "access.json"
        if not f.exists():
            continue
        r = access.apply_consolidation(json.loads(f.read_text()))
        assert len(r["edges"]) <= 4 and r["edges_all"]
        assert all(e["len_m"] >= 10 for e in r["edges"])
        if want:
            assert want <= {e["side"] for e in r["edges"]}
        if bid == "la-003":
            assert len(r["roof_access"]["value"].split()) <= 45 and r["roof_access"]["high_rise"]


# ---------------------------------------------------------------- 6. concise roof access
def test_long_roof_access_value_is_condensed():
    long = ("Best ladder/aerial placement is on the south side, from the wide arterial street frontage. "
            "The sidewalk and landscaping strip is between the street and the building. "
            "The west side street also offers access along the west face. Roof access hatches are not clearly visible.")
    f = concise_field({"value": long, "cite": {"src": "vexcel", "id": "t"}}, with_short=True)
    assert f["detail"] == long and f["short"]
    assert len([s for s in f["value"].split(". ") if s]) <= 2 and len(f["value"]) < len(long)
    assert concise_field(dict(V)) == V


# ---------------------------------------------------------------- 5. notify flag
def test_preplan_notify_false_skips_photon(sandbox, monkeypatch):
    from fastapi.testclient import TestClient

    from agent import runs
    from agent.main import app

    calls = []
    monkeypatch.setattr(runs, "notify_photon", lambda run_id, plan: calls.append(run_id))
    with TestClient(app) as c:
        r = c.post("/preplan", json={"building_id": "test-001", "notify": False}).json()
        assert r["notify"] is False
        _events(c, r["run_id"], "interrupt")
        assert calls == []
        r2 = c.post("/preplan", json={"building_id": "test-001"}).json()
        _events(c, r2["run_id"], "interrupt")
        assert calls == [r2["run_id"]]
