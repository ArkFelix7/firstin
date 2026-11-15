"use client";

import { Check, ChevronRight, Layers, MonitorSmartphone, Search, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Brand, ModeBadge } from "@/components/Brand";
import { BuildingMap, type Basemap } from "@/components/map/BuildingMap";
import { Button, KV, Mono, SourceGlyph, StatusBadge, planStatusTone } from "@/components/ui";
import { getBuildings, startPreplan, type Mode } from "@/lib/api";
import { fmtDate, fmtTime, getBuildingFacts, getRuns, searchBuildings, type BuildingFacts, type RunSummary } from "@/lib/buildingFacts";
import { clean } from "@/lib/text";
import type { Building } from "@/lib/types";

const LAYERS = [
  { key: "costar", label: "CoStar", provides: "Tenants, occupancy, construction era" },
  { key: "vexcel", label: "Vexcel", provides: "Roof, access, exposures" },
  { key: "matterport", label: "Matterport", provides: "Stairs, utilities, fire protection" },
] as const;

const HERO = "la-002";
const PAGE = 50;
const DETAIL_W = 380;
const n = (x: number) => x.toLocaleString("en-US");

export default function Home() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode | null>(null);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [q, setQ] = useState("");
  const [city, setCity] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [flyKey, setFlyKey] = useState(0);
  const [basemap, setBasemap] = useState<Basemap>("light");
  const [showMarkers, setShowMarkers] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [focus, setFocus] = useState<{ city: string; nonce: number } | null>(null);
  const [launching, setLaunching] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [facts, setFacts] = useState<Record<string, BuildingFacts | null>>({});
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [limit, setLimit] = useState(PAGE);
  const [results, setResults] = useState<{ q: string; total: number; items: Building[] } | null>(null);

  useEffect(() => {
    getBuildings().then(({ mode, buildings }) => {
      setMode(mode);
      setBuildings(buildings);
      const first = buildings.find((b) => b.building_id === HERO) ?? buildings.find((b) => b.featured) ?? buildings[0] ?? null;
      setCity(first?.city ?? null);
      setSelected(first?.building_id ?? null); // never open on an empty page
      if (first) setFocus({ city: first.city, nonce: 1 });
    });
    let alive = true;
    const poll = () => getRuns().then((r) => alive && setRuns(r));
    poll();
    const id = setInterval(poll, 10000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // search (debounced; server endpoint when available)
  useEffect(() => {
    const s = q.trim();
    if (!s) return;
    let alive = true;
    const t = setTimeout(() => {
      searchBuildings(buildings, s, null, limit).then((r) => alive && setResults({ q: s, ...r }));
    }, 120);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q, limit, buildings]);

  const byId = useMemo(() => new Map(buildings.map((b) => [b.building_id, b])), [buildings]);
  const sel = selected ? (byId.get(selected) ?? results?.items.find((b) => b.building_id === selected) ?? null) : null;
  const selFacts = sel ? facts[sel.building_id] : undefined;

  useEffect(() => {
    if (!sel || sel.building_id in facts) return;
    let alive = true;
    // only prepared buildings have agent cache files; the rest use registry fields
    const p = sel.featured || sel.cached ? getBuildingFacts(sel) : Promise.resolve(null);
    p.then((f) => alive && setFacts((m) => ({ ...m, [sel.building_id]: f })));
    return () => {
      alive = false;
    };
  }, [sel, facts]);

  const cities = useMemo(() => Array.from(new Set(buildings.map((b) => b.city))), [buildings]);
  const inCity = useMemo(() => buildings.filter((b) => !city || b.city === city), [buildings, city]);
  const featured = useMemo(() => inCity.filter((b) => b.featured).sort((a, z) => Number(z.building_id === HERO) - Number(a.building_id === HERO)), [inCity]);
  const rest = useMemo(() => inCity.filter((b) => !b.featured), [inCity]);
  const preparedTotal = buildings.filter((b) => b.featured || b.cached).length;
  const searching = q.trim().length > 0;

  const select = (id: string) => {
    setSelected(id);
    setFlyKey((k) => k + 1);
    setBasemap("satellite"); // inspect the roof on imagery
  };

  const pickCity = (c: string) => {
    setBasemap("light");
    setCity(c);
    setQ("");
    setLimit(PAGE);
    const first = buildings.find((b) => b.city === c && b.featured) ?? buildings.find((b) => b.city === c);
    setSelected(first?.building_id ?? null);
    setFocus((f) => ({ city: c, nonce: (f?.nonce ?? 0) + 1 }));
  };

  const generate = async () => {
    if (!sel || launching) return;
    setLaunching(true);
    setErr(null);
    try {
      const runId = await startPreplan(sel.building_id);
      router.push(`/plan/${encodeURIComponent(runId)}?b=${encodeURIComponent(sel.building_id)}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not start the run.");
      setLaunching(false);
    }
  };

  const shownRest = rest.slice(0, limit);

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden bg-canvas">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line-strong bg-surface px-4">
        <div className="flex items-center gap-3">
          <Brand />
          <span className="h-5 w-px bg-line-strong" />
          <span className="text-sm text-fg-2">Pre-incident plans</span>
        </div>
        <div className="flex items-center gap-4">
          <ModeBadge mode={mode} />
          <Link href="/incab" className="inline-flex h-8 items-center gap-1.5 rounded border border-line-strong bg-surface px-3 text-sm font-medium text-fg hover:bg-subtle">
            <MonitorSmartphone size={14} /> In-cab display
          </Link>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[clamp(400px,26vw,500px)] shrink-0 flex-col border-r border-line-strong bg-surface">
          <div className="space-y-3 border-b border-line px-4 pb-3 pt-4">
            <div className="flex items-baseline justify-between gap-3">
              <h1 className="text-lg font-semibold text-fg">Buildings</h1>
              <span className="truncate text-xs tabular-nums text-fg-3">
                {buildings.length ? `${n(buildings.length)} buildings, ${n(preparedTotal)} prepared` : "Loading"}
              </span>
            </div>
            <div className="flex gap-2">
              <label className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded border border-line-strong bg-surface px-2.5 focus-within:border-accent">
                <Search size={14} className="shrink-0 text-fg-3" />
                <input
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    setLimit(PAGE);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && results?.items[0]) select(results.items[0].building_id);
                    if (e.key === "Escape") setQ("");
                  }}
                  placeholder={`Search ${buildings.length ? n(buildings.length) : ""} buildings`}
                  className="w-full bg-transparent text-sm text-fg placeholder:text-fg-4 focus:outline-none"
                />
                {q && (
                  <button onClick={() => setQ("")} aria-label="Clear search" className="text-fg-3 hover:text-fg">
                    <X size={14} />
                  </button>
                )}
              </label>
              <div className="inline-flex h-8 shrink-0 rounded bg-muted p-0.5" role="tablist" aria-label="City">
                {cities.map((c) => {
                  const on = city === c && !searching;
                  return (
                    <button
                      key={c}
                      role="tab"
                      aria-selected={on}
                      onClick={() => pickCity(c)}
                      className={`rounded-sm px-3 text-xs font-medium ${on ? "bg-surface text-fg shadow-elev-1" : "text-fg-2 hover:text-fg"}`}
                    >
                      {c}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {searching ? (
              <>
                <ListHeader title="Results" meta={results && results.q === q.trim() ? `${n(results.total)} matches` : "Searching"} />
                {results?.items.map((it) => {
                  const b = { ...it, ...(byId.get(it.building_id) ?? {}) };
                  return <Row key={b.building_id} b={b} active={b.building_id === selected} onClick={() => select(b.building_id)} showCity />;
                })}
                {results && results.total === 0 && <p className="px-4 py-6 text-center text-sm text-fg-3">No building matches “{q}”.</p>}
                {results && results.items.length < results.total && <LoadMore onClick={() => setLimit((l) => l + PAGE)} left={results.total - results.items.length} />}
              </>
            ) : (
              <>
                <ListHeader title="Featured" meta={`${featured.length} prepared, about 30 s`} />
                {featured.map((b) => (
                  <Row key={b.building_id} b={b} active={b.building_id === selected} onClick={() => select(b.building_id)} />
                ))}

                {runs.length > 0 && (
                  <>
                    <ListHeader title="Recent runs" meta={`${runs.length}`} />
                    {runs.slice(0, 4).map((r) => {
                      const st = planStatusTone(String(r.status).toUpperCase());
                      const b = byId.get(r.building_id);
                      return (
                        <Link
                          key={r.run_id}
                          href={`/plan/${encodeURIComponent(r.run_id)}?b=${encodeURIComponent(r.building_id)}`}
                          className="grid grid-cols-[minmax(0,1fr)_auto_14px] items-center gap-3 border-b border-line px-4 py-2 hover:bg-subtle"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-sm text-fg">{b ? b.address.split(",")[0] : r.building_id}</span>
                            <span className="block truncate text-2xs text-fg-3">
                              <Mono className="text-fg-3">{r.run_id}</Mono>
                              {r.created_at ? `, ${fmtTime(r.created_at)}` : ""}
                            </span>
                          </span>
                          <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
                          <ChevronRight size={14} className="text-fg-4" />
                        </Link>
                      );
                    })}
                  </>
                )}

                <ListHeader title={`All buildings${city ? ` in ${city}` : ""}`} meta={`${n(rest.length)}`} />
                {shownRest.map((b) => (
                  <Row key={b.building_id} b={b} active={b.building_id === selected} onClick={() => select(b.building_id)} />
                ))}
                {shownRest.length < rest.length && <LoadMore onClick={() => setLimit((l) => l + PAGE)} left={rest.length - shownRest.length} />}
              </>
            )}
          </div>
        </aside>

        <main className="relative min-w-0 flex-1">
          <BuildingMap
            buildings={buildings}
            selectedId={selected}
            onSelect={select}
            basemap={basemap}
            focus={focus}
            showMarkers={showMarkers}
            showLabels={showLabels}
            flyKey={flyKey}
            padRight={sel ? DETAIL_W + 24 : 0}
          />
          <LayerPanel
            basemap={basemap}
            setBasemap={setBasemap}
            showMarkers={showMarkers}
            setShowMarkers={setShowMarkers}
            showLabels={showLabels}
            setShowLabels={setShowLabels}
          />
          {sel && (
            <DetailPanel b={sel} facts={selFacts} onClose={() => setSelected(null)} onGenerate={generate} launching={launching} err={err} />
          )}
        </main>
      </div>
    </div>
  );
}

function ListHeader({ title, meta }: { title: string; meta?: string }) {
  return (
    <div className="sticky top-0 z-10 flex h-8 items-center justify-between border-b border-line bg-subtle px-4 text-xs">
      <span className="font-medium text-fg-2">{title}</span>
      {meta && <span className="tabular-nums text-fg-3">{meta}</span>}
    </div>
  );
}

function LoadMore({ onClick, left }: { onClick: () => void; left: number }) {
  return (
    <button onClick={onClick} className="w-full border-b border-line px-4 py-2 text-left text-xs font-medium text-accent hover:bg-subtle">
      Load {Math.min(left, PAGE)} more <span className="font-normal text-fg-3">({n(left)} remaining)</span>
    </button>
  );
}

function Row({ b, active, onClick, showCity }: { b: Building; active: boolean; onClick: () => void; showCity?: boolean }) {
  const prepared = !!(b.featured || b.cached);
  const meta = [b.property_type, b.stories ? `${b.stories} ${b.stories === 1 ? "story" : "stories"}` : null, b.year_built ? `built ${b.year_built}` : null].filter(Boolean).join(", ");
  const street = b.address.split(",")[0];
  const secondary = meta || (b.name && clean(b.name) !== street ? clean(b.name) : "") || b.city;
  return (
    <button
      onClick={onClick}
      className={`relative grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-line px-4 py-2 text-left ${active ? "bg-accent-subtle" : "hover:bg-subtle"}`}
    >
      {active && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" />}
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-fg">{street}</span>
        <span className="block truncate text-xs text-fg-3">
          {showCity ? `${b.city}, ` : ""}
          {secondary}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-3">
        <span className="flex items-center gap-1" title={LAYERS.map((l) => `${l.label}: ${b.has?.[l.key] ? "available" : "missing"}`).join("\n")}>
          {LAYERS.map((l) => (
            <span key={l.key} className={b.has?.[l.key] ? "" : "opacity-25 grayscale"}>
              <SourceGlyph src={l.key} size={7} />
            </span>
          ))}
        </span>
        {prepared ? <StatusBadge>Prepared</StatusBadge> : <span className="w-[72px] text-right text-2xs text-fg-3">Live, ~50 s</span>}
      </span>
    </button>
  );
}

function DetailPanel({
  b,
  facts,
  onClose,
  onGenerate,
  launching,
  err,
}: {
  b: Building;
  facts: BuildingFacts | null | undefined;
  onClose: () => void;
  onGenerate: () => void;
  launching: boolean;
  err: string | null;
}) {
  const loading = facts === undefined;
  const f = facts ?? null;
  const prepared = !!(b.featured || b.cached);
  const none = <span className="text-fg-4">{loading ? "Loading" : "Not in record"}</span>;
  const year = f?.yearBuilt ?? b.year_built ?? null;
  const stories = f?.stories ?? b.stories ?? null;
  const area = f?.areaSf ?? b.rba_sqft ?? null;
  const captured: Record<string, string> = {
    costar: b.costar_id ? `Record ${b.costar_id}` : "",
    vexcel: f?.vexcelCaptured ? `Captured ${fmtDate(f.vexcelCaptured)}` : "",
    matterport: f?.matterportCreated ? `Scanned ${fmtDate(f.matterportCreated)}` : "",
  };
  return (
    <section className="absolute bottom-3 right-3 top-3 z-10 flex flex-col overflow-hidden rounded border border-line-strong bg-surface shadow-elev-2" style={{ width: DETAIL_W }} aria-label="Selected building">
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-line pl-4 pr-1.5">
        <span className="flex items-center gap-2 text-sm font-medium text-fg">
          Building details {prepared ? <StatusBadge>Prepared</StatusBadge> : <span className="text-2xs font-normal text-fg-3">Live data</span>}
        </span>
        <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded text-fg-3 hover:bg-muted hover:text-fg" aria-label="Close details">
          <X size={14} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <h2 className="text-lg font-semibold text-fg">{b.address.split(",")[0]}</h2>
        <p className="text-sm text-fg-2">{b.address.split(",").slice(1).join(",").trim()}</p>
        {b.name && clean(b.name) !== b.address.split(",")[0] && <p className="mt-0.5 text-xs text-fg-3">{clean(b.name)}</p>}

        {f?.aerialUrl && (
          <figure className="mt-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={f.aerialUrl} alt={`Aerial view of ${b.address}`} className="aspect-[16/9] w-full rounded border border-line object-cover" />
            <figcaption className="mt-1 text-2xs text-fg-3">
              Vexcel orthomosaic{f.vexcelCaptured ? `, ${fmtDate(f.vexcelCaptured)}` : ""}
              {f.vexcelGsd ? `, ${Math.round(f.vexcelGsd * 100)} cm resolution` : ""}
            </figcaption>
          </figure>
        )}

        {f?.accessUrl && (
          <figure className="mt-3">
            <div className="mb-1 text-xs font-medium text-fg-2">Access plan</div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={f.accessUrl} alt={`Access plan for ${b.address}`} className="aspect-[16/10] w-full rounded border border-line object-cover" />
            <figcaption className="mt-1 text-2xs text-fg-3">Ladder access walls, staging and entries from the last analysis</figcaption>
          </figure>
        )}

        <div className="mt-3 border-t border-line">
          <KV
            labelWidth={116}
            rows={[
              ...(b.property_type ? ([["Property type", b.property_type]] as Array<[string, React.ReactNode]>) : []),
              [
                "Year built",
                year ? (
                  <span className="tabular-nums">
                    {year}
                    {f?.yearRenovated ? <span className="text-fg-3">, renovated {f.yearRenovated}</span> : null}
                  </span>
                ) : (
                  none
                ),
              ],
              ["Stories", stories ? <span className="tabular-nums">{stories}</span> : none],
              ["Rentable area", area ? <span className="tabular-nums">{n(Math.round(area))} SF</span> : none],
              ["CoStar property", b.costar_id ? <Mono>{b.costar_id}</Mono> : <span className="text-fg-4">Not linked</span>],
              [
                "3D scans",
                b.matterport_model_ids?.length ? (
                  <span className="tabular-nums">
                    {b.matterport_model_ids.length} model{b.matterport_model_ids.length === 1 ? "" : "s"}
                    {f?.matterportSweeps ? <span className="text-fg-3">, {f.matterportSweeps} scan points</span> : null}
                  </span>
                ) : (
                  <span className="text-fg-4">None</span>
                ),
              ],
              [
                "Coordinates",
                <Mono key="ll" className="tabular-nums">
                  {b.lat.toFixed(5)}, {b.lng.toFixed(5)}
                </Mono>,
              ],
            ]}
          />
        </div>

        <h3 className="mb-1 mt-4 text-xs font-medium text-fg-2">Data layers</h3>
        <table className="w-full border-collapse border-t border-line">
          <tbody>
            {LAYERS.map((l) => {
              const on = !!b.has?.[l.key];
              return (
                <tr key={l.key}>
                  <td className="w-[108px] border-b border-line py-1.5 align-top">
                    <span className="inline-flex items-center gap-1.5 text-sm text-fg">
                      <SourceGlyph src={l.key} />
                      {l.label}
                    </span>
                  </td>
                  <td className="border-b border-line py-1.5 text-xs">
                    <div className="text-fg-2">{l.provides}</div>
                    {on && captured[l.key] && <div className="text-fg-3">{captured[l.key]}</div>}
                  </td>
                  <td className="w-[84px] border-b border-line py-1.5 text-right align-top">{on ? <StatusBadge tone="ok">Available</StatusBadge> : <StatusBadge>Missing</StatusBadge>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="shrink-0 border-t border-line px-4 py-3">
        <Button variant="primary" size="lg" className="w-full" onClick={onGenerate} loading={launching} disabled={launching}>
          {launching ? "Starting run" : "Generate pre-plan"}
        </Button>
        <p className="mt-1.5 text-xs text-fg-3">
          {prepared ? "Prepared building, about 30 seconds." : "Fetches live data, about 50 seconds."} Nothing is published until an officer approves it.
        </p>
        {err && <p className="mt-1 text-xs text-danger">{err}</p>}
      </div>
    </section>
  );
}

function LayerPanel(p: {
  basemap: Basemap;
  setBasemap: (b: Basemap) => void;
  showMarkers: boolean;
  setShowMarkers: (v: boolean) => void;
  showLabels: boolean;
  setShowLabels: (v: boolean) => void;
}) {
  return (
    <div className="absolute left-3 top-3 z-10 w-[220px] rounded border border-line-strong bg-surface text-fg shadow-elev-2">
      <div className="flex h-9 items-center gap-2 border-b border-line px-3 text-sm font-medium">
        <Layers size={14} className="text-fg-2" /> Layers
      </div>
      <div className="space-y-3 px-3 py-2.5">
        <fieldset>
          <legend className="mb-1 text-xs text-fg-3">Basemap</legend>
          <div className="grid grid-cols-2 rounded bg-muted p-0.5">
            {(
              [
                ["light", "Streets"],
                ["satellite", "Imagery"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                onClick={() => p.setBasemap(k)}
                aria-pressed={p.basemap === k}
                className={`h-6 rounded-sm text-xs font-medium ${p.basemap === k ? "bg-surface text-fg shadow-elev-1" : "text-fg-2 hover:text-fg"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>
        <fieldset className="space-y-0.5">
          <legend className="mb-1 text-xs text-fg-3">Operational layers</legend>
          <Toggle checked={p.showMarkers} onChange={p.setShowMarkers}>
            Indexed buildings
          </Toggle>
          <Toggle checked={p.showLabels} onChange={p.setShowLabels}>
            Featured labels
          </Toggle>
        </fieldset>
        <div>
          <div className="mb-1 text-xs text-fg-3">Legend</div>
          <ul className="space-y-1 text-xs text-fg-2">
            <li className="flex items-center gap-2">
              <span className="h-3.5 w-3.5 rounded-full border-2 border-white bg-accent ring-1 ring-line-strong" /> Featured, prepared
            </li>
            <li className="flex items-center gap-2">
              <span className="ml-0.5 h-2.5 w-2.5 rounded-full border border-white bg-[#5a6b8c] ring-1 ring-line-strong" /> Indexed building
            </li>
            <li className="flex items-center gap-2">
              <span className="flex h-4 w-4 items-center justify-center rounded-full border border-accent bg-accent-subtle text-[9px] font-semibold text-accent">12</span> Cluster, click to zoom
            </li>
            <li className="flex items-center gap-2">
              <span className="h-3.5 w-3.5 rounded-full border-2 border-white bg-fg ring-2 ring-accent" /> Selected
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}

function Toggle({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="flex h-6 cursor-pointer items-center gap-2 text-sm text-fg">
      <span className={`flex h-4 w-4 items-center justify-center rounded-sm border ${checked ? "border-accent bg-accent text-white" : "border-line-strong bg-surface"}`}>
        {checked && <Check size={11} strokeWidth={3} />}
      </span>
      <input type="checkbox" className="sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}
