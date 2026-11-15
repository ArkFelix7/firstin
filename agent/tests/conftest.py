import json
import os

import pytest

os.environ["FIRSTIN_OFFLINE"] = "1"
os.environ["FIRSTIN_PACE"] = "0"
os.environ["PHOTON_URL"] = "off"
os.environ["FIRSTIN_SAVE_REPLAY"] = "0"


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Isolated registry + out dir + stubbed data tools (works with or without real caches)."""
    from agent import config
    from agent.tools import sources

    reg = tmp_path / "buildings.json"
    reg.write_text(json.dumps([{"building_id": "test-001", "address": "100 Test St, Houston, TX", "city": "Houston",
                                "lat": 29.7, "lng": -95.3, "costar_id": "CS-1", "matterport_model_ids": ["m1"],
                                "has": {"costar": True, "vexcel": True, "matterport": True}}]))
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(config, "REGISTRY_PATH", reg)
    monkeypatch.setattr(config, "OUT_DIR", out)
    cite = lambda i: {"src": "costar", "id": i, "conf": 0.95}
    monkeypatch.setattr(sources, "costar_property", lambda building_id: {
        "costar_id": "CS-1", "address": "100 Test St", "year_built": 1978, "stories": 4, "rba_sqft": 62000,
        "building_class": "B", "property_type": "Office", "cite": cite("CS-1")})
    monkeypatch.setattr(sources, "costar_tenants", lambda building_id: {"tenants": [
        {"name": "Leslie's Pool Supplies", "use": "Pool supply distribution", "floor": 1, "cite": cite("T-1")},
        {"name": "Acme Law", "use": "Legal office", "floor": 3, "cite": cite("T-2")}], "cite": cite("CS-1")})
    monkeypatch.setattr(sources, "vexcel_tile", lambda building_id, view="ortho": {"error": "stub: no tile"})
    monkeypatch.setattr(sources, "matterport_model", lambda building_id: {
        "model_id": "m1", "rooms": [{"label": "North Stairwell", "floor": 1, "id": "r1"},
                                    {"label": "South Stairwell", "floor": 1, "id": "r2"},
                                    {"label": "Electrical Room", "floor": 1, "id": "r3"},
                                    {"label": "Elevator", "floor": 1, "id": "r4"}],
        "mattertags": [{"label": "Fire Alarm Panel", "floor": 1, "id": "tag1"}], "floors": [1], "sweep_count": 40,
        "cite": {"src": "matterport", "id": "m1"}})
    monkeypatch.setattr(sources, "matterport_panoramas", lambda building_id, room_filter=None, limit=6: {"panos": []})
    return tmp_path
