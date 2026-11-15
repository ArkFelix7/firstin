"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { KV, Mono, PanelHeader, SourceGlyph, SourceTag, VerifyValue } from "@/components/ui";
import { assetUrl } from "@/lib/api";
import { mockAerialUrl, mockCostarRecord, MOCK_MATTERPORT_MODEL } from "@/lib/mock";
import { normCite, sourceMeta, type NormCite } from "@/lib/plan";
import { clean, sentence, splitDetail } from "@/lib/text";
import type { Building, Plan } from "@/lib/types";
import { PanoViewer } from "./PanoViewer";
import type { Selection } from "./PlanSheet";

interface Props {
  selection: Selection | null;
  plan: Plan | null;
  building: Building | null;
  evidence: Record<string, Record<string, unknown>>;
  mock: boolean;
  onNavigate: (s: Selection) => void;
}

/** Every cited fact in the plan, flattened. Used to overlay all boxes on a tile. */
function collectCites(plan: Plan | null): Array<{ path: string; label: string; cite: NormCite }> {
  const out: Array<{ path: string; label: string; cite: NormCite }> = [];
  const walk = (x: unknown, path: string, key: string) => {
    if (Array.isArray(x)) return x.forEach((y, i) => walk(y, `${path}.${i}`, key));
    if (!x || typeof x !== "object") return;
    const o = x as Record<string, unknown>;
    if ("cite" in o) {
      const c = normCite(o.cite, o.conf);
      const label = String(o.type ?? o.loc ?? (o.side ? `${o.side} exposure` : null) ?? o.name ?? key.replace(/_/g, " "));
      if (c) out.push({ path, label: sentence(splitDetail(clean(label)).main), cite: c });
      return;
    }
    for (const [k, v] of Object.entries(o)) walk(v, path ? `${path}.${k}` : k, k);
  };
  walk(plan, "", "");
  return out;
}

