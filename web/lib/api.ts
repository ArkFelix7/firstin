// HTTP/SSE client for the FastAPI agent server (CONTRACTS.md), with automatic
// fallback to the in-browser mock when the server is unreachable.

import * as mock from "./mock";
import type { AgentEvent, ApproveBody, Building, IncabSummary, Plan } from "./types";

/**
 * API origin. NEXT_PUBLIC_API_URL wins; otherwise use the host the page was
 * served from on :8000 (so a Pi on the LAN hitting http://<laptop-ip>:3000/incab
 * talks to http://<laptop-ip>:8000).
 */
export function apiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_URL;
  if (env) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") return `${window.location.protocol}//${window.location.hostname}:8000`;
  return "http://localhost:8000";
}

export type Mode = "live" | "mock";

let modePromise: Promise<Mode> | null = null;

function forcedMode(): Mode | null {
  if (process.env.NEXT_PUBLIC_MOCK === "1") return "mock";
  if (typeof window !== "undefined") {
    const q = new URLSearchParams(window.location.search).get("mock");
    if (q === "1") return "mock";
    if (q === "0") return "live";
  }
  return null;
}

/** Resolves once per page load: "live" if GET /buildings answers, else "mock". */
export function getMode(): Promise<Mode> {
  const forced = forcedMode();
  if (forced) return Promise.resolve(forced);
  if (!modePromise) {
    modePromise = fetch(`${apiBase()}/buildings`, { signal: AbortSignal.timeout(1500), cache: "no-store" })
      .then((r) => (r.ok ? "live" : "mock") as Mode)
      .catch(() => "mock" as Mode);
  }
  return modePromise;
}

export const isMockRun = (runId: string) => runId.startsWith("mock-");

/** Resolve backend-relative asset paths (/static/...) against the API origin. */
export function assetUrl(u: unknown): string | null {
  if (typeof u !== "string" || !u) return null;
  if (/^(https?:|data:|blob:)/.test(u) || u.startsWith("/mock/")) return u;
  return `${apiBase()}${u.startsWith("/") ? "" : "/"}${u}`;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${apiBase()}${path}`, {
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!r.ok) throw new Error(`${init?.method ?? "GET"} ${path} → ${r.status}`);
  return (await r.json()) as T;
}

export async function getBuildings(): Promise<{ mode: Mode; buildings: Building[] }> {
  const mode = await getMode();
  if (mode === "mock") return { mode, buildings: mock.MOCK_BUILDINGS };
  try {
    const raw = await json<Building[] | { buildings: Building[] }>("/buildings");
    const buildings = Array.isArray(raw) ? raw : raw.buildings;
    return { mode, buildings };
  } catch {
    return { mode: "mock", buildings: mock.MOCK_BUILDINGS };
  }
}

export async function startPreplan(buildingId: string): Promise<string> {
  const mode = await getMode();
  if (mode === "mock") return mock.mockRunId(buildingId);
  const r = await json<{ run_id: string }>("/preplan", {
    method: "POST",
    body: JSON.stringify({ building_id: buildingId }),
  });
  return r.run_id;
}

/** GET /plan/{runId}: accepts either the bare plan (with status) or {plan, status}. */
export async function getPlan(runId: string): Promise<Plan | null> {
  if (isMockRun(runId)) return mock.mockGetPlan(runId);
  try {
    const raw = await json<Record<string, unknown>>(`/plan/${encodeURIComponent(runId)}`);
    if (raw && typeof raw.plan === "object" && raw.plan) {
      return { ...(raw.plan as Plan), status: (raw.status as string) ?? (raw.plan as Plan).status };
    }
    return raw as Plan;
  } catch {
    return null;
  }
}

const EVENT_TYPES = [
  "todo",
  "subagent_start",
  "subagent_end",
  "tool_call",
  "tool_result",
  "evidence",
  "plan",
  "interrupt",
  "published",
  "log",
  "error",
  "done",
];

export interface StreamHandlers {
  onEvent: (e: AgentEvent) => void;
  onStatus?: (s: "connecting" | "open" | "closed" | "error") => void;
}

/** Subscribe to GET /stream/{runId}. Returns an unsubscribe function. */
export function streamRun(runId: string, h: StreamHandlers): () => void {
  if (isMockRun(runId)) {
    h.onStatus?.("open");
    return mock.mockSubscribe(runId, h.onEvent);
  }
  h.onStatus?.("connecting");
  const es = new EventSource(`${apiBase()}/stream/${encodeURIComponent(runId)}`);
  const seen = new Set<string>(); // de-dupe if the server replays history on reconnect
  let finished = false;

  const handle = (data: string, named?: string) => {
    if (seen.has(data)) return;
    seen.add(data);
    let parsed: AgentEvent;
    try {
      parsed = JSON.parse(data) as AgentEvent;
    } catch {
      return;
    }
    if (!parsed.type && named) parsed.type = named;
    if (!parsed.payload) {
      // tolerate flat events: {"type": "...", ...fields}
      const { type, ts, ...rest } = parsed as AgentEvent & Record<string, unknown>;
      parsed = { type, ts, payload: rest };
    }
    h.onEvent(parsed);
    if (parsed.type === "done") {
      finished = true;
      es.close();
      h.onStatus?.("closed");
    }
  };

  es.onopen = () => h.onStatus?.("open");
  es.onmessage = (m) => handle(m.data);
  for (const t of EVENT_TYPES) es.addEventListener(t, (m) => handle((m as MessageEvent).data, t));
  es.onerror = () => {
    if (finished) return;
    h.onStatus?.(es.readyState === EventSource.CLOSED ? "closed" : "error");
  };
  return () => {
    finished = true;
    es.close();
  };
}

export async function approve(runId: string, body: ApproveBody): Promise<void> {
  if (isMockRun(runId)) {
    await mock.mockApprove(runId, body);
    return;
  }
  await json(`/approve/${encodeURIComponent(runId)}`, { method: "POST", body: JSON.stringify(body) });
}

export async function getIncab(): Promise<{ mode: Mode; summary: IncabSummary | null }> {
  const mode = await getMode();
  if (mode === "mock") return { mode, summary: mock.mockIncab() };
  const r = await fetch(`${apiBase()}/incab/active`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
  if (r.status === 404 || r.status === 204) return { mode, summary: null };
  if (!r.ok) throw new Error(`incab ${r.status}`);
  const data = (await r.json()) as IncabSummary | null | Record<string, never>;
  if (!data || !("plan_id" in data) || !data.plan_id) return { mode, summary: null };
  return { mode, summary: data as IncabSummary };
}

export async function ask(planId: string, question: string, summary: IncabSummary | null): Promise<string> {
  const mode = await getMode();
  if (mode === "mock") {
    await new Promise((r) => setTimeout(r, 600));
    return mock.mockAsk(question, summary);
  }
  const r = await json<{ answer: string }>("/ask", {
    method: "POST",
    body: JSON.stringify({ plan_id: planId, question }),
  });
  return r.answer;
}
