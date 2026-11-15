from agent.tools.hazard_rules import match_hazards


def types(r):
    return {h["rule"] for h in r["hazards"]}


def test_pool_supply_chlorine():
    r = match_hazards([{"name": "Leslie's Pool Supplies", "use": "Pool supply", "floor": 1, "cite": {"src": "costar", "id": "T1"}}], None, None)
    h = r["hazards"][0]
    assert h["rule"] == "chlorine_oxidizers" and h["location"] == "Floor 1"
    assert h["cite"]["src"] == "inference" and "costar.tenants[0]" in h["cite"]["from"] and "costar:T1" in h["cite"]["from"]


def test_naics_and_sic():
    assert "flammable_liquids_auto" in types(match_hazards([{"name": "Joe's", "naics": "811111"}]))
    assert "restaurant_cooking" in types(match_hazards([{"name": "X LLC", "sic": "5812"}]))
    assert "datacenter_telecom" in types(match_hazards([{"name": "Equinix", "use": "Data center colocation"}]))
    assert "lithium_ion" in types(match_hazards([{"name": "Rad Power", "use": "E-bike retail"}]))


def test_era_and_roof():
    t = types(match_hazards([], 1978, "Flat roof, open web steel joist, metal deck"))
    assert {"era_asbestos", "roof_truss_collapse"} <= t
    # modern lightweight rule needs construction evidence, never year alone / concrete / redeveloped
    assert "era_lightweight" not in types(match_hazards([], 1995))
    assert "era_lightweight" in types(match_hazards([], 1995, construction="Wood frame over podium"))
    assert "era_lightweight" not in types(match_hazards([], 2021, construction="Reinforced concrete"))
    assert not match_hazards([], None, None)["hazards"]


def test_no_false_positive_short_keywords():
    # "lab" must not match "Labor Ready"? -> it is a word match on 'lab' only
    assert "lab_chemicals" not in types(match_hazards([{"name": "Collaboration Partners", "use": "Consulting"}]))


def test_every_hazard_has_from():
    r = match_hazards([{"name": "Furniture Warehouse"}, {"name": "Pizza Hut"}], 1965, "barrel truss roof")
    assert r["hazards"] and all(h["cite"]["from"] for h in r["hazards"])


def test_restaurant_rule_needs_native_use_not_description_keywords():
    gi = {"name": "Global Importing Group", "use": "Wholesaler (industrial space); coffee, distribution",
          "industry": "Wholesaler", "cite": {"src": "costar", "id": "1"}}
    assert "restaurant_cooking" not in types(match_hazards([gi]))
    cafe = {"name": "Blue Bottle", "use": "Coffee shop (retail)", "industry": "Food Service"}
    assert "restaurant_cooking" in types(match_hazards([cafe]))
    lymbar = {"name": "The Lymbar", "use": "Restaurant/bar", "industry": "Restaurants"}
    assert "restaurant_cooking" in types(match_hazards([lymbar]))

    cleaner = {"name": "Coconut Cleaning", "use": "Accommodation & Food Services (industrial space)",
               "industry": "Accommodation & Food Services"}
    assert "restaurant_cooking" not in types(match_hazards([cleaner]))
