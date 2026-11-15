"""Build full Matterport model index -> agent/data/matterport_index.json (cursor pagination via nextOffset)."""
import json, time
from agent.scripts.mp_gql import gql, ROOT

Q = """query($off:String,$ps:Int){ models(pageSize:$ps, offset:$off) { totalResults nextOffset results {
  id name created description
  address { address streetAddressLines locality administrativeArea postalCode }
  publication { address }
  geolocation { lat long }
  floors { count } rooms { count labels } mattertags { count labels }
  assets { panoLocations { count } locations { count } panos { count } }
} } }"""

def main():
    out, off, ps = [], None, 500
    while True:
        d = gql(Q, {"off": off, "ps": ps})
        if "errors" in d and not d.get("data"):
            if ps > 100:
                ps = 100; continue
            raise SystemExit(d["errors"])
        m = d["data"]["models"]
        for r in m["results"]:
            a = r.get("address") or {}
            g = r.get("geolocation") or {}
            out.append({
                "id": r["id"], "name": r.get("name"), "created": r.get("created"),
                "description": (r.get("description") or "")[:300],
                "address": a.get("address") or (r.get("publication") or {}).get("address"),
                "street": (a.get("streetAddressLines") or [None])[0],
                "city": a.get("locality"), "state": a.get("administrativeArea"), "zip": a.get("postalCode"),
                "lat": float(g["lat"]) if g.get("lat") else None, "lng": float(g["long"]) if g.get("long") else None,
                "floors": (r.get("floors") or {}).get("count"),
                "rooms": (r.get("rooms") or {}).get("count"), "room_labels": (r.get("rooms") or {}).get("labels"),
                "tags": (r.get("mattertags") or {}).get("count"), "tag_labels": ((r.get("mattertags") or {}).get("labels") or [])[:30],
                "sweeps": ((r.get("assets") or {}).get("panoLocations") or {}).get("count"),
                "locations": ((r.get("assets") or {}).get("locations") or {}).get("count"),
            })
        print(len(out), "/", m["totalResults"], flush=True)
        off = m.get("nextOffset")
        if not off or not m["results"]:
            break
        time.sleep(0.3)
    p = ROOT / "agent/data/matterport_index.json"
    p.write_text(json.dumps({"total": len(out), "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "models": out}, indent=0))
    print("wrote", p)

if __name__ == "__main__":
    main()
