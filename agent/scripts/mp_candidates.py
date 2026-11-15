"""Score commercial demo-building candidates. Groups index models by street address, fetches light detail."""
import json, re, collections, time
from agent.scripts.mp_gql import gql, ROOT

KW = re.compile(r'suite|office|retail|warehouse|restaurant|industrial|commercial|church|school|clinic|medical|hotel|parking|garage|creative|showroom|cowork|co-working|flex|building|floor\b|lobby|loft|gym|fitness|industrious', re.I)
APT = re.compile(r'\b\d ?(br|bd|bed)\b|studio|townho|floor plan', re.I)
FIRE = {"staircase", "stairs", "hallway", "utility", "laundry", "garage", "basement", "kitchen", "entrance", "foyer", "lobby", "elevator", "storage", "mechanical", "closet"}
Q = '''query($id:ID!){ model(id:$id){ id floors { sequence } rooms { tags } locations { id } mattertags { id }
 assets { floorplans(formats:["jpg"]) { id } } } }'''

def key(m):
    return ((m.get('street') or m.get('address') or '').split(',')[0].strip().lower(), m.get('city'))

def main():
    M = json.load(open(ROOT / 'agent/data/matterport_index.json'))['models']
    g = collections.defaultdict(list)
    for m in M:
        k = key(m)
        if k[0] and k[1]:
            g[k].append(m)
    pool = []
    for k, ms in g.items():
        com = [m for m in ms if KW.search(m['name'] or '') and not APT.search(m['name'] or '')]
        if not com:
            continue
        sw = sum(m['sweeps'] or 0 for m in com)
        if sw >= 100:
            pool.append((sw, k, ms))
    pool.sort(key=lambda x: -x[0])
    out = []
    for sw, k, ms in pool[:45]:
        det = []
        for m in ms[:15]:
            d = gql(Q, {"id": m['id']}).get('data', {}).get('model') or {}
            tags = collections.Counter(t for r in d.get('rooms') or [] for t in (r.get('tags') or []))
            det.append({"id": m['id'], "name": m['name'], "floors": len(d.get('floors') or []),
                        "locations": len(d.get('locations') or []), "mattertags": len(d.get('mattertags') or []),
                        "floorplans": len((d.get('assets') or {}).get('floorplans') or []), "room_tags": dict(tags)})
            time.sleep(0.1)
        alltags = collections.Counter()
        for x in det: alltags.update(x['room_tags'])
        fire = {t: c for t, c in alltags.items() if t in FIRE}
        score = (max(x['floors'] for x in det) * 10 + min(sum(x['locations'] for x in det), 600) / 10
                 + sum(x['mattertags'] for x in det) * 0.5 + len(fire) * 6 + fire.get('staircase', 0) * 4
                 + fire.get('utility', 0) * 3 + len(det) * 2)
        out.append({"street": k[0], "city": k[1], "address": ms[0]['address'], "lat": ms[0]['lat'], "lng": ms[0]['lng'],
                    "score": round(score, 1), "fire_room_tags": fire, "all_room_tags": dict(alltags), "models": det})
        print(round(score, 1), k, len(det), max(x['floors'] for x in det), sum(x['locations'] for x in det), fire, flush=True)
    out.sort(key=lambda x: -x['score'])
    (ROOT / 'agent/cache/matterport').mkdir(parents=True, exist_ok=True)
    (ROOT / 'agent/cache/matterport/candidates.json').write_text(json.dumps(out, indent=1))

if __name__ == '__main__':
    main()
