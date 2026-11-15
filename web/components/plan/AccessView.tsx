"use client";

// Access plan: base aerial + ladder-access walls, staging polygon and entry points,
// drawn as an SVG in the cited image's full-resolution pixel space (viewBox crop),
// so geometry from the backend maps 1:1 without any scaling math.

import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { KV, Mono } from "@/components/ui";
import { assetUrl } from "@/lib/api";
import { clean } from "@/lib/text";
import type { Plan } from "@/lib/types";

type Pt = [number, number];
interface Edge {
  id: number | string;
  side: string;
  px: [Pt, Pt];
  len_m?: number;
  conf?: number;
  reason?: string;
  verified?: boolean;
}
interface Entry {
  n: number;
  type: string;
  side?: string;
  value?: string;
  conf?: number;
  verified?: boolean;
  cite?: { bbox?: [number, number, number, number]; img_w?: number; img_h?: number; url?: string; oblique?: string; shows_facade?: string };
  ortho_point?: { px?: Pt; approx?: boolean };
}

export type AccessFocus = { kind: "roof" } | { kind: "staging" } | { kind: "entry"; n: number } | { kind: "summary" };

/** Colors: ladder = success green, staging = accent, entries = small categorical set. Bright variants for legibility on imagery. */
const C = {
  ladder: "#2fbf6b",
  ladderHalo: "rgba(10,30,18,0.65)",
  staging: "#3d7bff",
  entry: { overhead: "#f2b33d", entrance: "#ffffff", exit: "#ef6a62" } as Record<string, string>,
};

const ENTRY_KIND: Record<string, "overhead" | "entrance" | "exit"> = {
  dock_door: "overhead",
  drive_in: "overhead",
  rollup: "overhead",
  entrance: "entrance",
  exit: "exit",
};
const ENTRY_LABEL: Record<string, string> = { dock_door: "Dock door", drive_in: "Drive-in door", rollup: "Roll-up door", entrance: "Entrance", exit: "Exit" };
export const entryLabel = (t: string) => ENTRY_LABEL[t] ?? t.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(380);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width || 380));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function accessData(plan: Plan | null) {
  const a = (plan?.access ?? {}) as Record<string, unknown>;
  const roof = (a.roof_access ?? {}) as Record<string, unknown>;
  const staging = (a.staging ?? {}) as Record<string, unknown>;
  const rg = (roof.geometry ?? null) as Record<string, unknown> | null;
  const sg = (staging.geometry ?? null) as Record<string, unknown> | null;
  const entries = (Array.isArray(a.entries) ? a.entries : []) as Entry[];
  const media = (plan?.media ?? {}) as Record<string, unknown>;
  const base = (rg ?? sg) as Record<string, unknown> | null;
  const value = typeof roof.value === "string" ? roof.value : "";
  const highRise = roof.high_rise === true || /beyond (the )?aerial ladder reach|high-rise/i.test(value);
  return {
    edges: (Array.isArray(rg?.edges) ? rg.edges : []) as Edge[],
    staging: Array.isArray(sg?.px) ? (sg.px as Pt[]) : null,
    entries,
    image: base && typeof base.image_url === "string" ? { url: base.image_url, w: Number(base.img_w) || 0, h: Number(base.img_h) || 0 } : null,
    annotated: (typeof media.access_annotated_url === "string" ? media.access_annotated_url : null) ?? (typeof rg?.annotated_url === "string" ? rg.annotated_url : null),
    highRise,
    heightM: typeof roof.height_m === "number" ? roof.height_m : null,
    summary: (a.entries_summary ?? null) as { value?: string; counts?: Record<string, Record<string, number>>; costar_loading_docks?: number | null } | null,
  };
}

export function hasAccessGeometry(plan: Plan | null) {
  const d = accessData(plan);
  return !!d.image || !!d.annotated;
}

