"use client";

import { AlertTriangle, Check, CheckCircle2 } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { SourceGlyph, SourceTag, Spinner, StatusBadge, Td, Th, VerifyValue, Mono, planStatusTone } from "@/components/ui";
import { coverage, fmtValue, humanize, isFieldObj, normCite, normField, sourceMeta, VERIFY, type NormCite, type NormField } from "@/lib/plan";
import { splitDetail, clean, sentence } from "@/lib/text";
import type { Plan } from "@/lib/types";

export interface Selection {
  path: string;
  label: string;
  value: string;
  cite: NormCite | null;
  reason?: string;
}

export interface SheetCtx {
  selected: string | null;
  onSelect: (s: Selection) => void;
  editing: boolean;
  edits: Record<string, string>;
  onEdit: (path: string, v: string) => void;
}

/** True when the document column is narrow (< 760 px): tables drop secondary columns. */
const Compact = createContext(false);

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(1000);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export const OFFICER_CITE: NormCite = { src: "officer", id: "manual-edit", conf: 1, bbox: null, url: null, from: null, model: null, raw: { src: "officer" } };

const SIDE: Record<string, string> = { N: "North", S: "South", E: "East", W: "West", NE: "Northeast", NW: "Northwest", SE: "Southeast", SW: "Southwest" };
const sideName = (s: unknown) => SIDE[String(s ?? "").toUpperCase()] ?? String(s ?? "Unknown");

const LANE_NAME: Record<string, string> = {
  costar: "CoStar analyst",
  aerial: "Aerial analyst",
  interior: "Interior analyst",
  hazards: "Hazard reasoner",
  planner: "Planner",
};

/* ------------------------------------------------------------------ */
/* Field row: label | value | source                                   */

/** Value text with any backend dash-joined pair split into value and a quieter detail. */
function ValueText({ text, clamp }: { text: string; clamp?: boolean }) {
  const { main, detail } = splitDetail(text);
  return (
    <span className={`block text-sm text-fg ${clamp ? "line-clamp-3" : ""}`}>
      {main}
      {detail && <span className="ml-2 text-xs text-fg-3">{detail}</span>}
    </span>
  );
}

function EditInput({ path, initial, placeholder, ctx }: { path: string; initial: string; placeholder?: string; ctx: SheetCtx }) {
  return (
    <input
      defaultValue={ctx.edits[path] ?? initial}
      placeholder={placeholder}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => ctx.onEdit(path, e.target.value)}
      className="h-7 w-full rounded border border-line-strong bg-surface px-2 text-sm text-fg placeholder:text-fg-4 focus:border-accent focus:outline-none"
    />
  );
}

function SelBar({ on }: { on: boolean }) {
  return on ? <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" /> : null;
}

function FieldRow({ ctx, path, label, field, extra }: { ctx: SheetCtx; path: string; label: string; field: NormField; extra?: ReactNode }) {
  const edited = ctx.edits[path];
  const isEdited = edited !== undefined && edited.trim() !== "";
  const cite = isEdited ? OFFICER_CITE : field.cite;
  const verify = !isEdited && field.verify;
  const text = isEdited ? edited : clean(fmtValue(field.value, path.split(".").pop()));
  const active = ctx.selected === path;
  const select = () => ctx.onSelect({ path, label, value: verify ? VERIFY : text, cite: verify ? null : cite });

  return (
    <div
      onClick={select}
      data-path={path}
      className={`relative grid cursor-pointer grid-cols-[minmax(96px,min(22%,168px))_minmax(0,1fr)_auto] items-start gap-4 border-b border-line px-6 py-2 last:border-b-0 ${
        active ? "bg-accent-subtle" : "hover:bg-subtle"
      }`}
    >
      <SelBar on={active} />
      <div className="text-xs leading-5 text-fg-3">{label}</div>
      <div className="min-w-0">
        {ctx.editing ? (
          <EditInput path={path} initial={verify ? "" : text} placeholder={verify ? "Enter verified value" : undefined} ctx={ctx} />
        ) : verify ? (
          <span className="text-sm">
            <VerifyValue />
          </span>
        ) : (
          <>
            <ValueText text={text} clamp={!active} />
            {extra}
          </>
        )}
      </div>
      <div className="flex min-w-[88px] justify-end pt-0.5">{verify ? <span className="text-2xs text-fg-4">No source</span> : <SourceTag cite={cite} active={active} onClick={select} />}</div>
    </div>
  );
}

