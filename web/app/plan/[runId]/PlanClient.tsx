"use client";

import { ChevronLeft, ChevronRight, Timer } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Brand, ModeBadge } from "@/components/Brand";
import { ApprovalBar, type ApprovalProps } from "@/components/plan/ApprovalBar";
import { EvidenceViewer } from "@/components/plan/EvidenceViewer";
import { OFFICER_CITE, PlanSheet, type Selection } from "@/components/plan/PlanSheet";
import { TracePanel } from "@/components/plan/TracePanel";
import { approve, getBuildings, isMockRun, type Mode } from "@/lib/api";
import { mockBuilding } from "@/lib/mock";
import { coverage, normCite, normField } from "@/lib/plan";
import { Mono, PanelHeader, Spinner, StatusBadge, planStatusTone } from "@/components/ui";
import type { Building, Plan } from "@/lib/types";
import { useRun } from "@/lib/useRun";

/** Until the officer clicks something, the evidence viewer follows the most compelling cited fact. */
function followSelection(plan: Plan | null): Selection | null {
  if (!plan) return null;
  const rawStairs = plan.interior?.stairwells;
  const stairs = Array.isArray(rawStairs) ? (rawStairs as Array<Record<string, unknown>>) : undefined;
  const sp = stairs?.findIndex((s) => s.standpipe && normCite(s.cite));
  if (stairs && sp !== undefined && sp >= 0) {
    const s = stairs[sp];
    return { path: `interior.stairwells.${sp}.loc`, label: `Stairwell ${String.fromCharCode(65 + sp)}, standpipe`, value: String(s.loc), cite: normCite(s.cite) };
  }
  const firstStair = stairs?.findIndex((s) => normCite(s.cite)) ?? -1;
  if (stairs && firstStair >= 0) {
    const s = stairs[firstStair];
    return { path: `interior.stairwells.${firstStair}.loc`, label: `Stairwell ${String.fromCharCode(65 + firstStair)}`, value: String(s.loc), cite: normCite(s.cite) };
  }
  const roof = normField(plan.access?.roof_access);
  if (roof.cite) return { path: "access.roof_access", label: "Roof access", value: String(roof.value), cite: roof.cite };
  return null;
}

function useElapsed(t0: number | null, tEnd: number | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!t0 || tEnd) return;
    const id = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(id);
  }, [t0, tEnd]);
  if (!t0) return 0;
  return Math.max(0, (tEnd ?? now) - t0);
}

