"""Cache Matterport data for the demo buildings.

Usage: python -m agent.scripts.mp_cache [building_id ...]
Writes agent/cache/matterport/<building_id>/{model.json, panos.json, *.jpg} and agent/cache/buildings.json.
"""
import io, json, re, sys, time, urllib.parse
import httpx
from PIL import Image
from agent.scripts.mp_gql import gql, ROOT
from agent.scripts.mp_skybox import skybox_to_equirect

CACHE = ROOT / "agent/cache/matterport"

# Demo picks (see agent/cache/matterport/DEMO_PICKS.md for scoring rationale)
PICKS = [
    {"building_id": "hou-001", "address": "4201 Main St, Houston, TX 77002", "city": "Houston",
     "name": "The Ion (Industrious Houston, 2nd floor)", "model_ids": ["CHUheq99ibg"]},
    {"building_id": "hou-002", "address": "2520 Washington Ave, Houston, TX 77007", "city": "Houston",
     "name": "Modera Washington (mixed-use: lobby, co-working, fitness, units)", "model_prefix": "Modera Washington",
     "street": "2520 washington ave"},
    {"building_id": "la-001", "address": "337 S Broadway, Los Angeles, CA 90013", "city": "Los Angeles",
     "name": "337 S Broadway Office/Retail (45,726 SF)", "model_ids": ["6FNMVoyPrL1"]},
    {"building_id": "la-002", "address": "1601 Perrino Pl, Los Angeles, CA 90023", "city": "Los Angeles",
     "name": "1601 Perrino Pl (warehouse + 2-story office suite)", "street": "1601 perrino pl"},
    {"building_id": "la-003", "address": "10940 Wilshire Blvd, Los Angeles, CA 90024", "city": "Los Angeles",
     "name": "The Tower, 10940 Wilshire Blvd (high-rise office)", "model_prefix": "The Tower", "street": "10940 wilshire blvd"},
]

PANOS_PER_BUILDING = 12
# room tag priority for firefighter-relevant panoramas (lower = more important)
PRIORITY = {"staircase": 0, "stairs": 0, "utility": 1, "basement": 1, "garage": 1, "laundry": 2, "entrance": 2,
            "foyer": 2, "lobby": 2, "hallway": 3, "corridor": 3, "kitchen": 3, "storage": 4, "closet": 5,
            "office": 6, "other": 7, "unfurnished": 7}

MODEL_Q = """query($id:ID!){ model(id:$id){
  id name created description
  address { address locality administrativeArea postalCode }
  geolocation { lat long }
  dimensions(units: imperial) { areaFloor areaFloorIndoor height }
  image { url }
  floors { id label sequence dimensions(units: imperial) { areaFloor } }
  rooms { id label tags keywords floor { id sequence label }
          classifications { label confidence }
          dimensions(units: imperial) { areaFloor width depth height }
          boundary { edges { vertices { position { x y } } openings { type } } } }
  mattertags { id label description keywords floor { sequence } anchorPosition { x y z } mediaType media enabled }
  locations { id label floor { sequence } position { x y z } room { id } neighbors pano { id } }
  assets { floorplans(formats: ["jpg"]) { url format flags floor { sequence } width height } }
} }"""

SKY_Q = """query($id:ID!, $ids:[String!]){ model(id:$id){ panoLocations(ids:$ids) { id label
  skybox(resolution: "2k") { children } } } }"""


def floor_hint(name):
    """Infer the building floor of a scan from its name (e.g. 'Suite 1050' -> 10, '2nd Floor' -> 2)."""
    n = name or ""
    m = re.search(r"(\d+)(?:st|nd|rd|th)\s+Floor", n, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"Suite\s+(\d{3,4})", n, re.I)
    if m:
        return int(m.group(1)) // 100
    if re.search(r"second floor", n, re.I):
        return 2
    if re.search(r"first floor|lobby", n, re.I):
        return 1
    return None