export function AccessView({ plan, focus }: { plan: Plan | null; focus: AccessFocus }) {
  const d = useMemo(() => accessData(plan), [plan]);
  const [edgeSel, setEdgeSel] = useState<Edge | null>(null);
  const [entrySel, setEntrySel] = useState<number | null>(focus.kind === "entry" ? focus.n : null);
  const [oblique, setOblique] = useState(focus.kind === "entry");
  const [ref, width] = useWidth<HTMLDivElement>();
  const [imgOk, setImgOk] = useState(true);

  // crop: bounding box of all geometry + margin, clamped to the image
  const view = useMemo(() => {
    if (!d.image?.w) return null;
    const pts: Pt[] = [...d.edges.flatMap((e) => e.px), ...(d.staging ?? []), ...d.entries.map((e) => e.ortho_point?.px).filter((p): p is Pt => !!p)];
    if (!pts.length) return null;
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const m = Math.max(x1 - x0, y1 - y0) * 0.14 + 60;
    x0 -= m; x1 += m; y0 -= m; y1 += m;
    // aim for a 4:3-ish frame
    const w = x1 - x0, h = y1 - y0;
    if (w / h < 1.15) { const add = (h * 1.15 - w) / 2; x0 -= add; x1 += add; }
    x0 = Math.max(0, x0); y0 = Math.max(0, y0);
    x1 = Math.min(d.image.w, x1); y1 = Math.min(d.image.h, y1);
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }, [d]);

  const entry = d.entries.find((e) => e.n === entrySel) ?? null;

  if (!view || !d.image || !imgOk) {
    const fb = assetUrl(d.annotated);
    return fb ? (
      <figure>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={fb} alt="Access plan" className="w-full rounded border border-line" />
        <figcaption className="mt-2 text-xs text-fg-3">Access plan, pre-drawn by the agent. Vexcel imagery.</figcaption>
      </figure>
    ) : (
      <p className="text-sm text-fg-3">No access geometry for this building.</p>
    );
  }

  const u = view.w / Math.max(width, 1); // image px per screen px
  const sides = Array.from(new Set(d.edges.map((e) => e.side)));
  const placed: Array<{ x: number; y: number }> = [];
  const sideLabel = sides
    .map((s) => {
      const longest = d.edges.filter((e) => e.side === s).sort((a, z) => (z.len_m ?? 0) - (a.len_m ?? 0))[0];
      const [[ax, ay], [bx, by]] = longest.px;
      return { side: s, x: (ax + bx) / 2, y: (ay + by) / 2, edge: longest };
    })
    .sort((a, z) => (z.edge.len_m ?? 0) - (a.edge.len_m ?? 0))
    .map((l) => {
      // nudge labels that would overlap one already placed (screen space ~ 80 x 22 px)
      let y = l.y;
      for (let k = 0; k < 6 && placed.some((p) => Math.abs(p.x - l.x) < 80 * u && Math.abs(p.y - y) < 22 * u); k++) y += 22 * u;
      placed.push({ x: l.x, y });
      return { ...l, y };
    });
  const anyUnverified = d.edges.some((e) => e.verified === false);
  const focusRoof = focus.kind === "roof" || focus.kind === "summary";
  const focusStaging = focus.kind === "staging";

  if (oblique && entry?.cite?.url) {
    return <ObliqueView entry={entry} onBack={() => setOblique(false)} />;
  }

  return (
    <figure>
      {d.highRise && (
        <p className="mb-2 border-l-2 border-danger bg-danger-subtle px-3 py-1.5 text-xs text-fg">
          <span className="font-semibold">Roof beyond aerial ladder reach{d.heightM ? ` (${Math.round(d.heightM)} m)` : ""}.</span> Use interior stairs. Green walls are apparatus set-up positions.
        </p>
      )}
      <div ref={ref} className="relative overflow-hidden rounded border border-line bg-muted">
        <svg viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} className="block w-full" style={{ aspectRatio: `${view.w} / ${view.h}` }} role="img" aria-label="Access plan">
          <image href={assetUrl(d.image.url) ?? ""} x={0} y={0} width={d.image.w} height={d.image.h} onError={() => setImgOk(false)} />
          {/* staging */}
          {d.staging && (
            <g opacity={focusStaging || focusRoof || focus.kind === "entry" ? 1 : 1}>
              <polygon points={d.staging.map((p) => p.join(",")).join(" ")} fill="rgba(61,123,255,0.30)" stroke={C.staging} strokeWidth={(focusStaging ? 3 : 2) * u} strokeLinejoin="round">
                <title>Staging area</title>
              </polygon>
            </g>
          )}
          {/* ladder walls */}
          {d.edges.map((e) => {
            const [[ax, ay], [bx, by]] = e.px;
            const sel = edgeSel?.id === e.id;
            const w = (sel ? 7 : focusRoof ? 5.5 : 4.5) * u;
            return (
              <g key={String(e.id)} onClick={() => setEdgeSel(sel ? null : e)} className="cursor-pointer">
                <line x1={ax} y1={ay} x2={bx} y2={by} stroke={C.ladderHalo} strokeWidth={w + 3 * u} strokeLinecap="round" />
                <line x1={ax} y1={ay} x2={bx} y2={by} stroke={C.ladder} strokeWidth={w} strokeLinecap="round" strokeDasharray={e.verified === false ? `${8 * u} ${6 * u}` : undefined} />
                <line x1={ax} y1={ay} x2={bx} y2={by} stroke="transparent" strokeWidth={18 * u}>
                  <title>{`Ladder access, ${e.side} wall, ${e.len_m ?? "?"} m, ${Math.round((e.conf ?? 0) * 100)}% confidence${e.verified === false ? ", unverified" : ""}`}</title>
                </line>
              </g>
            );
          })}
          {/* side labels */}
          {sideLabel.map((l) => {
            const text = `${d.highRise ? "Apparatus" : "Ladder"} ${l.side}`;
            const fs = 11 * u;
            const tw = text.length * fs * 0.58 + 10 * u;
            return (
              <g key={l.side} transform={`translate(${l.x},${l.y})`} pointerEvents="none">
                <rect x={-tw / 2} y={-9 * u} width={tw} height={18 * u} rx={3 * u} fill="#1f7a45" stroke="#ffffff" strokeWidth={1 * u} />
                <text x={0} y={4 * u} textAnchor="middle" fontSize={fs} fontWeight={600} fill="#ffffff" fontFamily="var(--font-sans)">
                  {text}
                </text>
              </g>
            );
          })}
          {d.staging && (() => {
            const cx = d.staging.reduce((s, p) => s + p[0], 0) / d.staging.length;
            const cy = d.staging.reduce((s, p) => s + p[1], 0) / d.staging.length;
            const fs = 11 * u;
            const tw = 7 * fs * 0.58 + 10 * u;
            return (
              <g transform={`translate(${cx},${cy})`} pointerEvents="none">
                <rect x={-tw / 2} y={-9 * u} width={tw} height={18 * u} rx={3 * u} fill={C.staging} stroke="#ffffff" strokeWidth={1 * u} />
                <text x={0} y={4 * u} textAnchor="middle" fontSize={fs} fontWeight={600} fill="#ffffff" fontFamily="var(--font-sans)">
                  Staging
                </text>
              </g>
            );
          })()}
          {/* entries */}
          {d.entries.map((e) => {
            const p = e.ortho_point?.px;
            if (!p) return null;
            const kind = ENTRY_KIND[e.type] ?? "entrance";
            const sel = e.n === entrySel;
            const r = (sel ? 10 : 7.5) * u;
            return (
              <g
                key={e.n}
                transform={`translate(${p[0]},${p[1]})`}
                className="cursor-pointer"
                onClick={() => {
                  setEntrySel(e.n);
                  setOblique(!!e.cite?.url);
                }}
              >
                <title>{`${e.n}. ${entryLabel(e.type)}, ${e.side ?? ""} side${e.value ? `: ${e.value}` : ""}. Position approximate; open to see the door in the oblique image.`}</title>
                {sel && <circle r={r + 4 * u} fill="none" stroke="#ffffff" strokeWidth={2 * u} />}
                <circle r={r} fill={C.entry[kind]} stroke="#16191d" strokeWidth={1.5 * u} />
                <text y={3.8 * u} textAnchor="middle" fontSize={(sel ? 11 : 9.5) * u} fontWeight={700} fill="#16191d" fontFamily="var(--font-sans)">
                  {e.n}
                </text>
              </g>
            );
          })}
        </svg>
        <span className="pointer-events-none absolute bottom-1 right-1.5 text-[10px] text-white/85 [text-shadow:0_1px_2px_rgba(0,0,0,.6)]">Vexcel</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-fg-2">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-[3px] w-4 rounded-sm" style={{ background: C.ladder }} /> {d.highRise ? "Apparatus set-up" : "Ladder access"}
        </span>
        {anyUnverified && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-0 w-4 border-t-[3px] border-dashed" style={{ borderColor: C.ladder }} /> Unverified
          </span>
        )}
        {d.staging && (
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm border" style={{ background: "rgba(61,123,255,0.3)", borderColor: C.staging }} /> Staging
          </span>
        )}
        {(["overhead", "entrance", "exit"] as const)
          .filter((k) => d.entries.some((e) => (ENTRY_KIND[e.type] ?? "entrance") === k))
          .map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full border border-fg" style={{ background: C.entry[k] }} />
              {k === "overhead" ? "Overhead door" : k === "entrance" ? "Entrance" : "Exit"}
            </span>
          ))}
      </div>
      <figcaption className="mt-1 flex items-center justify-between gap-2 text-xs text-fg-3">
        <span>Select a wall for its reason, or an entry to see the door in the oblique image.</span>
        <span className="shrink-0">North up</span>
      </figcaption>
      {d.entries.length > 0 && (
        <p className="mt-1 text-2xs text-fg-3">Entry positions are approximate, projected from oblique imagery onto the footprint.</p>
      )}

      {edgeSel && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs font-medium text-fg-2">Ladder access, {edgeSel.side} wall</h3>
          <div className="border-t border-line">
            <KV
              labelWidth={96}
              rows={[
                ["Reason", clean(edgeSel.reason ?? "")],
                ["Wall length", edgeSel.len_m ? <span className="tabular-nums">{edgeSel.len_m} m</span> : "Not reported"],
                ["Confidence", <span key="c" className="tabular-nums">{Math.round((edgeSel.conf ?? 0) * 100)}%</span>],
                ["Verified", edgeSel.verified === false ? "No, needs confirmation" : "Yes, second-pass check"],
                ["Edge", <Mono key="id">#{String(edgeSel.id)}</Mono>],
              ]}
            />
          </div>
        </div>
      )}
      {entry && !oblique && entry.cite?.url && (
        <button onClick={() => setOblique(true)} className="mt-3 text-xs font-medium text-accent hover:underline">
          View entry {entry.n} in the oblique image
        </button>
      )}
    </figure>
  );
}

