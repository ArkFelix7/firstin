import sys, time, json
from agent.tools import costar, matterport, vexcel
bid = sys.argv[1]
def t(name, f, *a):
    t0 = time.time(); r = f(*a); dt = time.time() - t0
    err = r.get("error") if isinstance(r, dict) else None
    summ = {k: r.get(k) for k in ("address","year_built","stories","sweep_count","tile_id","gsd_m") if isinstance(r, dict) and r.get(k) is not None}
    if name == "costar_tenants": summ = {"n_tenants": len(r.get("tenants") or [])}
    if name == "matterport_panoramas": summ = {"n_panos": len(r.get("panos") or [])}
    if name == "vexcel_roof" and not err: summ = {k: r["target"].get(k) for k in ("roof_material","height_est_m","building_type")}
    print(f"{name:22s} {dt:6.1f}s  {'ERR '+str(err)[:300] if err else json.dumps(summ, default=str)[:200]}", flush=True)
T0 = time.time()
t("costar_property", costar.costar_property, bid)
t("costar_tenants", costar.costar_tenants, bid)
t("matterport_model", matterport.matterport_model, bid)
t("matterport_panoramas", matterport.matterport_panoramas, bid)
t("vexcel_tile", vexcel.vexcel_tile, bid, "ortho")
t("vexcel_tile_context", vexcel.vexcel_tile, bid, "context")
t("vexcel_oblique_N", vexcel.vexcel_oblique, bid, "N")
t("vexcel_roof", vexcel.vexcel_roof, bid)
t("vexcel_footprint", vexcel.vexcel_footprint, bid)
print("TOTAL", round(time.time()-T0,1))
