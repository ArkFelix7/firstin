"""Pre-compute VLM answers for every demo building so the OFFLINE demo replays real vision.

Usage (needs ANTHROPIC_API_KEY in .env):  make warm-vision   [ONLY=la-002]
Uses the exact canonical questions + image choices the pipeline uses, so cache keys match.
"""
import argparse
import sys

from agent import config
from agent.pipeline import pick_panos
from agent.tools import registry, sources, vision


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--panos", type=int, default=4)
    a = ap.parse_args()
    if not config.has_api_key():
        sys.exit("ANTHROPIC_API_KEY is empty - add it to .env first")
    for b in registry.list_buildings():
        bid = b["building_id"]
        if a.only and bid not in a.only.split(","):
            continue
        t = sources.vexcel_tile(bid, "ortho")
        if t.get("image_path"):
            r = vision.analyze_aerial_image(t["image_path"], t.get("preview_path"), t.get("preview_scale"))
            print(bid, "ortho", "cached" if r.get("cached") else "NEW", r.get("error") or r.get("answer"))
        ob = sources.vexcel_oblique(bid, "N")
        if ob.get("image_path"):
            r = vision.analyze_aerial_image(ob["image_path"], shows_facade=ob.get("shows_facade"))
            print(bid, "oblique_N", r.get("error") or r.get("answer"))
        panos = (sources.matterport_panoramas(bid, None, 12) or {}).get("panos") or []
        for p in pick_panos(panos, a.panos):
            r = vision.analyze_interior_image(p["image_path"])
            print(bid, "pano", p.get("room"), r.get("error") or r.get("answer"))


if __name__ == "__main__":
    main()
