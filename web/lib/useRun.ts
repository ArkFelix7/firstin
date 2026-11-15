"use client";

import { useEffect, useReducer } from "react";
import { getPlan, streamRun } from "./api";
import { laneForTool, laneKey } from "./plan";
import type { AgentEvent, Plan } from "./types";

export type TodoStatus = "pending" | "in_progress" | "completed";
export interface Todo {
  content: string;
  status: TodoStatus;
}

export type LaneStatus = "idle" | "running" | "done" | "error";
export interface Lane {
  key: string;
  label: string;
  role: string;
  status: LaneStatus;
  task?: string;
  last?: string;
  summary?: string;
  calls: number;
  startedAt?: number;
  endedAt?: number;
}

export interface LogEntry {
  id: number;
  t: number;
  kind: "call" | "result" | "log" | "warn" | "error" | "evidence" | "system" | "cross";
  ok?: boolean;
  agent: string;
  text: string;
  detail?: string;
}

export interface RunState {
  todos: Todo[];
  lanes: Record<string, Lane>;
  log: LogEntry[];
  plan: Plan | null;
  interrupt: Record<string, unknown> | null;
  published: Record<string, unknown> | null;
  evidence: Record<string, Record<string, unknown>>;
  error: string | null;
  done: boolean;
  conn: "connecting" | "open" | "closed" | "error";
  t0: number | null;
  tEnd: number | null;
}

export const LANES: Array<Pick<Lane, "key" | "label" | "role">> = [
  { key: "costar", label: "costar-analyst", role: "CoStar · tenants, era, size" },
  { key: "aerial", label: "aerial-analyst", role: "Vexcel · roof, access, exposures" },
  { key: "interior", label: "interior-analyst", role: "Matterport · stairs, FP, utilities" },
  { key: "hazards", label: "hazard-reasoner", role: "Rules + LLM · hazard inference" },
  { key: "validator", label: "validator", role: "Cite-or-flag gate" },
];

function initial(): RunState {
  return {
    todos: [],
    lanes: Object.fromEntries(LANES.map((l) => [l.key, { ...l, status: "idle", calls: 0 }])),
    log: [],
    plan: null,
    interrupt: null,
    published: null,
    evidence: {},
    error: null,
    done: false,
    conn: "connecting",
    t0: null,
    tEnd: null,
  };
}

type Action =
  | { kind: "event"; e: AgentEvent; now: number }
  | { kind: "conn"; s: RunState["conn"] }
  | { kind: "plan"; plan: Plan }
  | { kind: "reset" };

let logId = 0;

function str(x: unknown): string {
  if (x === undefined || x === null) return "";
  if (typeof x === "string") return x;
  try {
    const s = JSON.stringify(x);
    return s.length > 160 ? s.slice(0, 157) + "…" : s;
  } catch {
    return String(x);
  }
}

function normTodos(p: Record<string, unknown>, prev: Todo[]): Todo[] {
  const list = (p.todos ?? p.items ?? null) as Array<Record<string, unknown>> | null;
  const conv = (t: Record<string, unknown>): Todo => {
    const raw = String(t.status ?? "pending").toLowerCase();
    const status: TodoStatus = /complete|done|finish/.test(raw) ? "completed" : /progress|running|active/.test(raw) ? "in_progress" : "pending";
    return { content: String(t.content ?? t.title ?? t.text ?? t.name ?? ""), status };
  };
  if (Array.isArray(list)) return list.map(conv);
  // single-todo update
  const one = conv(p);
  if (!one.content) return prev;
  const i = prev.findIndex((t) => t.content === one.content);
  if (i === -1) return [...prev, one];
  const next = prev.slice();
  next[i] = one;
  return next;
}

/* ---- todo derivation: agent mode emits write_todos rarely, so progress is inferred from lanes ---- */

const RANK: Record<TodoStatus, number> = { pending: 0, in_progress: 1, completed: 2 };

function todoClass(content: string): string {
  const c = content.toLowerCase();
  if (/approv|publish/.test(c)) return "publish";
  if (/validat/.test(c)) return "validator";
  if (/assembl|draft/.test(c)) return "assemble";
  if (/hazard/.test(c)) return "hazards";
  if (/resolve/.test(c)) return "resolve";
  if (/matterport|interior|stair|fire prot/.test(c)) return "interior";
  if (/vexcel|access|roof|exposure|aerial/.test(c)) return "aerial";
  if (/costar|building|occupan|tenant/.test(c)) return "costar";
  return "other";
}