def resolve_models(p):
    if p.get("model_ids"):
        return p["model_ids"]
    idx = json.load(open(ROOT / "agent/data/matterport_index.json"))["models"]
    out = []
    for m in idx:
        st = (m.get("street") or m.get("address") or "").split(",")[0].strip().lower()
        if st != p["street"]:
            continue
        if p.get("model_prefix") and not (m["name"] or "").startswith(p["model_prefix"]):
            continue
        out.append(m["id"])
    return out


def room_bounds(r):
    pts = [v["position"] for e in ((r.get("boundary") or {}).get("edges") or []) for v in (e.get("vertices") or [])]
    if not pts:
        return None
    xs, ys = [p["x"] for p in pts], [p["y"] for p in pts]
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]


def room_name(r):
    if r.get("label"):
        return r["label"]
    tags = [t for t in (r.get("tags") or []) if t]
    return tags[0] if tags else "unlabeled"


def fetch_model(mid):
    d = gql(MODEL_Q, {"id": mid})
    if not d.get("data") or not d["data"].get("model"):
        raise RuntimeError(f"model {mid}: {d.get('errors')}")
    m = d["data"]["model"]
    floors = [{"id": f["id"], "label": f.get("label"), "sequence": f["sequence"],
               "area_sqft": round(((f.get("dimensions") or {}).get("areaFloor") or 0), 1)} for f in m.get("floors") or []]
    rooms = []
    for r in m.get("rooms") or []:
        if "nonArea" in (r.get("keywords") or []):
            continue  # voids / hidden geometry
        dims = r.get("dimensions") or {}
        doors = sum(1 for e in ((r.get("boundary") or {}).get("edges") or []) for o in (e.get("openings") or []) if o)
        rooms.append({"id": r["id"], "label": room_name(r), "tags": r.get("tags") or [],
                      "classification": [c["label"] for c in r.get("classifications") or []],
                      "floor": (r.get("floor") or {}).get("sequence"),
                      "area_sqft": round(dims["areaFloor"], 1) if dims.get("areaFloor") else None,
                      "width_ft": round(dims["width"], 1) if dims.get("width") else None,
                      "depth_ft": round(dims["depth"], 1) if dims.get("depth") else None,
                      "height_ft": round(dims["height"], 1) if dims.get("height") else None,
                      "bounds": room_bounds(r), "openings": doors})
    room_by_id = {r["id"]: r for r in rooms}
    sweeps = []
    for loc in m.get("locations") or []:
        rid = (loc.get("room") or {}).get("id")
        pos = loc.get("position") or {}
        if not rid and pos:  # fallback: point-in-bounds on the same floor (smallest room wins)
            fl = (loc.get("floor") or {}).get("sequence")
            hits = [r for r in rooms if r["bounds"] and r["floor"] == fl
                    and r["bounds"][0] <= pos["x"] <= r["bounds"][2] and r["bounds"][1] <= pos["y"] <= r["bounds"][3]]
            if hits:
                rid = min(hits, key=lambda r: (r["bounds"][2] - r["bounds"][0]) * (r["bounds"][3] - r["bounds"][1]))["id"]
        sweeps.append({"sweep_id": loc["id"], "label": loc.get("label"), "floor": (loc.get("floor") or {}).get("sequence"),
                       "room_id": rid, "room": room_by_id.get(rid, {}).get("label") if rid else None,
                       "room_tags": room_by_id.get(rid, {}).get("tags", []) if rid else [],
                       "position": loc.get("position"), "neighbors": loc.get("neighbors") or [],
                       "pano_id": (loc.get("pano") or {}).get("id")})
    tags = [{"id": t["id"], "label": t.get("label"), "description": t.get("description"), "keywords": t.get("keywords"),
             "floor": (t.get("floor") or {}).get("sequence"), "position": t.get("anchorPosition"),
             "media_type": t.get("mediaType"), "media": t.get("media")}
            for t in m.get("mattertags") or [] if t.get("enabled", True)]
    g = m.get("geolocation") or {}
    return {
        "model_id": m["id"], "name": m.get("name"), "created": m.get("created"), "description": m.get("description"),
        "address": (m.get("address") or {}).get("address"),
        "geolocation": {"lat": float(g["lat"]), "lng": float(g["long"])} if g.get("lat") else None,
        "building_floor_hint": floor_hint(m.get("name")),
        "dimensions": m.get("dimensions"), "floors": floors, "rooms": rooms, "mattertags": tags,
        "sweeps": sweeps, "sweep_count": len(sweeps),
        "_floorplans": (m.get("assets") or {}).get("floorplans") or [], "_image": (m.get("image") or {}).get("url"),
        "url": f"https://my.matterport.com/show/?m={m['id']}",
    }


