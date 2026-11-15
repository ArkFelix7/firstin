from agent.plan_builder import roof_access_short, short_clause, voice_brief

LA003 = ("Aerial or ladder access is only practical from the street frontage on the north/northwest, where the tower "
         "meets the intersection and the wide east-west boulevard. Because of the building height, rooftop access is "
         "realistically by internal stairs or by helicopter at the marked helipad.")


def _plan(roof_value, short=None, hazards=()):
    node = {"value": roof_value, "cite": {"src": "vexcel", "id": "t", "conf": 0.5}}
    if short:
        node["short"] = short
    return {"building": {"stories": {"value": 24, "cite": {"src": "costar", "id": "1"}}},
            "access": {"roof_access": node}, "hazards": list(hazards)}


def test_la003_never_mid_word():
    s = short_clause(LA003)
    assert s == "street frontage on the north/northwest"
    assert not s.startswith("ly")
    for w in s.split():
        assert w in LA003  # only whole words from the source


def test_other_real_strings():
    assert short_clause("Best access is from the southwest long side, where a paved drive aisle runs") == "southwest long side"
    assert short_clause("Best ladder/aerial placement is on the south side, from the wide arterial street frontage.") == "south side"
    assert short_clause("Best ladder or aerial placement is the southeast side along the wide street, which has") == \
        "southeast side along the wide street"


def test_ladders_placed_phrase():
    assert short_clause("Ladders or aerials can be placed on the southeast side, which faces the paved drive aisle") == "southeast side"


def test_prefers_llm_short_form_and_brief_uses_it():
    p = _plan(LA003, short="north/northwest street frontage")
    assert roof_access_short(p) == "north/northwest street frontage"
    p = _plan(LA003, hazards=[{"type": "Rooftop solar array", "cite": {"src": "inference", "id": "rule:x", "from": ["a"]}}])
    assert roof_access_short(p) == "street frontage on the north/northwest; solar PV on roof"
    b = voice_brief(_plan(LA003))
    assert "Roof access: street frontage on the north/northwest." in b
    assert len(b.split()) <= 60


def test_no_em_dashes():
    from agent.plan_builder import no_dash, top_hazards, top_hazards_detail
    assert no_dash("Utility room — Floor 1") == "Utility room, Floor 1"
    assert no_dash({"a": ["x—y"], "cite": {"id": "keep—id"}}) == {"a": ["x-y"], "cite": {"id": "keep—id"}}
    p = {"hazards": [{"type": "Rooftop solar array", "location": "Roof", "conf": 0.7},
                     {"type": "Asbestos", "location": "Building-wide", "conf": 0.6}]}
    assert top_hazards(p) == ["Rooftop solar array (Roof)", "Asbestos"]
    assert top_hazards_detail(p)[0] == {"type": "Rooftop solar array", "location": "Roof", "conf": 0.7}
    p2 = _plan(LA003 + " — extra")
    p2["exposures"] = [{"side": "S", "desc": "commercial building — tall", "gap_m": 19.5, "cite": {"src": "vexcel", "id": "x"}}]
    b = voice_brief(p2)
    assert "—" not in b and "Exposure south: commercial building, 64 feet" in b


def test_construction_short():
    from agent.plan_builder import construction_short
    assert construction_short("Concrete tilt-up (CoStar material: Masonry)") == "Concrete tilt-up"
    assert construction_short("Steel") == "Steel"
    assert construction_short(None) is None