export function EvidenceViewer({ selection, plan, building, evidence, mock, onNavigate }: Props) {
  const cite = selection?.cite ?? null;
  const src = cite?.src ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PanelHeader title="Evidence">{cite && <SourceTag cite={cite} showConf={false} />}</PanelHeader>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div key={selection?.path ?? "empty"} className="p-4">
          {!selection ? (
            <Empty evidence={evidence} />
          ) : (
            <>
              <FactHeader selection={selection} />
              <div className="mt-4">
                {!cite ? (
                  <NoEvidence />
                ) : src === "vexcel" ? (
                  <VexcelView cite={cite} plan={plan} building={building} mock={mock} evidence={evidence} selectedPath={selection.path} />
                ) : src === "matterport" ? (
                  <MatterportView key={selection.path} cite={cite} building={building} evidence={evidence} label={selection.label} value={selection.value} plan={plan} />
                ) : src === "costar" ? (
                  <CostarView cite={cite} building={building} evidence={evidence} mock={mock} selection={selection} />
                ) : src === "officer" ? (
                  <p className="border-l-2 border-ok pl-3 text-sm text-fg-2">Entered by the approving officer. The edit is logged with the approval and replaces the agent value in the published plan.</p>
                ) : (
                  <InferenceView key={selection.path} cite={cite} selection={selection} plan={plan} building={building} evidence={evidence} mock={mock} onNavigate={onNavigate} />
                )}
              </div>
              <CiteMeta cite={cite} evidence={evidence} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function FactHeader({ selection }: { selection: Selection }) {
  const v = splitDetail(clean(selection.value));
  const verify = /verify\s+on\s+site/i.test(selection.value);
  return (
    <div>
      <div className="text-xs text-fg-3">{selection.label}</div>
      <div className={`mt-0.5 text-fg ${v.main.length > 80 ? "text-sm" : "text-lg font-semibold"}`}>
        {verify ? <VerifyValue /> : v.main}
      </div>
      {v.detail && !verify && <div className="text-sm text-fg-2">{v.detail}</div>}
      <Mono className="mt-1 block text-fg-4">{selection.path}</Mono>
    </div>
  );
}

function CiteMeta({ cite, evidence }: { cite: NormCite | null; evidence: Record<string, Record<string, unknown>> }) {
  if (!cite) return null;
  const raw = cite.raw as Record<string, unknown>;
  const captured = raw.captured_at ?? raw.captured ?? raw.date ?? (cite.src === "vexcel" ? (evidence.vexcel?.captured_at ?? null) : null);
  const conf = cite.conf !== null ? Math.round(cite.conf * 100) : null;
  const rows: Array<[string, React.ReactNode]> = [
    [
      "Source",
      <span key="s" className="inline-flex items-center gap-1.5">
        <SourceGlyph src={cite.src} />
        {sourceMeta(cite.src).label}
      </span>,
    ],
    ["Record ID", cite.id ? <Mono className="break-all">{cite.id}</Mono> : <span className="text-fg-4">None</span>],
    [
      "Confidence",
      conf !== null ? (
        <span className="flex items-center gap-2">
          <span className="tabular-nums">{conf}%</span>
          <span className="h-1 w-20 overflow-hidden rounded-sm bg-muted">
            <span className="block h-full bg-fg-2" style={{ width: `${conf}%` }} />
          </span>
        </span>
      ) : (
        <span className="text-fg-4">Not reported</span>
      ),
    ],
    ["Captured", captured ? String(captured) : <span className="text-fg-4">Not reported</span>],
  ];
  if (typeof raw.field === "string") rows.push(["Source field", <Mono key="f" className="break-all">{raw.field}</Mono>]);
  if (cite.bbox) rows.push(["Region", <Mono key="b">[{cite.bbox.map((n) => Math.round(n * 100) / 100).join(", ")}]</Mono>]);
  if (cite.from) rows.push(["Derived from", <Mono key="d" className="break-all">{cite.from.join(", ")}</Mono>]);
  return (
    <div className="mt-6">
      <h3 className="mb-1 text-xs font-medium text-fg-2">Citation</h3>
      <div className="border-t border-line">
        <KV rows={rows} labelWidth={96} />
      </div>
    </div>
  );
}

const TOOL_LABEL: Record<string, string> = {
  costar_property: "CoStar property record",
  costar_tenants: "CoStar tenants",
  vexcel_tile: "Aerial tile",
  vexcel_tile_at: "Aerial tile",
  vexcel_roof: "Roof analysis",
  vexcel_roof_at: "Roof analysis",
  vexcel_footprint: "Building footprint",
  vexcel_oblique: "Oblique imagery",
  vexcel_oblique_at: "Oblique imagery",
  analyze_aerial_image: "Aerial image analysis",
  analyze_interior_image: "Interior scan analysis",
  describe_image: "Image analysis",
  matterport_model: "Matterport model",
  matterport_panoramas: "Scan panoramas",
};

/** "/evidence/matterport/analyze_interior_image_2.json" -> "Interior scan analysis #2". */
function evidenceLabel(path: string, fallbackSrc: string): { label: string; src: string } {
  const m = path.match(/\/evidence\/(?:([a-z]+)\/)?([a-z_]+?)(?:_(\d+))?\.json$/i);
  if (!m) return { label: sourceMeta(fallbackSrc).label + " evidence", src: fallbackSrc };
  const src = (m[1] ?? fallbackSrc).toLowerCase();
  const base = TOOL_LABEL[m[2]] ?? (m[2] === src ? `${sourceMeta(src).label} evidence` : m[2].replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()));
  return { label: m[3] ? `${base} #${m[3]}` : base, src };
}

function Empty({ evidence }: { evidence: Record<string, Record<string, unknown>> }) {
  const files = Object.entries(evidence).flatMap(([k, v]) => {
    const paths = Object.keys((v.files as Record<string, unknown>) ?? {});
    return (paths.length ? paths : [String(v.path ?? `/evidence/${k}.json`)]).map((path) => ({ path, ...evidenceLabel(path, k) }));
  });
  return (
    <div>
      <p className="text-sm text-fg-2">Select a field in the plan to open the record, aerial tile or scan location it was taken from.</p>
      <div className="mt-6">
        <h3 className="mb-1 flex items-baseline justify-between text-xs font-medium text-fg-2">
          Evidence gathered by the agent
          {files.length > 0 && <span className="font-normal tabular-nums text-fg-3">{files.length} files</span>}
        </h3>
        {files.length === 0 ? (
          <p className="border-t border-line pt-2 text-sm text-fg-3">None yet.</p>
        ) : (
          <ul className="border-t border-line">
            {files.map((f) => (
              <li key={f.path} className="flex items-start gap-2 border-b border-line py-1.5" title={f.path}>
                <span className="mt-1.5">
                  <SourceGlyph src={f.src} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-fg">{f.label}</span>
                  <Mono className="block truncate text-fg-4">{f.path}</Mono>
                </span>
                <span className="shrink-0 pt-0.5 text-2xs text-fg-3">{sourceMeta(f.src).label}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function NoEvidence() {
  return (
    <div className="border-l-2 border-warn pl-3">
      <div className="text-sm">
        <VerifyValue />
      </div>
      <p className="mt-1 text-sm text-fg-2">
        No record in CoStar, Vexcel or Matterport supports this field, so the agent did not fill it. It is on the walk-through checklist. Enter the confirmed value in edit mode.
      </p>
    </div>
  );
}

const isImageUrl = (u: unknown): u is string => typeof u === "string" && /\.(jpe?g|png|webp)(\?|$)/i.test(u);

/* ---------------- Vexcel ---------------- */

function VexcelView({
  cite,
  plan,
  building,
  mock,
  evidence,
  selectedPath,
  annotated = false,
}: {
  cite: NormCite;
  plan: Plan | null;
  building: Building | null;
  mock: boolean;
  evidence: Record<string, Record<string, unknown>>;
  selectedPath: string;
  /** Show the agent's annotated ortho (detections drawn in) instead of the raw tile. */
  annotated?: boolean;
}) {
  const media = plan?.media as Record<string, unknown> | undefined;
  const annotatedUrl = annotated && typeof media?.aerial_url === "string" && /annotated/.test(media.aerial_url) ? assetUrl(media.aerial_url) : null;
  const url =
    annotatedUrl ??
    (isImageUrl(cite.url) ? assetUrl(cite.url) : null) ??
    assetUrl(media?.aerial_raw_url) ??
    assetUrl(media?.aerial_url) ??
    assetUrl(evidence.vexcel?.url ?? evidence.vexcel?.image_url) ??
    (building ? mockAerialUrl(building) : null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const boxes = useMemo(() => collectCites(plan).filter((c) => c.cite.src === "vexcel" && c.cite.bbox && (c.cite.id === cite.id || !cite.id)), [plan, cite.id]);
  const all = [...boxes];
  if (!all.some((b) => selectedPath.startsWith(b.path) || b.path.startsWith(selectedPath)) && cite.bbox) all.push({ path: selectedPath, label: "", cite });
  const W = dims?.w ?? 1024;
  const H = dims?.h ?? 1024;
  // bbox may be normalized (0 to 1), pixels in the cite's own image space (img_w/img_h), or pixels of the displayed image.
  const pct = (c: NormCite) => {
    const bb = c.bbox!;
    if (bb.every((n) => n <= 1.0001)) return bb.map((n) => n * 100);
    const iw = Number(c.raw.img_w) || W;
    const ih = Number(c.raw.img_h) || H;
    return bb.map((n, i) => (i % 2 ? (n / ih) * 100 : (n / iw) * 100));
  };

  return (
    <figure>
      <div className="relative overflow-hidden rounded border border-line bg-muted">
        {url && !failed ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={url}
            alt="Vexcel aerial tile"
            className="block w-full"
            onLoad={(e) => setDims({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            onError={() => setFailed(true)}
          />
        ) : (
          <div className="flex aspect-square items-center justify-center text-sm text-fg-3">Aerial tile unavailable</div>
        )}
        {dims &&
          !annotatedUrl &&
          all.map((b, i) => {
            const [x0, y0, x1, y1] = pct(b.cite);
            const sel = selectedPath === b.path || selectedPath.startsWith(b.path + ".") || b.path.startsWith(selectedPath + ".");
            return (
              <div
                key={i}
                title={b.label}
                className={`pointer-events-none absolute ${sel ? "z-10 border-2 border-[#3d7bff]" : "border border-dashed border-white/70"}`}
                style={{ left: `${x0}%`, top: `${y0}%`, width: `${x1 - x0}%`, height: `${y1 - y0}%` }}
              >
                {sel && b.label && (
                  <span className="absolute -top-5 left-[-2px] whitespace-nowrap rounded-sm bg-[#3d7bff] px-1.5 text-2xs font-medium leading-5 text-white">{b.label}</span>
                )}
              </div>
            );
          })}
      </div>
      <figcaption className="mt-2 flex items-center justify-between gap-2 text-xs text-fg-3">
        <span>
          {annotatedUrl ? "Annotated aerial tile with the agent's detections" : all.length ? `${all.length} detection${all.length === 1 ? "" : "s"} on this tile${mock ? ", cached" : ""}` : "Vexcel aerial tile"}
        </span>
        <span>North up</span>
      </figcaption>
    </figure>
  );
}

/* ---------------- Matterport ---------------- */

declare global {
  interface Window {
    MP_SDK?: { connect: (...args: unknown[]) => Promise<MpSdk> };
  }
}
interface MpSdk {
  Sweep: { moveTo: (id: string, opts?: Record<string, unknown>) => Promise<unknown>; Transition?: Record<string, unknown> };
}

const SDK_KEY = process.env.NEXT_PUBLIC_MATTERPORT_SDK_KEY;

function MatterportView({
  cite,
  building,
  evidence,
  label,
  value,
  plan,
}: {
  cite: NormCite;
  building: Building | null;
  evidence: Record<string, Record<string, unknown>>;
  label: string;
  value: string;
  plan: Plan | null;
}) {
  const urlModel = typeof cite.url === "string" ? cite.url.match(/[?&]m=([A-Za-z0-9]+)/)?.[1] : undefined;
  const model = cite.model ?? urlModel ?? (evidence.matterport?.model_id as string | undefined) ?? building?.matterport_model_ids?.[0] ?? MOCK_MATTERPORT_MODEL;
  // Pano: the cited image, else the nearest cached pano for this model/room type (from /evidence/matterport.json).
  const direct = isImageUrl(cite.url) ? assetUrl(cite.url) : null;
  const nearest = useMemo(() => {
    if (direct) return null;
    const contents = [evidence.matterport?.content, ...Object.values((evidence.matterport?.files as Record<string, unknown>) ?? {})].filter(
      (c): c is Record<string, unknown> => !!c && typeof c === "object",
    );
    const analyses = contents
      .flatMap((c) => [...((c.pano_analyses as Array<Record<string, unknown>>) ?? []), ...((c.panos as Array<Record<string, unknown>>) ?? [])])
      .filter((a) => typeof a.image_url === "string");
    const text = `${label} ${value}`.toLowerCase();
    const want = /stair/.test(text) ? "staircase" : /util|mech|elec|basement/.test(text) ? "utility" : /lobby|entr/.test(text) ? "lobby" : null;
    const byModel = (a: Record<string, unknown>) => String(a.image_url).includes(model);
    const pick = analyses.find((a) => byModel(a) && want && String(a.room).includes(want)) ?? analyses.find((a) => want && String(a.room).includes(want)) ?? analyses.find(byModel);
    if (pick) return { url: assetUrl(pick.image_url), room: `${pick.room ?? "Panorama"}${pick.floor !== undefined ? `, floor ${pick.floor}` : ""}` };
    const media = plan?.media as Record<string, unknown> | undefined;
    const urls = (media?.pano_urls as string[] | undefined) ?? [];
    const u = urls.find((x) => x.includes(model)) ?? urls[0];
    return u ? { url: assetUrl(u), room: "Nearest scan panorama" } : null;
  }, [direct, evidence.matterport, label, value, model, plan?.media]);
  const pano = direct ?? nearest?.url ?? null;
  const [tab, setTab] = useState<"pano" | "3d">(pano ? "pano" : "3d");
  const iframe = useRef<HTMLIFrameElement>(null);
  const sweep = cite.id;
  const room = typeof cite.raw.room === "string" && !nearest ? cite.raw.room : (nearest?.room ?? null);

  const src = `https://my.matterport.com/show/?m=${encodeURIComponent(model)}&play=1&qs=1&brand=0&help=0&title=0&mls=2${SDK_KEY ? `&applicationKey=${SDK_KEY}` : ""}`;

  // Optional: Showcase SDK deep-link to the cited sweep (localhost only).
  useEffect(() => {
    if (!SDK_KEY || tab !== "3d" || !sweep) return;
    let cancelled = false;
    const run = async () => {
      if (!window.MP_SDK) {
        await new Promise<void>((res, rej) => {
          const s = document.createElement("script");
          s.src = "https://static.matterport.com/showcase-sdk/latest.js";
          s.onload = () => res();
          s.onerror = () => rej();
          document.head.appendChild(s);
        });
      }
      if (cancelled || !iframe.current || !window.MP_SDK) return;
      const sdk = await window.MP_SDK.connect(iframe.current, SDK_KEY, "");
      if (!cancelled) await sdk.Sweep.moveTo(sweep, { transition: sdk.Sweep.Transition?.FLY });
    };
    const onLoad = () => run().catch(() => undefined);
    const el = iframe.current;
    el?.addEventListener("load", onLoad);
    return () => {
      cancelled = true;
      el?.removeEventListener("load", onLoad);
    };
  }, [tab, sweep]);

  return (
    <figure>
      {pano && (
        <div className="mb-2 inline-flex rounded border border-line-strong p-0.5" role="tablist">
          {(
            [
              ["pano", "360° panorama"],
              ["3d", "3D model"],
            ] as const
          ).map(([k, l]) => (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              onClick={() => setTab(k)}
              className={`h-6 rounded-sm px-2.5 text-xs font-medium ${tab === k ? "bg-muted text-fg" : "text-fg-3 hover:text-fg"}`}
            >
              {l}
            </button>
          ))}
        </div>
      )}
      <div className="relative overflow-hidden rounded border border-line bg-muted">
        {tab === "pano" && pano ? (
          <PanoViewer url={pano} bbox={cite.bbox} label={label} imgW={Number(cite.raw.img_w) || undefined} imgH={Number(cite.raw.img_h) || undefined} />
        ) : (
          <iframe ref={iframe} title="Matterport 3D model" src={src} className="block aspect-[4/3] w-full" allow="fullscreen; xr-spatial-tracking; autoplay" allowFullScreen />
        )}
      </div>
      <figcaption className="mt-2 flex items-center justify-between gap-2 text-xs text-fg-3">
        <span className="truncate">{room ? clean(room) : "Scan location"}</span>
        <span className="shrink-0">
          Model <Mono>{model}</Mono>
        </span>
      </figcaption>
    </figure>
  );
}

/* ---------------- CoStar ---------------- */

function CostarView({
  cite,
  building,
  evidence,
  mock,
  selection,
}: {
  cite: NormCite;
  building: Building | null;
  evidence: Record<string, Record<string, unknown>>;
  mock: boolean;
  selection: Selection;
}) {
  const fromEvidence = useMemo(() => {
    const files = evidence.costar?.files as Record<string, unknown> | undefined;
    if (files && Object.keys(files).length > 1) {
      // agent mode writes /evidence/costar/<tool>.json per call: show them side by side
      return Object.fromEntries(Object.entries(files).map(([path, c]) => [path.split("/").pop()?.replace(/\.json$/, "") ?? path, c]));
    }
    return (evidence.costar?.content ?? evidence.costar?.record ?? evidence.costar?.data ?? null) as Record<string, unknown> | null;
  }, [evidence.costar]);
  const fetchUrl = !fromEvidence && cite.url && /\.json($|\?)/.test(cite.url) ? assetUrl(cite.url) : null;
  const [fetched, setFetched] = useState<{ url: string; data: Record<string, unknown> } | null>(null);
  useEffect(() => {
    if (!fetchUrl) return;
    let alive = true;
    fetch(fetchUrl)
      .then((r) => r.json())
      .then((d) => alive && setFetched({ url: fetchUrl, data: d }))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [fetchUrl]);

  const record = fromEvidence ?? (fetched && fetched.url === fetchUrl ? fetched.data : null) ?? (mock && building ? mockCostarRecord(building) : null);

  const leaf = selection.path.split(".").pop() ?? "";
  const aliases: Record<string, string> = { sq_ft: "rba_sqft", building_class: "building_class" };
  const head = selection.value.split(/[.,:]/)[0]?.trim() ?? "";
  const terms = [leaf, aliases[leaf], typeof cite.raw.field === "string" ? cite.raw.field.split(/[.|[]/)[0] : null, ...(head.length > 3 ? [head] : [])].filter(
    (x): x is string => !!x && !/^\d+$/.test(x),
  );
  const text = record ? JSON.stringify(record, null, 2) : JSON.stringify(cite.raw, null, 2);
  const lines = text.split("\n");
  const isHit = (l: string) => terms.some((t) => l.includes(`"${t}"`) || (t.length > 3 && l.includes(t)));
  const firstHit = lines.findIndex(isHit);

  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => {
    const el = ref.current?.querySelector<HTMLElement>("[data-hit='1']");
    const box = ref.current;
    if (el && box) box.scrollTop = el.offsetTop - box.clientHeight / 2;
  }, [firstHit]);

  return (
    <figure className="overflow-hidden rounded border border-line">
      <div className="flex items-center justify-between border-b border-line bg-subtle px-3 py-1.5 text-xs">
        <span className="font-medium text-fg-2">Property record</span>
        <Mono>{cite.id}</Mono>
      </div>
      <pre ref={ref} className="relative max-h-[420px] overflow-auto bg-surface py-2 font-mono text-2xs leading-[18px]">
        {lines.map((l, i) => {
          const hit = isHit(l);
          return (
            <div key={i} data-hit={i === firstHit ? "1" : "0"} className={`flex px-3 ${hit ? "bg-accent-subtle" : ""}`}>
              <span className="mr-3 w-6 shrink-0 select-none text-right text-fg-4">{i + 1}</span>
              <JsonLine line={l} />
            </div>
          );
        })}
      </pre>
    </figure>
  );
}

function JsonLine({ line }: { line: string }) {
  const m = line.match(/^(\s*)("[^"]+")(\s*:\s*)?(.*)$/);
  if (!m) return <span className="whitespace-pre text-fg-3">{line}</span>;
  const [, ws, key, colon, rest] = m;
  if (!colon) return <span className="whitespace-pre text-fg">{line}</span>;
  return (
    <span className="whitespace-pre">
      {ws}
      <span className="text-fg-3">{key}</span>
      <span className="text-fg-4">{colon}</span>
      <span className="text-fg">{rest}</span>
    </span>
  );
}

/* ---------------- Inference ---------------- */

interface ChainItem {
  key: string;
  ref: string; // e.g. "vexcel.roof_type"
  src: string;
  cite: NormCite;
  thumb: string | null;
  path: string;
}

/** Resolve every link of an inference chain to a concrete cite and, where possible, an image. */
function resolveChain(cite: NormCite, plan: Plan | null, building: Building | null, evidence: Record<string, Record<string, unknown>>): ChainItem[] {
  const all = collectCites(plan);
  const media = (plan?.media as Record<string, unknown> | undefined) ?? {};
  const panos = (media.pano_urls as string[] | undefined) ?? [];
  const aerial = assetUrl(media.aerial_url) ?? assetUrl(media.aerial_raw_url) ?? assetUrl(evidence.vexcel?.image_url) ?? (building ? mockAerialUrl(building) : null);
  const out: ChainItem[] = [];
  const seen = new Set<string>();
  const push = (it: ChainItem) => {
    const k = `${it.src}:${it.cite.id ?? ""}:${it.thumb ?? ""}`;
    if (seen.has(k)) return;
    seen.add(k);
    out.push(it);
  };
  // the inference cite may itself point at an image (e.g. the panorama it read)
  if (isImageUrl(cite.url)) {
    const src = /matterport/.test(cite.url) ? "matterport" : "vexcel";
    push({ key: "self", ref: src === "matterport" ? "Scan panorama" : "Aerial tile", src, cite: { ...cite, src }, thumb: assetUrl(cite.url), path: "self" });
  }
  for (const ref of cite.from ?? []) {
    const [src0, field = ""] = ref.split(/[.:]/);
    const src = src0.toLowerCase();
    const sweep = ref.includes(":") ? field : null;
    const match =
      (sweep ? all.find((c) => c.cite.src === src && c.cite.id === sweep) : null) ??
      all.find((c) => c.cite.src === src && field && (c.path.endsWith(field) || (c.cite.from ?? []).includes(ref))) ??
      all.find((c) => c.cite.src === src && field && c.path.includes(field.split("_")[0])) ??
      all.find((c) => c.cite.src === src);
    let c: NormCite = match?.cite ?? { src, id: sweep, conf: null, bbox: null, url: null, from: null, model: null, raw: { src } };
    let thumb: string | null = null;
    if (src === "vexcel") thumb = (isImageUrl(c.url) ? assetUrl(c.url) : null) ?? aerial;
    if (src === "matterport") {
      const pano = (isImageUrl(c.url) ? c.url : null) ?? (sweep ? panos.find((u) => u.includes(sweep)) : null) ?? null;
      if (pano) c = { ...c, url: pano };
      thumb = pano ? assetUrl(pano) : null;
    }
    push({ key: ref, ref, src, cite: c, thumb, path: match?.path ?? ref });
  }
  return out;
}

function InferenceView({
  cite,
  selection,
  plan,
  building,
  evidence,
  mock,
  onNavigate,
}: {
  cite: NormCite;
  selection: Selection;
  plan: Plan | null;
  building: Building | null;
  evidence: Record<string, Record<string, unknown>>;
  mock: boolean;
  onNavigate: (s: Selection) => void;
}) {
  const chain = useMemo(() => resolveChain(cite, plan, building, evidence), [cite, plan, building, evidence]);
  const primaryIdx = Math.max(0, chain.findIndex((c) => c.thumb));
  const [active, setActive] = useState<number | null>(null);
  const idx = active ?? primaryIdx;
  const cur = chain[idx];
  const roofish = /roof|solar|pv|skylight|ponding|parapet/i.test(`${selection.label} ${selection.value} ${(cite.from ?? []).join(" ")}`);

  return (
    <div>
      <p className="text-xs text-fg-3">Inferred by the agent from the evidence below. Not directly observed.</p>
      {selection.reason && <p className="mt-1 text-sm text-fg">{clean(selection.reason)}</p>}

      {cur && (
        <div className="mt-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-xs text-fg-2">
            <SourceGlyph src={cur.src} />
            <span className="font-medium">{sourceMeta(cur.src).label}</span>
            <Mono className="truncate text-fg-3">{cur.ref}</Mono>
          </div>
          {cur.src === "vexcel" ? (
            <VexcelView cite={cur.cite} plan={plan} building={building} mock={mock} evidence={evidence} selectedPath={cur.path} annotated={roofish} />
          ) : cur.src === "matterport" && isImageUrl(cur.cite.url) ? (
            <div className="overflow-hidden rounded border border-line">
              <PanoViewer key={cur.cite.url} url={assetUrl(cur.cite.url)!} bbox={cur.cite.bbox} label={selection.label} />
            </div>
          ) : cur.src === "matterport" ? (
            <MatterportView key={cur.key} cite={cur.cite} building={building} evidence={evidence} label={selection.label} value={selection.value} plan={plan} />
          ) : cur.src === "costar" ? (
            <CostarView cite={cur.cite} building={building} evidence={evidence} mock={mock} selection={{ ...selection, path: cur.ref.replace(/^costar\./, "building."), value: cur.ref.split(".").pop() ?? "" }} />
          ) : null}
        </div>
      )}

      {chain.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-1 text-xs font-medium text-fg-2">Evidence chain</h3>
          <ul className="border-t border-line">
            {chain.map((c, i) => (
              <li key={c.key}>
                <button
                  onClick={() => setActive(i)}
                  className={`relative flex w-full items-center gap-3 border-b border-line py-1.5 pl-2 pr-1 text-left ${i === idx ? "bg-accent-subtle" : "hover:bg-subtle"}`}
                >
                  {i === idx && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" />}
                  <span className="flex h-10 w-16 shrink-0 items-center justify-center overflow-hidden rounded-sm border border-line bg-muted">
                    {c.thumb ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={c.thumb} alt="" className="h-full w-full object-cover" loading="lazy" />
                    ) : (
                      <span className="text-2xs text-fg-3">Record</span>
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5 text-sm text-fg">
                      <SourceGlyph src={c.src} />
                      {sourceMeta(c.src).label}
                    </span>
                    <Mono className="block truncate text-fg-3">{c.ref}</Mono>
                  </span>
                  {c.path !== c.ref && c.path !== "self" && (
                    <span
                      role="link"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation();
                        onNavigate({ path: c.path, label: c.ref, value: c.ref.split(/[.:]/).pop()?.replace(/_/g, " ") ?? c.ref, cite: c.cite });
                      }}
                      className="shrink-0 px-1 text-2xs text-fg-3 hover:text-accent"
                      title="Open this fact in the plan"
                    >
                      Go to fact
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