function ObliqueView({ entry, onBack }: { entry: Entry; onBack: () => void }) {
  const c = entry.cite!;
  const [b0, b1, b2, b3] = c.bbox ?? [0, 0, 0, 0];
  const W = c.img_w ?? 1;
  const H = c.img_h ?? 1;
  const pad = Math.max(b2 - b0, b3 - b1) * 0.35;
  // frame the door with context: about 7x the box, at least 480 px, 4:3, clamped to the image
  const [full, setFull] = useState(false);
  const cx = (b0 + b2) / 2, cy = (b1 + b3) / 2;
  const fw = Math.min(W, Math.max(480, (b2 - b0) * 7));
  const fh = Math.min(H, fw * 0.75);
  const vx = Math.max(0, Math.min(W - fw, cx - fw / 2));
  const vy = Math.max(0, Math.min(H - fh, cy - fh / 2));
  const vb = full || !c.bbox ? { x: 0, y: 0, w: W, h: H } : { x: vx, y: vy, w: fw, h: fh };
  return (
    <figure>
      <button onClick={onBack} className="mb-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
        <ArrowLeft size={12} /> Access plan
      </button>
      <div className="relative overflow-hidden rounded border border-line bg-muted">
        <svg viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} className="block w-full" style={{ aspectRatio: `${vb.w} / ${vb.h}` }} role="img" aria-label={`Oblique image, ${entryLabel(entry.type)}`}>
          <image href={assetUrl(c.url) ?? ""} x={0} y={0} width={W} height={H} />
          {c.bbox && (
            <rect x={b0 - pad} y={b1 - pad} width={b2 - b0 + 2 * pad} height={b3 - b1 + 2 * pad} fill="rgba(61,123,255,0.12)" stroke="#3d7bff" strokeWidth={vb.w / 180} />
          )}
        </svg>
        <span className="pointer-events-none absolute bottom-1 right-1.5 text-[10px] text-white/85 [text-shadow:0_1px_2px_rgba(0,0,0,.6)]">Vexcel oblique</span>
      </div>
      <figcaption className="mt-2 flex items-start justify-between gap-3 text-xs text-fg-3">
        <span>
          {entry.n}. {entryLabel(entry.type)}, {entry.side} side. Oblique {c.oblique ?? ""}
          {c.shows_facade ? `, looking at the ${c.shows_facade} facade` : ""}.
        </span>
        {c.bbox && (
          <button onClick={() => setFull((v) => !v)} className="shrink-0 font-medium text-accent hover:underline">
            {full ? "Zoom to door" : "Full image"}
          </button>
        )}
      </figcaption>
    </figure>
  );
}