/** Render every cited (or flagged) field of an object, flattening nested groups. */
function fieldsOf(obj: Record<string, unknown> | undefined, base: string, skip: string[]): Array<{ path: string; label: string; field: NormField }> {
  const out: Array<{ path: string; label: string; field: NormField }> = [];
  if (!obj) return out;
  for (const [k, v] of Object.entries(obj)) {
    if (skip.includes(k) || Array.isArray(v) || v === null || v === undefined) continue;
    const path = `${base}.${k}`;
    if (typeof v === "object" && !isFieldObj(v) && !("cite" in (v as object))) {
      out.push(...fieldsOf(v as Record<string, unknown>, path, skip));
    } else if (typeof v === "object" || /verify\s+on\s+site/i.test(String(v))) {
      out.push({ path, label: humanize(k), field: normField(v) });
    }
  }
  return out;
}

function Rows({ ctx, rows }: { ctx: SheetCtx; rows: Array<{ path: string; label: string; field: NormField }> }) {
  if (!rows.length) return null;
  return (
    <div className="border-y border-line">
      {rows.map((f) => (
        <FieldRow key={f.path} ctx={ctx} {...f} />
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function Pending({ agent, rows = 3 }: { agent: string; rows?: number }) {
  return (
    <div className="border-y border-line" aria-busy>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="grid grid-cols-[168px_minmax(0,1fr)_128px] items-center gap-4 border-b border-line px-6 py-3 last:border-b-0">
          <div className="h-2 w-20 rounded-sm bg-muted" />
          <div className="h-2 rounded-sm bg-muted" style={{ width: `${70 - i * 15}%` }} />
          <div className="ml-auto h-2 w-14 rounded-sm bg-muted" />
        </div>
      ))}
      <span className="sr-only">Waiting for {agent}</span>
    </div>
  );
}

function SheetSection({
  id,
  title,
  meta,
  pending,
  agent,
  children,
}: {
  id?: string;
  title: string;
  meta?: ReactNode;
  pending: boolean;
  agent: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-4 pt-6">
      <header className="flex items-baseline justify-between gap-4 px-6 pb-2">
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 className="text-base font-semibold text-fg">{title}</h2>
          {!pending && meta && <span className="truncate text-xs text-fg-3">{meta}</span>}
        </div>
        {pending && (
          <span className="flex shrink-0 items-center gap-1.5 text-xs text-fg-3">
            <Spinner size={12} /> Waiting for {LANE_NAME[agent] ?? agent}
          </span>
        )}
      </header>
      {pending ? <Pending agent={agent} /> : children}
    </section>
  );
}

/* ------------------------------------------------------------------ */

function verifyItems(plan: Plan | null, sectionOf: (path: string) => string) {
  const out: Array<{ path: string; label: string; section: string }> = [];
  if (!plan) return out;
  const skip = new Set(["voice_brief", "status", "approved_by", "plan_id", "address", "costar_id", "building_id", "media", "sources", "validation", "edits", "verify_on_site"]);
  const walk = (x: unknown, path: string, key: string) => {
    if (skip.has(key)) return;
    if (Array.isArray(x)) return; // list items (tenants, hazards, stairs) carry their own state
    if (!x || typeof x !== "object") {
      if (typeof x === "string" && /verify\s+on\s+site/i.test(x)) out.push({ path, label: humanize(key), section: sectionOf(path) });
      return;
    }
    const o = x as Record<string, unknown>;
    if (isFieldObj(o)) {
      if (normField(o).verify) out.push({ path, label: humanize(key), section: sectionOf(path) });
      return;
    }
    for (const [k, v] of Object.entries(o)) walk(v, path ? `${path}.${k}` : k, k);
  };
  walk(plan, "", "");
  return out;
}

const SECTION_NAME: Record<string, string> = {
  building: "Building",
  occupancy: "Occupancy",
  access: "Access",
  "interior.fire_protection": "Fire protection",
  fire_protection: "Fire protection",
  interior: "Interior",
  hazards: "Hazards",
  exposures: "Exposures",
};
const sectionOf = (path: string) => {
  const hit = Object.keys(SECTION_NAME).find((k) => path === k || path.startsWith(k + "."));
  return hit ? SECTION_NAME[hit] : "Plan";
};

export function PlanSheet({ plan, ctx, lanes, runId }: { plan: Plan | null; ctx: SheetCtx; lanes: Record<string, { status: string }>; runId: string }) {
  const p = plan ?? {};
  const status = String(p.status ?? "DRAFT").toUpperCase();
  const st = planStatusTone(status);
  const cov = coverage(plan);
  const b = p.building as Record<string, unknown> | undefined;
  const interior = p.interior as Record<string, unknown> | undefined;
  const fp = { ...((interior?.fire_protection as Record<string, unknown>) ?? {}), ...((p.fire_protection as Record<string, unknown>) ?? {}) };
  const hasFp = !!interior?.fire_protection || !!p.fire_protection;
  const laneDone = (k: string) => lanes[k]?.status === "done" || lanes[k]?.status === "error";
  const address = (b?.address as string) ?? "Resolving building";
  const total = cov.cited + cov.verify;
  const pct = total ? Math.round((cov.cited / total) * 100) : 0;
  const verifyList = useMemo(() => verifyItems(plan, sectionOf), [plan]);
  const hazards = Array.isArray(p.hazards) ? (p.hazards as Array<Record<string, unknown>>) : [];
  const name = typeof b?.name === "string" ? b.name : null;
  const [ref, width] = useWidth<HTMLElement>();
  const compact = width < 760;

  return (
    <Compact.Provider value={compact}>
    <div className="mx-auto max-w-[1040px] px-6 pb-8 pt-6">
      <article ref={ref} className="rounded-md border border-line bg-surface pb-6 shadow-elev-1">
        {/* Document header */}
        <header className="px-6 pb-4 pt-5">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0">
              <div className="text-xs text-fg-3">NFPA 1660 pre-incident plan</div>
              <h1 className="mt-1 text-2xl font-semibold text-fg">{address}</h1>
              <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-3">
                {name && <span>{clean(name)}</span>}
                {b?.costar_id ? (
                  <span>
                    CoStar property <Mono>{String(b.costar_id)}</Mono>
                  </span>
                ) : null}
                <span>
                  Plan <Mono>{(p.plan_id as string) ?? runId}</Mono>
                </span>
              </div>
            </div>
            <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
          </div>
        </header>

        {/* Summary strip */}
        <div className={`grid gap-px border-y border-line bg-line ${compact ? "grid-cols-3" : "grid-cols-[1.1fr_1fr_1fr_2.2fr]"}`}>
          <Summary label="Coverage">
            <div className="text-xl font-semibold tabular-nums text-fg">{total ? `${pct}%` : "0%"}</div>
            <div className="mt-1.5 flex h-1 w-full overflow-hidden rounded-sm bg-muted">
              <div className="h-full bg-fg-2" style={{ width: `${pct}%` }} />
              <div className="h-full bg-warn" style={{ width: `${total ? 100 - pct : 0}%` }} />
            </div>
          </Summary>
          <Summary label="Cited facts">
            <div className="text-xl font-semibold tabular-nums text-fg">{cov.cited}</div>
          </Summary>
          <Summary label="Verify on site">
            <a href="#walkthrough" className={`text-xl font-semibold tabular-nums ${cov.verify ? "text-warn hover:underline" : "text-fg"}`}>
              {cov.verify}
            </a>
          </Summary>
          <Summary label="By source" wide={compact}>
            <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
              {Object.keys(cov.bySrc).length === 0 && <span className="text-sm text-fg-4">None yet</span>}
              {Object.entries(cov.bySrc)
                .sort((a, z) => z[1] - a[1])
                .map(([s, n]) => (
                  <span key={s} className="inline-flex items-center gap-1.5 text-sm text-fg-2">
                    <SourceGlyph src={s} />
                    {sourceMeta(s).label}
                    <span className="tabular-nums font-medium text-fg">{n}</span>
                  </span>
                ))}
            </div>
          </Summary>
        </div>

        {/* 1. Hazards first: what a crew needs to know */}
        <SheetSection
          id="hazards"
          title="Hazards"
          meta={hazards.length ? `${hazards.length} flagged, ranked by confidence` : undefined}
          pending={!p.hazards}
          agent="hazards"
        >
          <Hazards ctx={ctx} hazards={hazards} />
        </SheetSection>

        <SheetSection title="Building" pending={!b?.stories && !b?.year_built} agent="costar">
          <BuildingStats ctx={ctx} b={b} />
          <Rows
            ctx={ctx}
            rows={fieldsOf(b, "building", ["address", "name", "costar_id", "building_id", "stories", "year_built", "sq_ft", "rba_sqft", "lat", "lng", "city", "cross_check"])}
          />
        </SheetSection>

        <SheetSection
          title="Occupancy"
          meta={
            Array.isArray(p.occupancy?.tenants)
              ? (() => {
                  const list = p.occupancy.tenants as Array<Record<string, unknown>>;
                  const unk = list.filter(tenantNeedsVerify).length;
                  return `${list.length} tenants or spaces${unk ? `, ${unk} need verification` : ""}`;
                })()
              : undefined
          }
          pending={!p.occupancy}
          agent="costar"
        >
          {Array.isArray(p.occupancy?.tenants) ? (
            <Tenants ctx={ctx} tenants={p.occupancy.tenants as Array<Record<string, unknown>>} footer={fieldsOf(p.occupancy, "occupancy", ["tenants"])} />
          ) : (
            <Rows ctx={ctx} rows={[{ path: "occupancy.tenants", label: "Tenants", field: normField(p.occupancy?.tenants) }, ...fieldsOf(p.occupancy, "occupancy", ["tenants"])]} />
          )}
        </SheetSection>

        <SheetSection title="Access" pending={!p.access && !laneDone("aerial")} agent="aerial">
          <Rows ctx={ctx} rows={fieldsOf(p.access, "access", [])} />
        </SheetSection>

        <SheetSection title="Interior" pending={!interior && !laneDone("interior")} agent="interior">
          <div className="border-y border-line">
            {Array.isArray(interior?.stairwells) ? (
              (interior.stairwells as Array<Record<string, unknown>>).map((s, i) => (
                <FieldRow
                  key={i}
                  ctx={ctx}
                  path={`interior.stairwells.${i}.loc`}
                  label={`Stairwell ${String.fromCharCode(65 + i)}`}
                  field={normField({ value: s.loc ?? s.value ?? s.name, cite: s.cite })}
                  extra={s.standpipe ? <span className="mt-1 inline-flex text-xs text-fg-2">Standpipe present</span> : undefined}
                />
              ))
            ) : (
              <FieldRow ctx={ctx} path="interior.stairwells" label="Stairwells" field={normField(interior?.stairwells)} />
            )}
            {fieldsOf(interior, "interior", ["stairwells", "fire_protection"]).map((f) => (
              <FieldRow key={f.path} ctx={ctx} {...f} />
            ))}
          </div>
        </SheetSection>

        <SheetSection title="Fire protection" pending={!hasFp && !laneDone("interior")} agent="interior">
          <Rows ctx={ctx} rows={fieldsOf(fp, interior?.fire_protection ? "interior.fire_protection" : "fire_protection", [])} />
        </SheetSection>

        <SheetSection title="Exposures" meta={Array.isArray(p.exposures) ? `${p.exposures.length} sides` : undefined} pending={!p.exposures} agent="aerial">
          <Exposures ctx={ctx} exposures={Array.isArray(p.exposures) ? (p.exposures as Array<Record<string, unknown>>) : []} />
        </SheetSection>

        <SheetSection
          id="walkthrough"
          title="Walk-through checklist"
          meta={verifyList.length ? `${verifyList.length} items with no citable source. Confirm on site.` : undefined}
          pending={!plan || (!p.hazards && !p.access)}
          agent="planner"
        >
          <Checklist ctx={ctx} items={verifyList} />
        </SheetSection>

        <SheetSection title="Crew voice brief" pending={!p.voice_brief} agent="planner">
          <div className="px-6">
            <p className="border-l-2 border-line-strong pl-4 text-base leading-6 text-fg-2">{clean(String(p.voice_brief ?? ""))}</p>
          </div>
        </SheetSection>
      </article>
    </div>
    </Compact.Provider>
  );
}

function Summary({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`min-w-0 bg-surface px-6 py-3 ${wide ? "col-span-3" : ""}`}>
      <div className="text-xs text-fg-3">{label}</div>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

/* ---------------- Building key figures ---------------- */

function BuildingStats({ ctx, b }: { ctx: SheetCtx; b: Record<string, unknown> | undefined }) {
  const compact = useContext(Compact);
  const cc = b?.cross_check as Record<string, unknown> | undefined;
  const stats: Array<[string, string]> = [
    ["building.stories", "Stories"],
    ["building.year_built", "Year built"],
    ["building.sq_ft", "Gross area"],
  ];
  return (
    <div className={`grid gap-px border-t border-line bg-line ${compact ? "grid-cols-2" : cc ? "grid-cols-4" : "grid-cols-3"}`}>
      {stats.map(([path, label]) => {
        const key = path.split(".")[1];
        const field = normField(key === "sq_ft" ? (b?.sq_ft ?? b?.rba_sqft) : b?.[key]);
        const edited = ctx.edits[path];
        const isEdited = edited !== undefined && edited.trim() !== "";
        const cite = isEdited ? OFFICER_CITE : field.cite;
        const verify = !isEdited && field.verify;
        const text = isEdited ? edited : fmtValue(field.value, key);
        const active = ctx.selected === path;
        const select = () => ctx.onSelect({ path, label, value: verify ? VERIFY : text, cite: verify ? null : cite });
        return (
          <div key={path} data-path={path} onClick={select} className={`relative min-w-0 cursor-pointer px-6 py-3 ${active ? "bg-accent-subtle" : "bg-surface hover:bg-subtle"}`}>
            <SelBar on={active} />
            <div className="text-xs text-fg-3">{label}</div>
            {ctx.editing ? (
              <div className="mt-1">
                <EditInput path={path} initial={verify ? "" : text} ctx={ctx} />
              </div>
            ) : verify ? (
              <div className="mt-1 text-sm">
                <VerifyValue />
              </div>
            ) : (
              <div className="mt-0.5 truncate text-xl font-semibold tabular-nums text-fg">{text}</div>
            )}
            <div className="mt-1 -ml-1">{!verify && <SourceTag cite={cite} active={active} onClick={select} />}</div>
          </div>
        );
      })}
      {cc && <CrossCheck cc={cc} />}
    </div>
  );
}

/** CoStar x Vexcel height agreement, as a quiet verification note. */
function CrossCheck({ cc }: { cc: Record<string, unknown> }) {
  const agree = cc.agree !== false;
  const pct = typeof cc.ratio === "number" ? Math.round(cc.ratio * 100) : null;
  const cm = typeof cc.costar_m === "number" ? cc.costar_m : null;
  const vm = typeof cc.vexcel_m === "number" ? cc.vexcel_m : null;
  return (
    <div className="min-w-0 bg-surface px-6 py-3" title={typeof cc.note === "string" ? clean(cc.note) : undefined}>
      <div className="text-xs text-fg-3">Height</div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums text-fg">{cm !== null ? `${cm} m` : vm !== null ? `${vm} m` : "n/a"}</div>
      <div className={`mt-1 flex items-start gap-1 text-2xs ${agree ? "text-fg-2" : "text-warn"}`}>
        {agree ? <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-ok" /> : <AlertTriangle size={12} className="mt-0.5 shrink-0" />}
        <span>
          {agree
            ? `Verified across 2 sources${pct !== null ? `, ${pct}% agreement` : ""}`
            : `Sources disagree: CoStar ${cm ?? "?"} m, Vexcel ${vm ?? "?"} m`}
        </span>
      </div>
    </div>
  );
}

/* ---------------- Tenants ---------------- */

const TENANT_PREVIEW = 8;
const isUnknown = (v: unknown) => v === null || v === undefined || v === "" || /verify\s+on\s+site/i.test(String(v));

export function tenantNeedsVerify(t: Record<string, unknown>) {
  return isUnknown(t.use) && isUnknown(t.industry);
}

function Tenants({ ctx, tenants, footer }: { ctx: SheetCtx; tenants: Array<Record<string, unknown>>; footer: Array<{ path: string; label: string; field: NormField }> }) {
  const [all, setAll] = useState(false);
  const compact = useContext(Compact);
  const has = (k: string) => tenants.some((t) => !isUnknown(t[k]));
  const showSf = has("sqft");
  const showEmp = has("employees") && !compact;
  const ranked = tenants.map((t, i) => ({ t, i })).sort((a, z) => (Number(z.t.sqft) || 0) - (Number(a.t.sqft) || 0));
  const shown = all ? ranked : ranked.slice(0, TENANT_PREVIEW);
  const cols = 2 + (showSf ? 1 : 0) + (showEmp ? 1 : 0); // columns between tenant and source
  return (
    <>
      <table className="w-full table-fixed border-collapse">
        <colgroup>
          <col />
          <col className={compact ? "w-[34%]" : "w-[30%]"} />
          <col className="w-14" />
          {showSf && <col className="w-24" />}
          {showEmp && <col className="w-14" />}
          <col className="w-14" />
        </colgroup>
        <thead>
          <tr>
            <Th className="pl-6">Tenant</Th>
            <Th>Industry</Th>
            <Th align="right">Floor</Th>
            {showSf && <Th align="right">Area (SF)</Th>}
            {showEmp && <Th align="right">Staff</Th>}
            <Th align="right" className="pr-6">
              <span className="sr-only">Source</span>
            </Th>
          </tr>
        </thead>
        <tbody>
          {shown.map(({ t, i }) => {
            const path = `occupancy.tenants.${i}`;
            const cite = normCite(t.cite);
            const active = ctx.selected === path;
            const tname = splitDetail(clean(String(t.name ?? "Unnamed tenant")));
            const rawUse = !isUnknown(t.use) ? String(t.use) : !isUnknown(t.industry) ? String(t.industry) : null;
            const use = rawUse ? clean(rawUse).replace(/\s*\((?:[a-z/ ]+ )?space\)\s*$/i, "") : null;
            const sub = [t.suite ? `Suite ${String(t.suite).replace(/^(ste|suite)\.?\s+/i, "")}` : null, tname.detail, t.move_in ? `Since ${String(t.move_in).slice(0, 7)}` : null].filter(Boolean).join(", ");
            const sel = () => ctx.onSelect({ path, label: `Tenant: ${tname.main}`, value: use ? `${tname.main}. ${use}` : tname.main, cite });
            const conf = cite?.conf !== null && cite?.conf !== undefined ? Math.round(cite.conf * 100) : null;
            return (
              <tr key={i} onClick={sel} data-path={path} className={`cursor-pointer ${active ? "bg-accent-subtle" : "hover:bg-subtle"}`}>
                <Td className="relative truncate py-1.5 pl-6">
                  <SelBar on={active} />
                  <div className="truncate font-medium text-fg" title={tname.main}>
                    {tname.main}
                  </div>
                  {sub && <div className="truncate text-xs text-fg-3">{sub}</div>}
                </Td>
                <Td className="py-1.5">
                  {use ? (
                    <div className="truncate text-fg-2" title={use}>
                      {use}
                    </div>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-fg-3" title="Use not recorded. Verify on site.">
                      <AlertTriangle size={12} className="text-warn" /> Unknown
                    </span>
                  )}
                </Td>
                <Td align="right" className="py-1.5 tabular-nums text-fg-2">
                  {!isUnknown(t.floor) ? String(t.floor) : ""}
                </Td>
                {showSf && (
                  <Td align="right" className="py-1.5 tabular-nums text-fg-2">
                    {typeof t.sqft === "number" ? t.sqft.toLocaleString() : ""}
                  </Td>
                )}
                {showEmp && (
                  <Td align="right" className="py-1.5 tabular-nums text-fg-2">
                    {!isUnknown(t.employees) ? String(t.employees) : ""}
                  </Td>
                )}
                <Td align="right" className="py-1.5 pr-6">
                  {cite && (
                    <span className="inline-flex h-5 items-center" title={`${sourceMeta(cite.src).label}${cite.id ? `, record ${cite.id}` : ""}${conf !== null ? `, ${conf}% confidence` : ""}`}>
                      <SourceGlyph src={cite.src} />
                    </span>
                  )}
                </Td>
              </tr>
            );
          })}
          {ranked.length > TENANT_PREVIEW && (
            <tr>
              <td colSpan={cols + 2} className="border-b border-line p-0">
                <button type="button" onClick={() => setAll((v) => !v)} className="w-full px-6 py-2 text-left text-xs font-medium text-accent hover:bg-subtle">
                  {all ? `Show top ${TENANT_PREVIEW} by area` : `Show all ${ranked.length} tenants`}
                </button>
              </td>
            </tr>
          )}
        </tbody>
        {footer.length > 0 && (
          <tfoot>
            {footer.map((f) => {
              const active = ctx.selected === f.path;
              const edited = ctx.edits[f.path];
              const isEdited = edited !== undefined && edited.trim() !== "";
              const cite = isEdited ? OFFICER_CITE : f.field.cite;
              const verify = !isEdited && f.field.verify;
              const text = isEdited ? edited : clean(fmtValue(f.field.value, f.path.split(".").pop()));
              const sel = () => ctx.onSelect({ path: f.path, label: f.label, value: verify ? VERIFY : text, cite: verify ? null : cite });
              return (
                <tr key={f.path} onClick={sel} data-path={f.path} className={`cursor-pointer bg-subtle ${active ? "bg-accent-subtle" : "hover:bg-muted"}`}>
                  <Td className="relative py-2 pl-6 text-xs text-fg-3">
                    <SelBar on={active} />
                    {f.label}
                  </Td>
                  <Td className="py-2" colSpan={cols}>
                    {ctx.editing ? <EditInput path={f.path} initial={verify ? "" : text} ctx={ctx} /> : verify ? <VerifyValue /> : <span className="text-fg">{text}</span>}
                  </Td>
                  <Td align="right" className="py-2 pr-6">
                    {cite && !verify && (
                      <span className="inline-flex h-5 items-center" title={`${sourceMeta(cite.src).label}${cite.conf !== null ? `, ${Math.round(cite.conf * 100)}% confidence` : ""}`}>
                        <SourceGlyph src={cite.src} />
                      </span>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tfoot>
        )}
      </table>
    </>
  );
}

/* ---------------- Hazards ---------------- */

const HAZARD_PREVIEW = 5;

function Hazards({ ctx, hazards }: { ctx: SheetCtx; hazards: Array<Record<string, unknown>> }) {
  const [all, setAll] = useState(false);
  const compact = useContext(Compact);
  if (!hazards.length) return <div className="border-y border-line px-6 py-3 text-sm text-fg-3">No hazards inferred.</div>;
  const ranked = hazards
    .map((h, i) => ({ h, i, conf: typeof h.conf === "number" ? h.conf : (normCite(h.cite)?.conf ?? 0) }))
    .sort((a, z) => z.conf - a.conf);
  const shown = all ? ranked : ranked.slice(0, HAZARD_PREVIEW);
  return (
    <>
    <table className="w-full table-fixed border-collapse">
      <colgroup>
        <col className="w-16" />
        <col />
        {!compact && <col className="w-[24%]" />}
        <col className="w-16" />
        <col className={compact ? "w-14" : "w-[120px]"} />
      </colgroup>
      <thead>
        <tr>
          <Th className="pl-6">Rank</Th>
          <Th>Hazard</Th>
          {!compact && <Th>Location</Th>}
          <Th align="right">Conf.</Th>
          <Th align="right" className="pr-6">
            {compact ? <span className="sr-only">Source</span> : "Source"}
          </Th>
        </tr>
      </thead>
      <tbody>
        {shown.map(({ h, i, conf }, rank) => {
          const path = `hazards.${i}`;
          const cite = normCite(h.cite, h.conf);
          const active = ctx.selected === path;
          const t = splitDetail(String(h.type ?? "Hazard"));
          const edited = ctx.edits[`${path}.location`];
          const loc = splitDetail(String(edited ?? h.location ?? ""));
          const reason = typeof h.reason === "string" ? clean(h.reason) : null;
          const tactics = typeof h.tactics === "string" ? clean(h.tactics) : null;
          const sel = () =>
            ctx.onSelect({
              path,
              label: loc.main ? `Hazard, ${loc.main}` : "Hazard",
              value: t.main,
              cite,
              reason: [reason ? sentenceEnd(reason) : null, tactics].filter(Boolean).join(" ") || undefined,
            });
          return (
            <tr key={i} onClick={sel} data-path={path} className={`cursor-pointer ${active ? "bg-accent-subtle" : "hover:bg-subtle"}`}>
              <Td className="relative pl-6 tabular-nums text-fg-3">
                <SelBar on={active} />
                {rank + 1}
              </Td>
              <Td>
                <div className="flex items-start gap-2">
                  <AlertTriangle size={14} strokeWidth={2.25} className="mt-[3px] shrink-0 text-danger" />
                  <div className="min-w-0">
                    <div className="font-medium text-fg">
                      {t.main}
                      {t.detail && <span className="ml-2 font-normal text-fg-2">{t.detail}</span>}
                    </div>
                    {compact && (loc.main || ctx.editing) && (
                      <div className="mt-0.5 text-xs text-fg">
                        {ctx.editing ? <EditInput path={`${path}.location`} initial={String(h.location ?? "")} ctx={ctx} /> : <>Location: {loc.main}</>}
                      </div>
                    )}
                    {tactics && <div className="mt-0.5 text-xs text-fg-2">{tactics}</div>}
                    {reason && <div className="mt-0.5 text-xs text-fg-3">Basis: {reason}</div>}
                  </div>
                </div>
              </Td>
              {!compact && (
              <Td className="text-fg-2">
                {ctx.editing ? (
                  <EditInput path={`${path}.location`} initial={String(h.location ?? "")} ctx={ctx} />
                ) : loc.main ? (
                  <>
                    {loc.main}
                    {loc.detail && <div className="text-xs text-fg-3">{loc.detail}</div>}
                  </>
                ) : (
                  <VerifyValue compact />
                )}
              </Td>
              )}
              <Td align="right" className="tabular-nums text-fg-2">
                {conf ? `${Math.round(conf * 100)}%` : ""}
              </Td>
              <Td align="right" className="pr-6">
                <HazardSource cite={cite} compact={compact} active={active} onClick={sel} />
              </Td>
            </tr>
          );
        })}
      </tbody>
    </table>
    {ranked.length > HAZARD_PREVIEW && (
      <button type="button" onClick={() => setAll((v) => !v)} className="w-full border-b border-line px-6 py-2 text-left text-xs font-medium text-accent hover:bg-subtle">
        {all ? "Show top 5 only" : `Show all ${ranked.length} hazards`}
      </button>
    )}
    </>
  );
}

/** Inference tag plus the upstream sources it was derived from (ring + diamond = inferred from Vexcel). */
function HazardSource({ cite, compact, active, onClick }: { cite: NormCite | null; compact: boolean; active: boolean; onClick: () => void }) {
  if (!cite) return <span className="text-2xs text-fg-4">No source</span>;
  const upstream = Array.from(new Set((cite.from ?? []).map((f) => f.split(/[.:]/)[0].toLowerCase()))).filter((x) => x !== cite.src && sourceMeta(x).label !== x);
  const title = `${sourceMeta(cite.src).label}${upstream.length ? `, derived from ${upstream.map((u) => sourceMeta(u).label).join(" and ")}` : ""}`;
  return (
    <span className="inline-flex items-center justify-end gap-1.5" title={title}>
      {compact ? (
        <SourceGlyph src={cite.src} />
      ) : (
        <SourceTag cite={cite} active={active} onClick={onClick} showConf={false} />
      )}
      {upstream.length > 0 && (
        <span className="inline-flex items-center gap-0.5" aria-label={title}>
          {upstream.map((u) => (
            <SourceGlyph key={u} src={u} size={7} />
          ))}
        </span>
      )}
    </span>
  );
}

const sentenceEnd = (s: string) => {
  const x = s.charAt(0).toUpperCase() + s.slice(1);
  return /[.!?]$/.test(x) ? x : `${x}.`;
};

/* ---------------- Exposures ---------------- */

function Exposures({ ctx, exposures }: { ctx: SheetCtx; exposures: Array<Record<string, unknown>> }) {
  const compact = useContext(Compact);
  if (!exposures.length) return <div className="border-y border-line px-6 py-3 text-sm text-fg-3">No exposures identified.</div>;
  return (
    <table className="w-full table-fixed border-collapse">
      <colgroup>
        <col className={compact ? "w-24" : "w-[128px]"} />
        <col />
        <col className={compact ? "w-[108px]" : "w-[132px]"} />
      </colgroup>
      <thead>
        <tr>
          <Th className="pl-6">Side</Th>
          <Th>Description</Th>
          <Th align="right" className="pr-6">
            Source
          </Th>
        </tr>
      </thead>
      <tbody>
        {exposures.map((x, i) => {
          const path = `exposures.${i}.desc`;
          const cite = normCite(x.cite);
          const active = ctx.selected === path;
          const desc = sentence(clean(String(x.desc ?? x.value ?? "")));
          const label = `${sideName(x.side)} exposure`;
          const sel = () => ctx.onSelect({ path, label, value: desc, cite });
          return (
            <tr key={i} onClick={sel} data-path={path} className={`cursor-pointer ${active ? "bg-accent-subtle" : "hover:bg-subtle"}`}>
              <Td className="relative pl-6 text-fg">
                <SelBar on={active} />
                {sideName(x.side)}
              </Td>
              <Td className="text-fg-2">{desc}</Td>
              <Td align="right" className="pr-6">
                <SourceTag cite={cite} active={active} onClick={sel} />
              </Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ---------------- Walk-through checklist ---------------- */

function Checklist({ ctx, items }: { ctx: SheetCtx; items: Array<{ path: string; label: string; section: string }> }) {
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  if (!items.length) return <div className="border-y border-line px-6 py-3 text-sm text-fg-3">Every field has a citable source.</div>;
  const done = items.filter((it) => checked[it.path] || (ctx.edits[it.path] ?? "").trim()).length;
  return (
    <div className="border-y border-line">
      <div className="flex items-center justify-between border-b border-line bg-subtle px-6 py-1.5 text-xs text-fg-3">
        <span>Item</span>
        <span className="tabular-nums">
          {done} of {items.length} confirmed
        </span>
      </div>
      {items.map((it) => {
        const edited = (ctx.edits[it.path] ?? "").trim();
        const isDone = !!checked[it.path] || !!edited;
        const active = ctx.selected === it.path;
        return (
          <div
            key={it.path}
            data-path={`check:${it.path}`}
            onClick={() => ctx.onSelect({ path: it.path, label: it.label, value: edited || VERIFY, cite: edited ? OFFICER_CITE : null })}
            className={`relative grid cursor-pointer grid-cols-[16px_minmax(96px,min(22%,168px))_minmax(0,1fr)_auto] items-center gap-4 border-b border-line px-6 py-2 last:border-b-0 ${
              active ? "bg-accent-subtle" : "hover:bg-subtle"
            }`}
          >
            <SelBar on={active} />
            <button
              type="button"
              aria-label={`Mark ${it.label} confirmed`}
              aria-pressed={isDone}
              onClick={(e) => {
                e.stopPropagation();
                setChecked((c) => ({ ...c, [it.path]: !c[it.path] }));
              }}
              className={`flex h-4 w-4 items-center justify-center rounded-sm border ${isDone ? "border-ok bg-ok text-white" : "border-line-strong bg-surface hover:border-fg-3"}`}
            >
              {isDone && <Check size={11} strokeWidth={3} />}
            </button>
            <span className={`text-sm ${isDone ? "text-fg-3 line-through" : "text-fg"}`}>{it.label}</span>
            <span className="truncate text-sm text-fg-2">{edited ? `Entered by officer: ${edited}` : <span className="text-fg-3">{it.section}</span>}</span>
            <span className="text-right text-xs">{isDone ? <span className="text-ok">Confirmed</span> : <VerifyValue compact />}</span>
          </div>
        );
      })}
    </div>
  );
}