def pick_panos(models, n):
    """Pick n sweeps: group by (model, room), order rooms by fire-relevance priority, then round-robin
    across rooms (and models), choosing within a room the sweep farthest from those already picked."""
    import math
    groups = {}
    for mi, md in enumerate(models):
        for s in md["sweeps"]:
            if not s.get("position"):
                continue
            groups.setdefault((mi, s["room_id"] or "none"), []).append(s)
    def prio(k):
        tags = groups[k][0]["room_tags"]
        return (min([PRIORITY.get(t, 8) for t in tags] or [9]), -len(groups[k]))
    order = sorted(groups, key=prio)
    chosen, picked = [], {k: [] for k in order}
    def dist(a, b):
        return math.dist([a["x"], a["y"], a["z"]], [b["x"], b["y"], b["z"]])
    while len(chosen) < n:
        progressed = False
        for k in order:
            if len(chosen) >= n:
                break
            pool = [s for s in groups[k] if s not in picked[k]]
            if not pool:
                continue
            if picked[k]:
                s = max(pool, key=lambda c: min(dist(c["position"], p["position"]) for p in picked[k]))
            else:
                s = pool[len(pool) // 2]
            picked[k].append(s); chosen.append((k[0], s)); progressed = True
        if not progressed:
            break
    return chosen


def download(url, client):
    for i in range(3):
        try:
            r = client.get(url, timeout=60)
            if r.status_code == 200:
                return r.content
        except httpx.HTTPError:
            pass
        time.sleep(2 * (i + 1))
    return None


def save_floorplans(md, bdir, client):
    out = []
    for fp in md.pop("_floorplans"):
        flags = [f for f in (fp.get("flags") or []) if f != "photogramy"]
        if "alpha" in flags:
            continue
        kind = flags[0] if flags else "plain"
        if kind not in ("plain", "measurements"):
            continue
        seq = (fp.get("floor") or {}).get("sequence")
        name = f"floorplan_{md['model_id']}_f{seq}_{kind}.jpg"
        if any(o["file"] == name for o in out):
            continue
        data = download(fp["url"], client)
        if not data:
            continue
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((2400, 2400))
        im.save(bdir / name, quality=85)
        out.append({"floor": seq, "file": name, "kind": kind, "width": im.width, "height": im.height,
                    "source": "matterport colorplan (assets.floorplans)"})
    md["floorplans"] = out
    img = md.pop("_image")
    if img:
        data = download(img, client)
        if data:
            im = Image.open(io.BytesIO(data)).convert("RGB")
            im.thumbnail((1280, 1280))
            name = f"thumb_{md['model_id']}.jpg"
            im.save(bdir / name, quality=85)
            md["thumbnail"] = name


def cache_building(p):
    bid = p["building_id"]
    bdir = CACHE / bid
    bdir.mkdir(parents=True, exist_ok=True)
    mids = resolve_models(p)
    print(bid, "models:", mids, flush=True)
    client = httpx.Client(follow_redirects=True)
    models = []
    for mid in mids:
        try:
            md = fetch_model(mid)
        except Exception as e:  # one inaccessible/deleted scan must not sink the whole building
            print("  skip model", mid, e, flush=True)
            continue
        save_floorplans(md, bdir, client)
        models.append(md)
        time.sleep(0.2)
    panos = []
    for mi, s in pick_panos(models, PANOS_PER_BUILDING):
        md = models[mi]
        d = gql(SKY_Q, {"id": md["model_id"], "ids": [s["pano_id"] or s["sweep_id"]]})
        pl = (((d.get("data") or {}).get("model") or {}).get("panoLocations") or [])
        kids = ((pl[0].get("skybox") or {}).get("children") if pl else None) or []
        if len(kids) != 6:
            print("  no skybox for", s["sweep_id"]); continue
        faces = []
        for u in kids:
            b = download(u, client)
            if not b:
                break
            faces.append(Image.open(io.BytesIO(b)))
        if len(faces) != 6:
            continue
        fname = f"pano_{md['model_id']}_{s['sweep_id']}.jpg"
        skybox_to_equirect(faces, 2048).save(bdir / fname, quality=82)
        panos.append({"sweep_id": s["sweep_id"], "sweep_label": s["label"], "model_id": md["model_id"],
                      "model_name": md["name"], "floor": s["floor"], "building_floor_hint": md["building_floor_hint"],
                      "room": s["room"], "room_tags": s["room_tags"], "position": s["position"],
                      "file": fname, "projection": "equirectangular 2048x1024 (stitched from 2k skybox)"})
        print("  pano", fname, s["room"], flush=True)
    keep = {p_["file"] for p_ in panos}
    for f in bdir.glob("pano_*.jpg"):  # drop panoramas from earlier runs
        if f.name not in keep:
            f.unlink()
    meta = {"building_id": bid, "name": p["name"], "address": p["address"], "city": p["city"],
            "cached_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "models": models}
    (bdir / "model.json").write_text(json.dumps(meta, indent=1))
    (bdir / "panos.json").write_text(json.dumps({"building_id": bid, "panos": panos}, indent=1))
    return meta


def census_geocode(address):
    url = ("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?benchmark=Public_AR_Current&format=json&address="
           + urllib.parse.quote(address))
    try:
        r = httpx.get(url, timeout=30).json()
        ms = r["result"]["addressMatches"]
        if ms:
            c = ms[0]["coordinates"]
            return {"lat": c["y"], "lng": c["x"], "matched": ms[0]["matchedAddress"], "source": "census"}
    except Exception as e:  # noqa
        print("census fail", address, e)
    return None


def write_registry(metas):
    reg_path = ROOT / "agent/cache/buildings.json"
    existing = {}
    if reg_path.exists():
        try:
            existing = {b["building_id"]: b for b in json.loads(reg_path.read_text())}
        except Exception:
            existing = {}
    for meta in metas:
        geo = census_geocode(meta["address"])
        mp = next((m["geolocation"] for m in meta["models"] if m.get("geolocation")), None)
        # Matterport geolocation lands inside the true footprint; census was 30-210 m off (per Vexcel check)
        lat, lng, src = (mp["lat"], mp["lng"], "matterport") if mp else ((geo["lat"], geo["lng"], "census") if geo else (None, None, None))
        prev = existing.get(meta["building_id"], {})
        existing[meta["building_id"]] = {
            "building_id": meta["building_id"], "name": meta["name"], "address": meta["address"], "city": meta["city"],
            "lat": lat, "lng": lng, "geocode_source": src,
            "matterport_geolocation": mp,
            "census_lat": geo["lat"] if geo else None, "census_lng": geo["lng"] if geo else None,
            "costar_id": prev.get("costar_id"),
            "matterport_model_ids": [m["model_id"] for m in meta["models"]],
            "has": {"costar": (prev.get("has") or {}).get("costar", False), "vexcel": (prev.get("has") or {}).get("vexcel", True),
                    "matterport": True},
        }
    reg = sorted(existing.values(), key=lambda b: b["building_id"])
    reg_path.write_text(json.dumps(reg, indent=1))
    print("wrote", reg_path)


def main():
    want = set(sys.argv[1:])
    metas = []
    for p in PICKS:
        if want and p["building_id"] not in want:
            continue
        metas.append(cache_building(p))
    write_registry(metas)


if __name__ == "__main__":
    main()
