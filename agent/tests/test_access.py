"""Access geometry: edge extraction/selection and staging overlap validation (pure functions, no network)."""
from agent.tools import access

# 100 x 40 px rectangle, y down / north up. gsd 0.5 m/px -> 50 m x 20 m building.
RECT = [(100, 100), (300, 100), (300, 180), (100, 180)]
GSD = 0.25


def _edges():
    simp, edges = access.extract_edges(RECT, GSD)
    return simp, edges


def test_extract_edges_sides_and_normals():
    simp, edges = _edges()
    assert len(simp) == 4
    sides = sorted(e["side"] for e in edges)
    assert sides == ["E", "N", "S", "W"]
    south = next(e for e in edges if e["side"] == "S")
    assert south["normal"][1] > 0.99  # outward = image down = south
    assert abs(south["len_m"] - 50.0) < 0.5
    assert all(e["len_m"] >= access.MIN_EDGE_M for e in edges)


def test_extract_edges_simplifies_noisy_ring():
    noisy = [(100, 100), (200, 100.6), (300, 100), (300, 180), (200, 179.5), (100, 180), (100, 140.4)]
    simp, edges = access.extract_edges(noisy, GSD)
    assert len(simp) == 4 and len(edges) == 4


def test_select_edges_uses_vlm_decision_and_verification():
    _, edges = _edges()
    ids = {e["side"]: e["id"] for e in edges}
    ans = {"edges": [{"id": ids["S"], "accessible": True, "conf": 0.8, "reason": "drive aisle"},
                     {"id": ids["N"], "accessible": False, "conf": 0.7, "reason": "rail"},
                     {"id": ids["E"], "accessible": True, "conf": 0.6, "reason": "lot"}]}
    sel = access.select_edges(edges, ans)
    assert [e["side"] for e in sel] == ["S", "E"]
    ver = {"edges": [{"id": ids["S"], "ok": True}, {"id": ids["E"], "ok": False, "why": "fence"}]}
    sel = access.select_edges(edges, ans, ver)
    assert [e["side"] for e in sel] == ["S"]
    assert sel[0]["conf"] >= 0.8 and sel[0]["verified"] is True
    # geometry is the footprint edge itself, not a model bbox
    s = next(e for e in edges if e["side"] == "S")
    assert (sel[0]["a"], sel[0]["b"]) == (s["a"], s["b"])
    assert access.select_edges(edges, None) == []


def test_staging_outside_building_is_accepted():
    simp, edges = _edges()
    south = [e for e in edges if e["side"] == "S"]
    poly = [(150, 200), (250, 200), (250, 230), (150, 230)]  # 5-12.5 m south of the S wall
    v = access.validate_staging(poly, simp, south, GSD)
    assert v["ok"], v
    assert v["overlap_before"] == 0 and not v["clipped"]


def test_staging_overlapping_building_is_clipped_to_outside_of_wall():
    simp, edges = _edges()
    south = [e for e in edges if e["side"] == "S"]
    poly = [(150, 160), (250, 160), (250, 230), (150, 230)]  # starts inside the footprint
    assert access.overlap_frac(poly, simp) > 0.2
    v = access.validate_staging(poly, simp, south, GSD, south[0]["id"])
    assert v["ok"] and v["clipped"], v
    assert access.overlap_frac(v["poly"], simp) <= 0.02
    assert min(p[1] for p in v["poly"]) >= 180  # nothing left north of the wall


def test_staging_inside_building_is_rejected():
    simp, edges = _edges()
    south = [e for e in edges if e["side"] == "S"]
    poly = [(150, 110), (250, 110), (250, 170), (150, 170)]
    v = access.validate_staging(poly, simp, south, GSD, south[0]["id"])
    assert not v["ok"]


def test_staging_candidates_never_overlap_footprint():
    simp, edges = _edges()
    cands = access.staging_candidates(edges, simp, GSD)
    assert cands
    for c in cands:
        assert access.overlap_frac(c["poly"], simp) <= 0.02
    ranked = access.rank_staging(cands, {"cands": [
        {"label": cands[0]["label"], "surface": "building_or_roof", "clear": 0.9},
        {"label": cands[1]["label"], "surface": "drive_aisle", "clear": 0.9, "connected": True},
        {"label": cands[2]["label"], "surface": "open_paved_lot", "clear": 0.5}]})
    assert [r["label"] for r in ranked] == [cands[1]["label"]]


def test_oblique_projection_roundtrip():
    meta = {"direction": "W", "width": 1700, "height": 1300, "extent_m": 120}
    x, y = access.obl_project(meta, 12.0, -7.0)
    e, n = access.obl_unproject(meta, x, y)
    assert abs(e - 12.0) < 1e-6 and abs(n + 7.0) < 1e-6
