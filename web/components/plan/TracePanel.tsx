"use client";

import { AlertCircle, Check, ChevronDown, ChevronRight, Circle, CircleCheck, CircleDashed, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { LANES, type Lane, type LogEntry, type RunState } from "@/lib/useRun";
import { clean } from "@/lib/text";

const LANE_NAME: Record<string, string> = {
  costar: "CoStar analyst",
  aerial: "Aerial analyst",
  interior: "Interior analyst",
  hazards: "Hazard reasoner",
  validator: "Validator",
};

const LANE_ROLE: Record<string, string> = {
  costar: "Tenants, era, size from CoStar",
  aerial: "Roof, access, exposures from Vexcel",
  interior: "Stairs, utilities, fire protection from Matterport",
  hazards: "Rules and model inference over the evidence",
  validator: "Cites every field or flags it",
};

const fmtClock = (ms: number) => {
  const s = Math.max(0, ms) / 1000;
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;
};
const fmtDur = (ms: number) => (ms < 60000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.floor(ms / 60000)} m ${Math.round((ms % 60000) / 1000)} s`);

/** Strip markdown and the reducer's leading glyphs from free text. */
const tidy = (s: string | undefined) =>
  clean(String(s ?? ""))
    .replace(/^[\s▶■⏸✓]+/u, "")
    .replace(/\*\*/g, "")
    .replace(/^[-*]\s+/, "")
    .replace(/\s+/g, " ")
    .trim();

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

export function TracePanel({ state }: { state: RunState }) {
  const done = state.todos.filter((t) => t.status === "completed").length;
  const now = useNow(!state.tEnd && !state.done);
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Steps */}
      <div className="border-b border-line px-4 pb-3 pt-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="font-medium text-fg-2">Steps</span>
          <span className="tabular-nums text-fg-3">
            {done} of {state.todos.length || "?"}
          </span>
        </div>
        {state.todos.length === 0 ? (
          <div className="flex items-center gap-2 py-1 text-sm text-fg-3">
            <Loader2 size={14} className="animate-spin" /> Planning
          </div>
        ) : (
          <ol className="space-y-0.5">
            {state.todos.map((t, i) => (
              <li key={t.content + i} className="flex items-start gap-2 text-sm">
                <span className="mt-[3px] flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                  {t.status === "completed" ? (
                    <CircleCheck size={14} className="text-ok" />
                  ) : t.status === "in_progress" ? (
                    <Loader2 size={14} className="animate-spin text-accent" />
                  ) : (
                    <Circle size={14} className="text-fg-4" />
                  )}
                </span>
                <span className={t.status === "pending" ? "text-fg-3" : t.status === "in_progress" ? "font-medium text-fg" : "text-fg-2"}>{tidy(t.content)}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {/* Subagents */}
      <div className="border-b border-line">
        <div className="flex items-center justify-between px-4 pb-1 pt-3 text-xs">
          <span className="font-medium text-fg-2">Subagents</span>
          <span className="text-fg-3">Run in parallel</span>
        </div>
        <ul>
          {LANES.map((l) => (
            <LaneRow key={l.key} lane={state.lanes[l.key]} now={now} />
          ))}
        </ul>
      </div>

      <LogStream log={state.log} />
    </div>
  );
}

function LaneRow({ lane, now }: { lane: Lane; now: number }) {
  const running = lane.status === "running";
  const ms = lane.startedAt ? (lane.endedAt ?? now) - lane.startedAt : null;
  const line = lane.status === "done" ? tidy(lane.summary || lane.last) || "Complete" : lane.status === "idle" ? LANE_ROLE[lane.key] : tidy(lane.last ?? lane.task) || LANE_ROLE[lane.key];
  return (
    <li className="grid grid-cols-[16px_minmax(0,1fr)_auto] items-start gap-x-2 px-4 py-1.5">
      <span className="mt-[3px] flex h-3.5 w-3.5 items-center justify-center">
        {lane.status === "done" ? (
          <CircleCheck size={14} className="text-ok" />
        ) : running ? (
          <Loader2 size={14} className="animate-spin text-accent" />
        ) : lane.status === "error" ? (
          <AlertCircle size={14} className="text-danger" />
        ) : (
          <CircleDashed size={14} className="text-fg-4" />
        )}
      </span>
      <div className="min-w-0">
        <div className={`text-sm ${lane.status === "idle" ? "text-fg-3" : "font-medium text-fg"}`}>{LANE_NAME[lane.key] ?? lane.label}</div>
        <div className="truncate text-xs text-fg-3" title={line}>
          {line}
        </div>
      </div>
      <div className="text-right text-xs tabular-nums">
        <div className={lane.status === "idle" ? "text-fg-4" : "text-fg-2"}>{ms !== null ? fmtDur(ms) : "Queued"}</div>
        {lane.calls > 0 && <div className="text-fg-3">{lane.calls} calls</div>}
      </div>
    </li>
  );
}

const KIND: Record<LogEntry["kind"], { label: string; cls: string }> = {
  call: { label: "call", cls: "text-fg-2" },
  result: { label: "result", cls: "text-fg-3" },
  log: { label: "info", cls: "text-fg-3" },
  warn: { label: "wait", cls: "text-warn" },
  error: { label: "error", cls: "text-danger" },
  evidence: { label: "write", cls: "text-fg-3" },
  system: { label: "agent", cls: "text-fg-2" },
  cross: { label: "check", cls: "text-ok" },
};

function LogStream({ log }: { log: LogEntry[] }) {
  const [open, setOpen] = useState(true);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log.length, open]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex items-center justify-between px-4 pb-1 pt-3 text-xs hover:text-fg">
        <span className="flex items-center gap-1 font-medium text-fg-2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Tool calls and events
        </span>
        <span className="tabular-nums text-fg-3">{log.length}</span>
      </button>
      {open && (
        <div ref={ref} className="min-h-0 flex-1 overflow-y-auto pb-3 font-mono text-2xs">
          {log.map((e) => {
            const k = KIND[e.kind] ?? KIND.log;
            const failed = e.kind === "cross" && e.ok === false;
            const text = tidy(e.text);
            const detail = tidy(e.detail);
            return (
              <div key={e.id} className="grid grid-cols-[40px_44px_minmax(0,1fr)] gap-x-2 px-4 py-0.5 leading-4 hover:bg-subtle">
                <span className="tabular-nums text-fg-4">{fmtClock(e.t)}</span>
                <span className={failed ? "text-warn" : k.cls}>
                  {e.kind === "cross" ? (
                    <span className="inline-flex items-center gap-0.5">
                      {!failed && <Check size={10} strokeWidth={3} />}
                      {k.label}
                    </span>
                  ) : (
                    k.label
                  )}
                </span>
                <span className="min-w-0">
                  <span className={e.kind === "call" || e.kind === "system" ? "text-fg" : e.kind === "warn" ? "text-warn" : e.kind === "error" ? "text-danger" : "text-fg-2"}>{text}</span>
                  {detail && <span className="line-clamp-2 break-all text-fg-3">{detail}</span>}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