/** Upgrade (never downgrade) todos of the given classes. */
function bump(todos: Todo[], classes: string[] | "all", status: TodoStatus, except: string[] = []): Todo[] {
  let changed = false;
  const next = todos.map((t) => {
    const cls = todoClass(t.content);
    if (except.includes(cls)) return t;
    if (classes !== "all" && !classes.includes(cls)) return t;
    if (RANK[status] <= RANK[t.status]) return t;
    changed = true;
    return { ...t, status };
  });
  return changed ? next : todos;
}

/** Merge a todo-list event without regressing progress we already derived. */
function mergeTodos(prev: Todo[], incoming: Todo[]): Todo[] {
  return incoming.map((t) => {
    const old = prev.find((o) => o.content === t.content);
    return old && RANK[old.status] > RANK[t.status] ? old : t;
  });
}

function reduce(s: RunState, a: Action): RunState {
  if (a.kind === "reset") return initial();
  if (a.kind === "conn") return { ...s, conn: a.s };
  if (a.kind === "plan") return s.plan ? s : { ...s, plan: a.plan };

  const { e, now } = a;
  const p = (e.payload ?? {}) as Record<string, unknown>;
  const t0 = s.t0 ?? now;
  const agentName = String(p.agent ?? p.subagent ?? p.name ?? "planner");
  const push = (entry: Omit<LogEntry, "id" | "t">): LogEntry[] => {
    const next = [...s.log, { ...entry, id: ++logId, t: now - t0 }];
    return next.length > 400 ? next.slice(-400) : next;
  };
  const touchLane = (key: string | null, patch: Partial<Lane>, bumpCalls = false) => {
    if (!key || !s.lanes[key]) return s.lanes;
    const cur = s.lanes[key];
    return {
      ...s.lanes,
      [key]: { ...cur, ...patch, calls: cur.calls + (bumpCalls ? 1 : 0), status: patch.status ?? (cur.status === "idle" ? "running" : cur.status), startedAt: cur.startedAt ?? now },
    };
  };

  switch (e.type) {
    case "todo":
      return { ...s, t0, todos: mergeTodos(s.todos, normTodos(p, s.todos)) };
    case "subagent_start": {
      const name = String(p.name ?? p.subagent ?? "subagent");
      const key = laneKey(name);
      return {
        ...s,
        t0,
        lanes: touchLane(key, { status: "running", task: str(p.task ?? p.description), startedAt: now, endedAt: undefined }),
        todos: bump(
          bump(bump(s.todos, ["resolve"], "completed"), [key], "in_progress"),
          key === "validator" ? ["assemble", "hazards", "costar", "aerial", "interior"] : [],
          "completed",
        ),
        log: push({ kind: "system", agent: name, text: `▶ ${name} started`, detail: str(p.task ?? p.description) }),
      };
    }
    case "subagent_end": {
      const name = String(p.name ?? p.subagent ?? "subagent");
      const key = laneKey(name);
      const failed = p.ok === false || !!p.error;
      return {
        ...s,
        t0,
        lanes: touchLane(key, { status: failed ? "error" : "done", summary: str(p.summary ?? p.result ?? p.error), endedAt: now }),
        todos: bump(s.todos, key === "validator" ? ["validator", "assemble"] : [key], "completed"),
        log: push({ kind: failed ? "error" : "system", agent: name, text: `■ ${name} ${failed ? "failed" : "finished"}`, detail: str(p.summary ?? p.result ?? p.error) }),
      };
    }
    case "tool_call": {
      const tool = String(p.name ?? p.tool ?? "tool");
      const key = p.agent || p.subagent ? laneKey(String(p.agent ?? p.subagent)) : laneForTool(tool);
      return {
        ...s,
        t0,
        lanes: key && key !== "planner" ? touchLane(key, { last: `${tool}(…)` }, true) : s.lanes,
        log: push({ kind: "call", agent: String(p.agent ?? p.subagent ?? key ?? "planner"), text: tool, detail: str(p.args ?? p.input) }),
      };
    }
    case "tool_result": {
      const tool = String(p.name ?? p.tool ?? "tool");
      const key = p.agent || p.subagent ? laneKey(String(p.agent ?? p.subagent)) : laneForTool(tool);
      const summary = str(p.summary ?? p.result ?? p.output);
      return {
        ...s,
        t0,
        lanes: key && key !== "planner" ? touchLane(key, { last: summary || `${tool} ✓` }) : s.lanes,
        log: push({ kind: "result", agent: String(p.agent ?? p.subagent ?? key ?? "planner"), text: tool, detail: summary }),
      };
    }
    case "evidence": {
      const source = String(p.source ?? p.src ?? "evidence").toLowerCase();
      return {
        ...s,
        t0,
        evidence: {
          ...s.evidence,
          [source]: {
            ...(s.evidence[source] ?? {}),
            ...p,
            files: { ...((s.evidence[source]?.files as Record<string, unknown>) ?? {}), [String(p.path ?? source)]: p.content ?? p },
          },
        },
        log: push({ kind: "evidence", agent: agentName, text: `wrote ${str(p.path ?? p.file ?? `/evidence/${source}.json`)}` }),
      };
    }
    case "plan": {
      const plan = { ...((p.plan ?? p) as Plan) };
      if (p.plan && typeof p.status === "string") plan.status = p.status;
      // merge so partial section updates accumulate
      const merged: Plan = { ...(s.plan ?? {}) };
      for (const [k, v] of Object.entries(plan)) if (v !== undefined) merged[k] = v;
      const pending = String(merged.status ?? "").toUpperCase() === "PENDING_APPROVAL";
      return { ...s, t0, plan: merged, todos: pending ? bump(s.todos, "all", "completed", ["publish"]) : s.todos };
    }
    case "interrupt":
      return {
        ...s,
        t0,
        interrupt: p,
        tEnd: s.tEnd ?? now,
        todos: bump(bump(s.todos, "all", "completed", ["publish"]), ["publish"], "in_progress"),
        plan: s.plan ? { ...s.plan, status: "PENDING_APPROVAL" } : s.plan,
        log: push({ kind: "warn", agent: "planner", text: "⏸ interrupt: awaiting officer approval", detail: str(p.message ?? p.action) }),
      };
    case "published":
      return {
        ...s,
        t0,
        published: p,
        interrupt: null,
        todos: bump(s.todos, "all", "completed"),
        plan: s.plan ? { ...s.plan, status: "APPROVED" } : s.plan,
        log: push({ kind: "system", agent: "planner", text: "✓ published to in-cab", detail: str(p.pdf_url ?? "") }),
      };
    case "log": {
      const level = String(p.level ?? "info");
      if (p.kind === "cross_check") {
        return { ...s, t0, log: push({ kind: "cross", ok: p.agree !== false, agent: agentName, text: str(p.msg ?? p.message ?? p.text) }) };
      }
      return { ...s, t0, log: push({ kind: level === "warn" ? "warn" : level === "error" ? "error" : "log", agent: agentName, text: str(p.msg ?? p.message ?? p.text) }) };
    }
    case "error":
      return { ...s, t0, error: str(p.message ?? p.error ?? "Agent error"), log: push({ kind: "error", agent: agentName, text: str(p.message ?? p.error ?? "error") }) };
    case "done": {
      const approved = String(p.status ?? "").toUpperCase() === "APPROVED" || !!s.published;
      return { ...s, t0, done: true, tEnd: s.tEnd ?? now, todos: approved ? bump(s.todos, "all", "completed") : s.todos };
    }
    default:
      return { ...s, t0, log: push({ kind: "log", agent: agentName, text: `${e.type}: ${str(p)}` }) };
  }
}

export function useRun(runId: string) {
  const [state, dispatch] = useReducer(reduce, undefined, initial);

  useEffect(() => {
    dispatch({ kind: "reset" });
    let alive = true;
    const unsub = streamRun(runId, {
      // use the server timestamp when present so replayed history keeps its real timing
      onEvent: (e) => alive && dispatch({ kind: "event", e, now: typeof e.ts === "number" ? e.ts * 1000 : Date.now() }),
      onStatus: (st) => alive && dispatch({ kind: "conn", s: st }),
    });
    // hydrate from GET /plan in case we joined late (does not override streamed plan)
    getPlan(runId).then((plan) => {
      if (alive && plan && Object.keys(plan).length > 1) dispatch({ kind: "plan", plan });
    });
    return () => {
      alive = false;
      unsub();
    };
  }, [runId]);

  return state;
}
