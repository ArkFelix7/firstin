"""Pre-cache Matterport + Vexcel + CoStar for curated registry buildings, then mark them cached+featured.

Usage (from firstin/): agent/.venv/bin/python -m agent.scripts.registry_precache costar-275988 costar-363919 ...
Then: agent/.venv/bin/python -m agent.scripts.warm_vision --only <ids comma-separated>
"""
import json
import os
import sys
import time

from agent import config
from agent.scripts import registry_build, vx_cache_all
from agent.scripts import mp_cache
from agent.tools import costar, registry


def main():
    ids = sys.argv[1:]
    cap = int(os.environ.get("FIRSTIN_MP_MAX_MODELS_CURATED", "10"))
    for bid in ids:
        b = registry.get_building(bid)
        if not b:
            print(bid, "not in registry"); continue
        t0 = time.time()
        mdir = config.CACHE_DIR / "matterport" / bid
        if not (mdir / "model.json").exists() or len(json.loads((mdir / "model.json").read_text())["models"]) < min(cap, len(b["matterport_model_ids"])):
            mp_cache.cache_building({"building_id": bid, "address": b["address"], "city": b["city"], "name": b["name"],
                                     "model_ids": b["matterport_model_ids"][:cap]})
        t1 = time.time()
        vx = vx_cache_all.cache_building(b)
        t2 = time.time()
        cs = costar.build_cache([bid])
        print(json.dumps({"building_id": bid, "mp_s": round(t1 - t0, 1), "vx_s": round(t2 - t1, 1),
                          "roof": vx.get("roof"), "coord_source": vx.get("coord_source"), "costar": cs.get(bid)},
                         default=str), flush=True)
    reg = json.loads(registry_build.REG.read_text())
    for b in reg:
        if b["building_id"] in ids:
            b["cached"] = True
            b["featured"] = True
    registry_build.REG.write_text(json.dumps(reg))
    print(registry_build.build())


if __name__ == "__main__":
    main()
