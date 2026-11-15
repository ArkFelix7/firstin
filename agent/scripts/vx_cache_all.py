"""Cache all Vexcel assets for every building in agent/cache/buildings.json.

Per building -> agent/cache/vexcel/<building_id>/:
  ortho.jpg (+_1600 preview, .json georef)     ~120 m x 120 m, native ~6-7 cm GSD
  context.jpg (+_1600, .json)                  ~300 m x 300 m for hydrants / exposures / staging
  oblique_{N,E,S,W}.jpg (+.json)                45-degree views (oblique_S shows the NORTH facade, etc.)
  roof.json + property_raw.json                 AI roof/structure attributes, DSM height, exposures
  footprint.json                                footprint polygon in lat/lng + pixel coords on ortho/context
  ortho_annotated.jpg                           ortho preview with target footprint (red) + exposures (orange)
Plus agent/cache/vexcel/index.json summary.

Usage (from firstin/):
  uv run --python 3.12 --with httpx --with python-dotenv --with pillow python agent/scripts/vx_cache_all.py
     [--only la-001] [--force]  [--watch 20]   (--watch N: re-poll buildings.json every 60s for N minutes)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.tools import vexcel as vx  # noqa: E402


def annotate(bid: str, tile: dict, fp: dict, roof: dict) -> str | None:
    try:
        from PIL import Image, ImageDraw

        im = Image.open(tile["preview_path"]).convert("RGB")
        s = tile["preview_scale"]
        dr = ImageDraw.Draw(im)
        g = tile["georef"]
        for e in roof.get("exposures", []):
            c = e.get("roof_centroid")
            if c:
                p = vx.latlng_to_px(g, c["lat"], c["lng"])
                x, y = p["x"] * s, p["y"] * s
                dr.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(255, 140, 0), width=4)
                dr.text((x + 12, y - 8), f"{e['side']} {e['gap_m']}m", fill=(255, 140, 0))
        poly = fp.get("on_images", {}).get("ortho", {}).get("polygon_px")
        if poly:
            dr.polygon([(x * s, y * s) for x, y in poly], outline=(255, 0, 0), width=4)
        out = Path(tile["image_path"]).parent / "ortho_annotated.jpg"
        im.save(out, "JPEG", quality=88)
        return str(out)
    except Exception as e:
        print("  annotate failed:", e)
        return None


def cache_building(b: dict) -> dict:
    bid = b["building_id"]
    t0 = time.time()
    rb = vx._resolve(bid)
    if "error" in rb:
        return {"building_id": bid, "error": rb["error"]}
    summary = {"building_id": bid, "address": b.get("address"), "lat": rb["lat"], "lng": rb["lng"],
               "coord_source": rb.get("coord_source")}
    for view in ("ortho", "context"):
        r = vx.vexcel_tile(bid, view)
        summary[view] = r.get("error") or {"url": r["image_url"], "tile_id": r["tile_id"], "gsd_m": r["gsd_m"],
                                           "captured_at": r["captured_at"]}
    for d in "NESW":
        r = vx.vexcel_oblique(bid, d)
        summary[f"oblique_{d}"] = r.get("error") or {"url": r["image_url"], "image": r["tile_id"],
                                                     "captured_at": r["captured_at"]}
    roof = vx.vexcel_roof(bid)
    if "error" in roof:
        summary["roof"] = roof["error"]
    else:
        t = roof["target"]
        summary["roof"] = {k: t.get(k) for k in ("roof_material", "roof_shape", "roof_condition_label",
                                                 "building_type", "footprint_area_m2", "height_est_m",
                                                 "stories_est", "distance_to_point_m")}
        summary["exposures"] = [f"{e['side']} {e['gap_m']}m ({e['building_type']})" for e in roof["exposures"][:6]]
    fp = vx.vexcel_footprint(bid)
    if "error" not in fp:
        (vx.VX_CACHE / vx._safe_id(bid) / "footprint.json").write_text(json.dumps(fp, indent=2))
        tile = vx.vexcel_tile(bid, "ortho")
        if "error" not in tile and "error" not in roof:
            a = annotate(bid, tile, fp, roof)
            if a:
                summary["annotated_url"] = vx._url(bid, "ortho_annotated.jpg")
    summary["secs"] = round(time.time() - t0, 1)
    return summary


def load_buildings() -> list[dict]:
    try:
        data = json.loads(vx.BUILDINGS_JSON.read_text())
        return data.get("buildings", []) if isinstance(data, dict) else data
    except Exception:
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated building_ids")
    ap.add_argument("--force", action="store_true", help="refetch live even if cached (FIRSTIN_LIVE=1)")
    ap.add_argument("--watch", type=float, default=0, help="keep polling buildings.json for N minutes")
    a = ap.parse_args()
    if a.force:
        os.environ["FIRSTIN_LIVE"] = "1"
    orig_live = os.environ.get("FIRSTIN_LIVE")
    idx_path = vx.VX_CACHE / "index.json"
    try:
        index = json.loads(idx_path.read_text())
    except Exception:
        index = {}
    done_sig: dict[str, str] = {}
    deadline = time.time() + a.watch * 60
    while True:
        for b in load_buildings():
            bid = b.get("building_id")
            if not bid or (a.only and bid not in a.only.split(",")):
                continue
            rb = vx._resolve(bid)
            sig = f"{rb.get('lat')},{rb.get('lng')}"
            if done_sig.get(bid) == sig:
                continue
            # coordinates changed since last cache -> refetch
            print(f"[vx] caching {bid} {b.get('address')}", flush=True)
            s = cache_building(b)
            if orig_live is None:
                os.environ.pop("FIRSTIN_LIVE", None)
            else:
                os.environ["FIRSTIN_LIVE"] = orig_live
            print(json.dumps(s, indent=1), flush=True)
            index[bid] = s
            done_sig[bid] = sig
            idx_path.write_text(json.dumps(index, indent=2))
        if time.time() >= deadline:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
