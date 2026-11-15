import type { Cite, Plan } from "./types";

export const VERIFY = "VERIFY ON SITE";

export interface NormCite {
  src: string;
  id: string | null;
  conf: number | null;
  bbox: [number, number, number, number] | null;
  url: string | null;
  from: string[] | null;
  model: string | null;
  raw: Cite;
}

export function normCite(c: unknown, fallbackConf?: unknown): NormCite | null {
  if (!c || typeof c !== "object") return null;
  const x = c as Cite;
  if (!x.src) return null;
  const id = (x.id ?? x.tile ?? x.sweep ?? x.record_id ?? x.record ?? null) as string | null;
  const conf = typeof x.conf === "number" ? x.conf : typeof fallbackConf === "number" ? fallbackConf : null;
  const bbox = Array.isArray(x.bbox) && x.bbox.length === 4 && x.bbox.some((n) => n !== 0) ? (x.bbox as [number, number, number, number]) : null;
  return {
    src: String(x.src).toLowerCase(),
    id: id ? String(id) : null,
    conf,
    bbox,
    url: typeof x.url === "string" ? x.url : null,
    from: Array.isArray(x.from) ? (x.from as string[]) : null,
    model: (x.model ?? x.model_id ?? null) as string | null,
    raw: x,
  };
}

export interface NormField {
  value: string | number | boolean | null;
  cite: NormCite | null;
  verify: boolean;
}

const isVerify = (v: unknown) => typeof v === "string" && /verify\s+on\s+site/i.test(v);

export function isFieldObj(x: unknown): x is { value: unknown; cite?: unknown } {
  return !!x && typeof x === "object" && !Array.isArray(x) && "value" in (x as object);
}

export function normField(x: unknown): NormField {
  if (x === null || x === undefined) return { value: null, cite: null, verify: true };
  if (isFieldObj(x)) {
    const raw = x.value;
    const value =
      raw === null || raw === undefined
        ? null
        : typeof raw === "object"
          ? JSON.stringify(raw)
          : (raw as string | number | boolean);
    const cite = normCite(x.cite, (x as Record<string, unknown>).conf);
    return { value, cite, verify: value === null || isVerify(value) };
  }
  if (typeof x === "object") return { value: JSON.stringify(x), cite: null, verify: false };
  return { value: x as string | number | boolean, cite: null, verify: isVerify(x) };
}

export function fmtValue(v: NormField["value"], key?: string): string {
  if (v === null) return VERIFY;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") {
    if (key && /sq_?ft|sqft|area|rba/i.test(key)) return `${v.toLocaleString()} SF`;
    if (key && /_m2$/.test(key)) return `${v.toLocaleString()} m² (${Math.round(v * 10.764).toLocaleString()} SF)`;
    if (key && /height_ft$/.test(key)) return `${v} ft`;
    if (key && /height_m$|_m$/.test(key)) return `${v} m`;
    if (key && /year/i.test(key)) return String(v);
    return v.toLocaleString();
  }
  return v;
}

export function humanize(key: string): string {
  const special: Record<string, string> = {
    sq_ft: "Gross area",
    rba_sqft: "Rentable area",
    fdc: "FDC",
    year_built: "Year built",
    occupant_load_estimate: "Occupant load",
    roof_access: "Roof access",
    building_class: "Class / type",
    alarm_panel: "Alarm panel",
    electrical_room: "Electrical room",
    gas_shutoff: "Gas shutoff",
    access_roads: "Access roads",
    year_renovated: "Renovated",
    height_ft: "Height (CoStar)",
    height_m: "Height (Vexcel DSM)",
    footprint_m2: "Footprint",
    elevators_costar: "Elevators (CoStar)",
    loading_docks: "Loading docks",
    power: "Electrical service",
    property_type: "Property type",
    mechanical_room: "Mechanical room",
    sprinkler_riser: "Sprinkler riser",
    knox_box: "Knox box",
    owner: "Owner",
  };
  if (special[key]) return special[key];
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const SOURCE_META: Record<string, { label: string; short: string; color: string; text: string }> = {
  costar: { label: "CoStar", short: "CS", color: "var(--src-costar)", text: "text-src-costar" },
  vexcel: { label: "Vexcel", short: "VX", color: "var(--src-vexcel)", text: "text-src-vexcel" },
  matterport: { label: "Matterport", short: "MP", color: "var(--src-matterport)", text: "text-src-matterport" },
  inference: { label: "Inference", short: "IN", color: "var(--src-inference)", text: "text-src-inference" },
  officer: { label: "Officer", short: "OF", color: "var(--src-officer)", text: "text-src-officer" },
};

export function sourceMeta(src: string) {
  return SOURCE_META[src] ?? { label: src, short: src.slice(0, 2).toUpperCase(), color: "var(--fg-3)", text: "text-fg-3" };
}

/** Walk the plan and count leaf facts: cited vs VERIFY ON SITE. */
export function coverage(plan: Plan | null): { cited: number; verify: number; bySrc: Record<string, number> } {
  const out = { cited: 0, verify: 0, bySrc: {} as Record<string, number> };
  if (!plan) return out;
  const visit = (x: unknown, key: string) => {
    if (["voice_brief", "status", "approved_by", "plan_id", "address", "costar_id", "building_id"].includes(key)) return;
    if (Array.isArray(x)) return x.forEach((y) => visit(y, ""));
    if (x && typeof x === "object") {
      const o = x as Record<string, unknown>;
      if ("cite" in o) {
        const c = normCite(o.cite);
        const val = "value" in o ? o.value : "loc" in o ? o.loc : "type" in o ? o.type : "desc" in o ? o.desc : o.name;
        if (c && !isVerify(val)) {
          out.cited++;
          out.bySrc[c.src] = (out.bySrc[c.src] ?? 0) + 1;
        } else out.verify++;
        return;
      }
      Object.entries(o).forEach(([k, v]) => visit(v, k));
      return;
    }
    if (isVerify(x)) out.verify++;
  };
  Object.entries(plan).forEach(([k, v]) => visit(v, k));
  return out;
}

export function getPath(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((o, k) => (o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined), obj);
}

export function laneKey(name: string): string {
  const n = name.toLowerCase();
  if (n.includes("costar")) return "costar";
  if (n.includes("aerial") || n.includes("vexcel")) return "aerial";
  if (n.includes("interior") || n.includes("matterport")) return "interior";
  if (n.includes("hazard")) return "hazards";
  if (n.includes("valid")) return "validator";
  return "planner";
}

export function laneForTool(tool: string): string | null {
  const t = tool.toLowerCase();
  if (t.startsWith("costar")) return "costar";
  if (t.startsWith("vexcel")) return "aerial";
  if (t.startsWith("matterport")) return "interior";
  return null;
}
