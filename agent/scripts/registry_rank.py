"""Rank registry buildings for demo curation: current-tenant hazards (CoStar via the deterministic hazard rules)
x Matterport coverage. Prints a summary only (no raw records).
Usage: agent/.venv/bin/python -m agent.scripts.registry_rank [N] [--all-types]"""
import json, sys
from agent import config
from agent.tools import costar, hazard_rules


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 40
    mp = {m["id"]: m for m in json.loads((config.AGENT_DIR / "data/matterport_index.json").read_text())["models"]}
    reg = json.loads(config.REGISTRY_PATH.read_text())
    rows = []
    for b in reg:
        if b.get("featured") or (b.get("property_type") in ("Multifamily", None) and "--all-types" not in sys.argv):
            continue
        t = costar.costar_tenants(b["building_id"])
        if t.get("error"):
            continue
        hz = hazard_rules.match_hazards(t.get("tenants") or [], b.get("year_built"))
        hz = hz.get("hazards", hz) if isinstance(hz, dict) else hz
        kinds = sorted({h.get("rule") or h.get("type") for h in hz if isinstance(h, dict)})
        who = sorted({(h.get("reason") or "").split("'")[1][:18] if "'" in (h.get("reason") or "") else "" for h in hz if isinstance(h, dict)})
        sweeps = sum(mp.get(m, {}).get("sweeps") or 0 for m in b["matterport_model_ids"])
        nm = len(b["matterport_model_ids"])
        score = len(kinds) * 4 + min(len(hz), 8) + min(nm, 6) * 1.5 + min(sweeps, 400) / 50
        rows.append((round(score, 1), b["building_id"], b["city"][:3], b["property_type"], b.get("stories"),
                     t.get("tenant_count"), nm, sweeps, b["address"][:38], ",".join(map(str, kinds))[:90],
                     ";".join(who)[:90]))
    for r in sorted(rows, reverse=True)[:n]:
        print(*r, sep=" | ")


if __name__ == "__main__":
    main()