export function PlanClient() {
  const { runId: raw } = useParams<{ runId: string }>();
  const runId = decodeURIComponent(raw);
  const search = useSearchParams();
  const bParam = search.get("b");
  const state = useRun(runId);

  const [mode, setMode] = useState<Mode | null>(isMockRun(runId) ? "mock" : null);
  const [buildings, setBuildings] = useState<Building[]>([]);
  useEffect(() => {
    if (isMockRun(runId)) return;
    getBuildings().then((r) => {
      setMode(r.mode === "live" ? "live" : "mock");
      setBuildings(r.buildings);
    });
  }, [runId]);

  const building = useMemo<Building | null>(() => {
    if (isMockRun(runId)) return mockBuilding(runId.replace(/^mock-/, "").replace(/-[a-z0-9]+$/, ""));
    const addr = state.plan?.building?.address;
    return buildings.find((b) => b.building_id === bParam) ?? buildings.find((b) => addr && b.address === addr) ?? null;
  }, [runId, buildings, bParam, state.plan?.building?.address]);

  const [userSel, setUserSel] = useState<Selection | null>(null);
  const baseSel = userSel ?? followSelection(state.plan);

  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [officer, setOfficer] = useState("Capt. Station 12");
  const [submitting, setSubmitting] = useState(false);
  const [submitErr, setSubmitErr] = useState<string | null>(null);

  const onEdit = useCallback((path: string, v: string) => setEdits((e) => ({ ...e, [path]: v })), []);
  const editedValue = baseSel ? (edits[baseSel.path] ?? "").trim() : "";
  // an officer edit supersedes the agent's value in the evidence panel too
  const selection = baseSel && editedValue ? { ...baseSel, value: editedValue, cite: OFFICER_CITE } : baseSel;

  const decide = async (decision: "approve" | "reject") => {
    setSubmitting(true);
    setSubmitErr(null);
    try {
      const clean = Object.fromEntries(Object.entries(edits).filter(([, v]) => v.trim() !== ""));
      await approve(runId, {
        approved_by: officer,
        decision,
        ...(decision === "approve" && Object.keys(clean).length ? { edits: clean } : {}),
      });
      setEditing(false);
    } catch (e) {
      setSubmitErr(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setSubmitting(false);
    }
  };

  const status = String(state.plan?.status ?? "").toUpperCase();
  const phase: ApprovalProps["phase"] =
    state.published || status === "APPROVED"
      ? "published"
      : status === "REJECTED"
        ? "rejected"
        : submitting
          ? "submitting"
          : state.interrupt
            ? "awaiting"
            : (state.error && !state.plan) || submitErr
              ? "error"
              : "running";

  const elapsed = useElapsed(state.t0, state.tEnd);
  const todosDone = state.todos.filter((t) => t.status === "completed").length;
  const address = (state.plan?.building?.address as string) ?? building?.address ?? "Resolving building";

  const st = planStatusTone(state.published ? "APPROVED" : status);
  const verifyCount = useMemo(() => coverage(state.plan).verify, [state.plan]);
  const connLabel = state.done ? "Stream closed" : state.conn === "open" ? "Streaming" : state.conn === "error" ? "Reconnecting" : state.conn === "closed" ? "Stream closed" : "Connecting";
  const connColor = state.conn === "open" && !state.done ? "bg-ok" : state.conn === "error" ? "bg-danger" : "bg-fg-4";

  return (
    <div className="flex h-dvh min-h-[640px] flex-col bg-canvas">
      <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-line-strong bg-surface px-4">
        <div className="flex min-w-0 items-center gap-3">
          <Link href="/" className="flex h-7 w-7 items-center justify-center rounded text-fg-3 hover:bg-muted hover:text-fg" aria-label="Back to map">
            <ChevronLeft size={16} />
          </Link>
          <Brand />
          <span className="h-5 w-px bg-line-strong" />
          <nav className="flex min-w-0 items-center gap-1.5 text-sm" aria-label="Breadcrumb">
            <Link href="/" className="text-fg-3 hover:text-fg">
              Pre-plans
            </Link>
            <ChevronRight size={14} className="shrink-0 text-fg-4" />
            <span className="truncate font-medium text-fg">{address}</span>
          </nav>
          <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
        </div>
        <div className="flex shrink-0 items-center gap-5 text-xs text-fg-2">
          <span className="text-fg-3">
            Run <Mono>{runId}</Mono>
          </span>
          <span className="flex items-center gap-1.5">
            <Timer size={14} className="text-fg-3" />
            <span className="tabular-nums">{(elapsed / 1000).toFixed(1)} s</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${connColor}`} />
            {connLabel}
          </span>
          <ModeBadge mode={mode} />
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(272px,300px)_minmax(0,1fr)_minmax(360px,420px)]">
        <aside className="flex min-h-0 flex-col border-r border-line-strong bg-surface">
          <PanelHeader title="Agent run" meta="deepagents">
            {!state.tEnd && !state.done ? <Spinner size={12} /> : null}
          </PanelHeader>
          <div className="min-h-0 flex-1">
            <TracePanel state={state} />
          </div>
        </aside>

        <main className="flex min-h-0 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <PlanSheet plan={state.plan} lanes={state.lanes} runId={runId} ctx={{ selected: selection?.path ?? null, onSelect: setUserSel, editing, edits, onEdit }} />
          </div>
          <ApprovalBar
            phase={phase}
            editing={editing}
            editCount={Object.values(edits).filter((v) => v.trim()).length}
            officer={officer}
            setOfficer={setOfficer}
            onApprove={() => decide("approve")}
            onReject={() => decide("reject")}
            onEdit={() => setEditing(true)}
            onCancelEdit={() => {
              setEditing(false);
              setEdits({});
            }}
            progress={{ done: todosDone, total: state.todos.length }}
            published={state.published}
            voiceBrief={state.plan?.voice_brief}
            error={submitErr ?? state.error}
            verifyCount={verifyCount}
            approvedBy={(state.plan?.approved_by as string | null | undefined) ?? null}
          />
        </main>

        <aside className="min-h-0 border-l border-line-strong bg-surface">
          <EvidenceViewer selection={selection} plan={state.plan} building={building} evidence={state.evidence} mock={mode === "mock"} onNavigate={setUserSel} />
        </aside>
      </div>
    </div>
  );
}
