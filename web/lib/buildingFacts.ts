// Read-only building facts for the map page's detail panel, from the agent's
// offline cache (served at /static/cache) plus the server's run list.
// Every call degrades to null; the panel just shows fewer rows.

import { apiBase, assetUrl, getMode } from "./api";
import type { Building } from "./types";

export interface BuildingFacts {
  yearBuilt: number | null;
  yearRenovated: number | null;
  stories: number | null;
  areaSf: number | null;
  heightFt: number | null;
  costarProperty: string | null;
  vexcelCaptured: string | null;
  vexcelGsd: number | null;
  aerialUrl: string | null;
  /** Agent-drawn access plan (ladder walls, staging, entries), when the building was analysed. */
  accessUrl: string | null;
  matterportCreated: string | null;
  matterportModels: number | null;
  matterportSweeps: number | null;
}

export interface RunSummary {
  run_id: string;
  building_id: string;
  status: string;
  created_at: number | null;
}

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${apiBase()}${path}`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

const num = (x: unknown) => (typeof x === "number" && isFinite(x) ? x : null);

export async function getBuildingFacts(b: Building): Promise<BuildingFacts | null> {
  if ((await getMode()) === "mock") return null;
  const id = encodeURIComponent(b.building_id);
  const accessPath = `/static/cache/vexcel/${id}/access_annotated.jpg`;
  const [costar, ortho, mp, accessOk] = await Promise.all([
    getJson<Record<string, unknown>>(`/static/cache/costar/${id}.json`),
    getJson<Record<string, unknown>>(`/static/cache/vexcel/${id}/ortho.json`),
    getJson<{ models?: Array<Record<string, unknown>> }>(`/static/cache/matterport/${id}/model.json`),
    fetch(`${apiBase()}${accessPath}`, { method: "HEAD", cache: "no-store", signal: AbortSignal.timeout(3000) })
      .then((r) => r.ok)
      .catch(() => false),
  ]);
  const p = (costar?.property ?? {}) as Record<string, unknown>;
  const events = Array.isArray(p.constructionEvents) ? (p.constructionEvents as Array<{ eventType?: number; year?: number }>) : [];
  const models = Array.isArray(mp?.models) ? mp.models : [];
  const created = models.map((m) => String(m.created ?? "")).filter(Boolean).sort();
  return {
    yearBuilt: num(events.find((e) => e.eventType === 2)?.year),
    yearRenovated: num(events.find((e) => e.eventType === 4)?.year),
    stories: num(p.numStoriesAboveGrade),
    areaSf: num(p.rentableBuildingAreaSquareFeet) ?? num(p.grossBuildingAreaSquareFeet),
    heightFt: num(p.buildingHeightInFeet),
    costarProperty: costar?.property_id ? String(costar.property_id) : p.id ? String(p.id) : null,
    vexcelCaptured: typeof ortho?.captured_at === "string" ? ortho.captured_at : null,
    vexcelGsd: num(ortho?.gsd_m),
    aerialUrl: assetUrl(ortho?.preview_url ?? ortho?.image_url),
    accessUrl: accessOk ? assetUrl(accessPath) : null,
    matterportCreated: created[0] ?? null,
    matterportModels: models.length || null,
    matterportSweeps: models.reduce((n, m) => n + (num(m.sweep_count) ?? 0), 0) || null,
  };
}

export async function getRuns(): Promise<RunSummary[]> {
  if ((await getMode()) === "mock") return [];
  const raw = await getJson<RunSummary[] | { runs: RunSummary[] }>("/runs");
  const list = Array.isArray(raw) ? raw : (raw?.runs ?? []);
  return [...list].sort((a, z) => (z.created_at ?? 0) - (a.created_at ?? 0));
}

export function fmtDate(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "";
  const d = typeof v === "number" ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
  return isNaN(d.getTime()) ? String(v) : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function fmtTime(v: number | null | undefined): string {
  if (!v) return "";
  const d = new Date(v < 1e12 ? v * 1000 : v);
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

/* ---------------- Search ---------------- */

let serverSearch: boolean | null = null; // feature-detected once per page load

function clientSearch(all: Building[], q: string, city: string | null) {
  const s = q.trim().toLowerCase();
  const hits = all.filter((b) => (!city || b.city === city) && `${b.address} ${b.name ?? ""} ${b.building_id} ${b.costar_id ?? ""}`.toLowerCase().includes(s));
  // prefix matches on the street address first, then featured, then the rest
  const rank = (b: Building) => (b.address.toLowerCase().startsWith(s) ? 0 : 1) * 2 + (b.featured ? 0 : 1);
  return hits.sort((a, z) => rank(a) - rank(z));
}

/** GET /buildings/search when the server has it, else filter the loaded registry. */
export async function searchBuildings(all: Building[], q: string, city: string | null, limit: number): Promise<{ total: number; items: Building[] }> {
  if (serverSearch !== false && (await getMode()) === "live") {
    try {
      const params = new URLSearchParams({ q, limit: String(limit) });
      if (city) params.set("city", city);
      const r = await fetch(`${apiBase()}/buildings/search?${params}`, { cache: "no-store", signal: AbortSignal.timeout(2500) });
      if (r.ok) {
        serverSearch = true;
        const d = (await r.json()) as { total?: number; items?: Building[] };
        if (Array.isArray(d.items)) return { total: d.total ?? d.items.length, items: d.items };
      } else if (r.status === 404 || r.status === 405) serverSearch = false;
    } catch {
      /* fall through to client search */
    }
  }
  const hits = clientSearch(all, q, city);
  return { total: hits.length, items: hits.slice(0, limit) };
}
