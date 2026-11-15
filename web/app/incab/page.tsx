"use client";

import { AlertTriangle, Loader2, Mic, Radio, Volume2, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { LogoMark } from "@/components/Brand";
import { ask, assetUrl, getIncab, type Mode } from "@/lib/api";
import type { IncabSummary } from "@/lib/types";
import { clean, sentence, splitHazard } from "@/lib/text";

/* Minimal Web Speech API typings */
interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}
type SRCtor = new () => SpeechRecognitionLike;

const UNIT = process.env.NEXT_PUBLIC_UNIT_NAME ?? "Engine 12";

function hazardText(h: NonNullable<IncabSummary["top_hazards"]>[number]): { type: string; loc?: string } {
  if (typeof h === "string") {
    const x = splitHazard(h);
    return { type: x.type, loc: x.loc ?? undefined };
  }
  return { type: clean(String(h.type ?? h.name ?? "Hazard")), loc: h.location ? clean(String(h.location)) : undefined };
}

function stairsList(s: IncabSummary["stairs"]): string[] {
  if (!s) return [];
  if (Array.isArray(s)) return s.map((x) => clean(String(x)));
  return clean(String(s))
    .split(/;|\n|(?<=\)),\s+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

function fmtTime(v: IncabSummary["approved_at"]) {
  if (!v) return "";
  const d = typeof v === "number" ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
  return isNaN(d.getTime()) ? String(v) : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function Clock() {
  const [t, setT] = useState<string>("");
  useEffect(() => {
    const tick = () => setT(new Date().toLocaleTimeString([], { hour12: false }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="tabular">{t}</span>;
}

export default function InCab() {
  const [summary, setSummary] = useState<IncabSummary | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [mode, setMode] = useState<Mode | null>(null);
  const [linkOk, setLinkOk] = useState(true);
  const [flash, setFlash] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const [qa, setQa] = useState<{ q: string; a: string | null } | null>(null);
  const lastId = useRef<string | null | undefined>(undefined);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const summaryRef = useRef<IncabSummary | null>(null);

  const stopAll = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }, []);

  const say = useCallback(
    (text: string) => {
      const synth = window.speechSynthesis;
      if (!synth) return;
      synth.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.0;
      u.onend = () => setSpeaking(false);
      u.onerror = () => setSpeaking(false);
      setSpeaking(true);
      synth.speak(u);
    },
    [],
  );

  const briefMe = useCallback(() => {
    const s = summaryRef.current;
    if (!s) return;
    if (speaking) return stopAll();
    const url = assetUrl(s.audio_url);
    const fallback = () => s.voice_brief && say(s.voice_brief);
    if (url) {
      const a = new Audio(url);
      audioRef.current = a;
      a.onended = () => setSpeaking(false);
      a.onerror = () => {
        audioRef.current = null;
        fallback();
      };
      setSpeaking(true);
      a.play().catch(() => fallback());
    } else fallback();
  }, [say, speaking, stopAll]);

  const briefRef = useRef(briefMe);
  useEffect(() => {
    briefRef.current = briefMe;
  }, [briefMe]);

  // poll
  useEffect(() => {
    let alive = true;
    const autobrief = new URLSearchParams(window.location.search).get("autobrief") === "1";
    const poll = async () => {
      try {
        const r = await getIncab();
        if (!alive) return;
        setMode(r.mode);
        setLinkOk(true);
        const id = r.summary?.plan_id ?? null;
        if (lastId.current !== undefined && id && id !== lastId.current) {
          setFlash(Date.now());
          setTimeout(() => setFlash(0), 6000);
          if (autobrief) setTimeout(() => briefRef.current(), 1800);
        }
        lastId.current = id;
        summaryRef.current = r.summary;
        setSummary(r.summary);
      } catch {
        if (alive) setLinkOk(false);
      } finally {
        if (alive) setLoaded(true);
      }
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const askVoice = useCallback(() => {
    const s = summaryRef.current;
    if (!s) return;
    const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    const submit = async (q: string) => {
      setQa({ q, a: null });
      try {
        const a = await ask(s.plan_id, q, s);
        setQa({ q, a });
        say(a);
      } catch {
        setQa({ q, a: "Agent unreachable." });
      }
    };
    if (!Ctor) {
      const q = window.prompt("Ask about this building:");
      if (q) submit(q);
      return;
    }
    stopAll();
    const rec = new Ctor();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e) => {
      const q = e.results[0]?.[0]?.transcript;
      if (q) submit(q);
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    setListening(true);
    setQa(null);
    rec.start();
  }, [say, stopAll]);

  // hardware button / keyboard: Space or Enter = BRIEF ME, "a" = ask
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.code === "Space" || e.key === "Enter") {
        e.preventDefault();
        briefRef.current();
      } else if (e.key.toLowerCase() === "a") askVoice();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [askVoice]);

  const s = summary;
  const stairs = stairsList(s?.stairs);
  const rawHazards = Array.isArray(s?.top_hazards_detail) && s.top_hazards_detail.length ? s.top_hazards_detail : Array.isArray(s?.top_hazards) ? s.top_hazards : [];
  // de-duplicate by hazard type (several tenants can trigger the same rule), merging locations
  const hazards = rawHazards
    .map((h) => hazardText(h as NonNullable<IncabSummary["top_hazards"]>[number]))
    .reduce<Array<{ type: string; loc?: string }>>((acc, h) => {
      const hit = acc.find((x) => x.type.toLowerCase() === h.type.toLowerCase());
      if (!hit) acc.push({ ...h });
      else if (h.loc && !hit.loc?.includes(h.loc)) hit.loc = hit.loc ? `${hit.loc}; ${h.loc}` : h.loc;
      return acc;
    }, [])
    .slice(0, 3);
  const isVerify = (v: unknown) => /verify\s+on\s+site/i.test(String(v ?? ""));
  const roof = s?.roof_access_short && !isVerify(s.roof_access_short) ? s.roof_access_short : s?.roof_access;

  return (
    <div data-theme="dark" className="relative flex h-dvh select-none flex-col overflow-hidden bg-canvas text-fg">
      {/* Status bar */}
      <div className="flex h-[8vh] min-h-12 shrink-0 items-center justify-between border-b border-line bg-surface px-[2.4vw]">
        <div className="flex items-center gap-[1.2vw]">
          <LogoMark size={28} inverted />
          <span className="text-[clamp(18px,2.2vw,32px)] font-semibold">{UNIT}</span>
          <span className="text-[clamp(12px,1.3vw,18px)] text-fg-3">In-cab display</span>
        </div>
        <div className="flex items-center gap-[2.4vw] text-[clamp(13px,1.5vw,22px)]">
          <span className={`flex items-center gap-2 ${linkOk ? "text-fg-2" : "text-danger"}`}>
            <span className={`h-2.5 w-2.5 rounded-full ${linkOk ? (mode === "mock" ? "bg-warn" : "bg-ok") : "bg-danger"}`} />
            {linkOk ? (mode === "mock" ? "Replay" : "Connected") : "No connection"}
          </span>
          <span className="font-medium tabular-nums text-fg">
            <Clock />
          </span>
        </div>
      </div>

      {flash > 0 && s && (
        <div className="flex shrink-0 items-center gap-3 border-b border-accent-line bg-accent-subtle px-[2.4vw] py-[1vh] text-[clamp(14px,1.6vw,24px)] text-fg">
          <span className="h-2.5 w-2.5 rounded-full bg-accent" />
          New pre-plan received
        </div>
      )}

      {!s ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-[2vh] text-center">
          {loaded ? <Radio className="text-fg-3" size={56} strokeWidth={1.5} /> : <Loader2 className="animate-spin text-fg-3" size={48} />}
          <div className="text-[clamp(28px,4vw,60px)] font-semibold text-fg">Standing by</div>
          <div className="max-w-[60vw] text-[clamp(14px,1.6vw,24px)] text-fg-3">No approved pre-plan. Plans appear here as soon as an officer approves them.</div>
        </div>
      ) : (
        <div key={s.plan_id} className="flex min-h-0 flex-1 flex-col px-[2.4vw] pb-[2.4vh] pt-[2.4vh]">
          {/* Address */}
          <div className="shrink-0">
            <div className="flex items-center gap-3 text-[clamp(13px,1.5vw,22px)] text-fg-2">
              <span className="font-medium text-ok">Approved pre-plan</span>
              {s.approved_at ? <span className="text-fg-3">{fmtTime(s.approved_at)}</span> : null}
              {s.approved_by ? <span className="text-fg-3">by {s.approved_by}</span> : null}
            </div>
            <div className="mt-[0.6vh] line-clamp-2 text-[clamp(26px,min(4.2vw,7vh),68px)] font-semibold leading-[1.1]">{s.address}</div>
          </div>

          {/* Key figures */}
          <div className="mt-[2vh] grid shrink-0 grid-cols-[1fr_1fr_2.4fr] divide-x divide-line border-y border-line">
            <Stat label="Stories" value={s.stories ?? "Verify on site"} />
            <Stat label="Built" value={s.year_built ?? "Verify on site"} />
            <Stat label="Construction" value={s.construction ? clean(s.construction) : "Verify on site"} sub={s.construction_detail && s.construction_detail !== s.construction ? clean(s.construction_detail) : undefined} small />
          </div>

          {/* Hazards and egress */}
          <div className="mt-[2vh] grid min-h-0 flex-1 grid-cols-[1.3fr_1fr] gap-[2.4vw]">
            <section className="flex min-h-0 flex-col">
              <h2 className="flex items-center gap-2 text-[clamp(13px,1.5vw,22px)] font-medium text-fg-2">
                <AlertTriangle size={22} className="text-danger" /> Top hazards
              </h2>
              <ol className="mt-[1vh] min-h-0 flex-1 overflow-hidden border-t border-line">
                {hazards.length ? (
                  hazards.map((h, i) => (
                    <li key={i} className="grid grid-cols-[3.2vw_minmax(0,1fr)] items-baseline gap-x-[1vw] border-b border-l-4 border-b-line border-l-danger py-[1.2vh] pl-[1vw]">
                      <span className="text-[clamp(16px,min(2.2vw,3.4vh),34px)] font-semibold tabular-nums text-fg-3">{i + 1}</span>
                      <div className="min-w-0">
                        <div className="line-clamp-2 text-[clamp(18px,min(2.4vw,3.6vh),38px)] [@media(max-height:700px)]:line-clamp-1 font-semibold leading-tight">{h.type}</div>
                        {h.loc && <div className="mt-[0.3vh] truncate text-[clamp(14px,min(1.7vw,2.6vh),26px)] text-fg-2">{h.loc}</div>}
                      </div>
                    </li>
                  ))
                ) : (
                  <li className="py-[1.4vh] text-[clamp(16px,2vw,30px)] text-fg-3">None flagged</li>
                )}
              </ol>
            </section>
            <div className="flex min-h-0 flex-col gap-[2.4vh] overflow-hidden">
              <Block label="Stairs">
                {stairs.length && !stairs.every(isVerify) ? (
                  stairs.map((x, i) => (
                    <div key={i} className="leading-tight">
                      {x.split(/(standpipe)/i).map((part, j) =>
                        /standpipe/i.test(part) ? (
                          <span key={j} className="font-semibold text-fg underline decoration-danger decoration-2 underline-offset-4">
                            {part}
                          </span>
                        ) : (
                          <span key={j}>{part}</span>
                        ),
                      )}
                    </div>
                  ))
                ) : (
                  <VerifyText />
                )}
              </Block>
              <Block label="Roof access">
                {roof && !isVerify(roof) ? <span className={roof.length > 90 ? "line-clamp-4 text-[clamp(15px,1.7vw,26px)] font-normal" : ""}>{sentence(clean(roof))}</span> : <VerifyText />}
              </Block>
            </div>
          </div>

          {/* Controls */}
          <div className="mt-[2vh] grid h-[14vh] min-h-16 shrink-0 grid-cols-[1fr_15vh] gap-[1.2vw]">
            <button
              onClick={briefMe}
              className={`flex items-center justify-center gap-[1.4vw] rounded-md text-[clamp(28px,3.6vw,56px)] font-semibold ${
                speaking ? "border border-line-strong bg-muted text-fg" : "bg-accent text-on-accent hover:bg-accent-hover active:bg-accent-hover"
              }`}
            >
              {speaking ? <Square size={40} fill="currentColor" /> : <Volume2 size={44} />}
              {speaking ? "Stop" : "Brief me"}
            </button>
            <button
              onClick={askVoice}
              className={`flex flex-col items-center justify-center gap-1 rounded-md border ${listening ? "border-accent bg-accent-subtle text-fg" : "border-line-strong bg-surface text-fg hover:bg-subtle"}`}
              aria-label="Ask a question"
            >
              <Mic size={36} />
              <span className="text-[clamp(13px,1.4vw,20px)] font-medium">{listening ? "Listening" : "Ask"}</span>
            </button>
          </div>
        </div>
      )}

      {/* Voice Q&A */}
      {qa && (
        <div onClick={() => setQa(null)} className="absolute inset-x-[2.4vw] bottom-[20vh] z-30 rounded-md border border-line-strong bg-surface p-[1.6vw]">
          <div className="text-[clamp(13px,1.4vw,20px)] text-fg-3">Question: {qa.q}</div>
          <div className="mt-2 text-[clamp(22px,2.8vw,42px)] font-semibold leading-tight">{qa.a ? clean(qa.a) : <Loader2 className="inline animate-spin" size={32} />}</div>
        </div>
      )}
    </div>
  );
}

function VerifyText() {
  return (
    <span className="inline-flex items-center gap-2 text-warn">
      <AlertTriangle size={24} /> Verify on site
    </span>
  );
}

function Stat({ label, value, small, sub }: { label: string; value: string | number; small?: boolean; sub?: string }) {
  const text = String(value);
  const verify = /verify on site/i.test(text);
  const long = small || text.length > 7;
  return (
    <div className="min-w-0 overflow-hidden px-[1.4vw] py-[1.4vh] first:pl-0">
      <div className="text-[clamp(12px,1.3vw,20px)] text-fg-3">{label}</div>
      <div
        className={`mt-[0.4vh] line-clamp-2 font-semibold ${verify ? "text-warn" : ""} ${
          long ? "text-[clamp(16px,min(2.2vw,3.6vh),34px)] leading-tight" : "text-[clamp(30px,min(4.4vw,7vh),68px)] leading-none tabular-nums"
        }`}
      >
        {text}
      </div>
      {sub && <div className="mt-[0.4vh] truncate text-[clamp(12px,min(1.3vw,2vh),20px)] text-fg-3">{sub}</div>}
    </div>
  );
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="min-h-0 overflow-hidden">
      <h2 className="text-[clamp(13px,1.5vw,22px)] font-medium text-fg-2">{label}</h2>
      <div className="mt-[1vh] space-y-[0.8vh] border-t border-line pt-[1.2vh] text-[clamp(16px,min(2.2vw,3.4vh),34px)] font-medium leading-tight">{children}</div>
    </section>
  );
}
