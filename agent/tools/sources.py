"""Safe adapters over the data-source tool modules (some are written by teammates).

Every function returns a JSON-serializable dict and never raises; a missing module or
function yields {"error": ...} so the pipeline degrades to VERIFY ON SITE.
"""
from __future__ import annotations

import importlib
import traceback
from typing import Any


def _call(module: str, fn: str, *args, **kwargs) -> Any:
    try:
        mod = importlib.import_module(f"{__package__}.{module}")
    except Exception as e:  # noqa: BLE001
        return {"error": f"tools.{module} unavailable: {type(e).__name__}: {e}"}
    f = getattr(mod, fn, None)
    if f is None:
        return {"error": f"tools.{module}.{fn} not implemented"}
    try:
        res = f(*args, **kwargs)
        return res if isinstance(res, dict) else {"result": res}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{module}.{fn} failed: {type(e).__name__}: {e}", "trace": traceback.format_exc(limit=2)}


def costar_property(building_id: str) -> dict:
    return _call("costar", "costar_property", building_id)


def costar_tenants(building_id: str) -> dict:
    return _call("costar", "costar_tenants", building_id)


def vexcel_tile(building_id: str, view: str = "ortho") -> dict:
    return _call("vexcel", "vexcel_tile", building_id, view)


def vexcel_oblique(building_id: str, direction: str = "N") -> dict:
    return _call("vexcel", "vexcel_oblique", building_id, direction)


def matterport_model(building_id: str) -> dict:
    return _call("matterport", "matterport_model", building_id)


def matterport_panoramas(building_id: str, room_filter: str | None = None, limit: int = 6) -> dict:
    return _call("matterport", "matterport_panoramas", building_id, room_filter, limit)


def vexcel_roof(building_id: str) -> dict:
    return _call("vexcel", "vexcel_roof", building_id)


def vexcel_footprint(building_id: str) -> dict:
    return _call("vexcel", "vexcel_footprint", building_id)
