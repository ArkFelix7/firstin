from agent.tools.validator import VERIFY, validate_plan


def test_cited_fields_pass():
    plan = {"building": {"address": "x", "stories": {"value": 4, "cite": {"src": "costar", "id": "1", "conf": 0.9}}}}
    r = validate_plan(plan)
    assert r["ok"] and r["plan"]["building"]["stories"]["value"] == 4


def test_uncited_field_downgraded():
    plan = {"building": {"stories": {"value": 4, "cite": None}},
            "access": {"roof_access": {"value": "North alley", "cite": {"src": "vexcel"}}}}  # no id
    r = validate_plan(plan)
    assert not r["ok"]
    assert r["plan"]["building"]["stories"]["value"] == VERIFY
    assert r["plan"]["access"]["roof_access"] == {"value": VERIFY, "cite": None, "unverified": "North alley"}
    assert "building.stories" in r["verify_on_site"]


def test_inference_requires_from():
    bad = {"building": {"construction": {"value": "Steel", "cite": {"src": "inference", "conf": 0.6}}}}
    good = {"building": {"construction": {"value": "Steel", "cite": {"src": "inference", "conf": 0.6, "from": ["costar.year_built"]}}}}
    assert validate_plan(bad)["plan"]["building"]["construction"]["value"] == VERIFY
    assert validate_plan(good)["ok"]


def test_bad_src_and_conf():
    for c in ({"src": "wikipedia", "id": "x"}, {"src": "costar", "id": "x", "conf": 1.5}):
        assert validate_plan({"access": {"staging": {"value": "lot", "cite": c}}})["plan"]["access"]["staging"]["value"] == VERIFY


def test_bare_scalars_and_verify_strings():
    plan = {"interior": {"fire_protection": {"fdc": "VERIFY ON SITE", "alarm_panel": "Lobby"}}}
    r = validate_plan(plan)
    fp = r["plan"]["interior"]["fire_protection"]
    assert fp["fdc"] == {"value": VERIFY, "cite": None}
    assert fp["alarm_panel"]["value"] == VERIFY and fp["alarm_panel"]["unverified"] == "Lobby"


def test_list_items_flagged_not_dropped():
    plan = {"hazards": [{"type": "Chlorine", "cite": None},
                        {"type": "Asbestos", "cite": {"src": "inference", "id": "rule:x", "from": ["costar.year_built"]}}]}
    r = validate_plan(plan)
    hz = r["plan"]["hazards"]
    assert hz[0]["verify_on_site"] is True and hz[0]["cite"] is None
    assert "verify_on_site" not in hz[1]


def test_every_leaf_cited_or_verify():
    from agent.plan_builder import build_plan
    plan = build_plan("p", {"building_id": "b", "address": "a"}, {})  # no evidence at all
    r = validate_plan(plan)
    assert r["ok"]
    b = r["plan"]["building"]
    for k in ("stories", "year_built", "sq_ft", "construction"):
        assert b[k]["value"] == VERIFY
