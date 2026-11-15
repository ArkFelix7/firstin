"use client";

import { AlertCircle, ArrowUpRight, Check, CheckCircle2, FileText, Pencil, Play, Square, X, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button, Spinner, StatusBadge } from "@/components/ui";
import { assetUrl } from "@/lib/api";

export interface ApprovalProps {
  phase: "running" | "awaiting" | "submitting" | "published" | "rejected" | "error";
  editing: boolean;
  editCount: number;
  officer: string;
  setOfficer: (v: string) => void;
  onApprove: () => void;
  onReject: () => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  progress: { done: number; total: number };
  published: Record<string, unknown> | null;
  voiceBrief?: string;
  error?: string | null;
  verifyCount?: number;
  approvedBy?: string | null;
  unit?: string;
}

const fmtTime = (v: unknown) => {
  const d = typeof v === "number" ? new Date(v < 1e12 ? v * 1000 : v) : typeof v === "string" ? new Date(v) : new Date();
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
};

/** Docked review bar at the foot of the plan document, like a document sign-off. */
export function ApprovalBar(p: ApprovalProps) {
  return (
    <div className="@container relative flex h-16 shrink-0 items-center gap-3 overflow-hidden border-t border-line-strong bg-surface px-6">
      {p.phase === "running" && <Running {...p} />}
      {(p.phase === "awaiting" || p.phase === "submitting") && (p.editing ? <Editing {...p} /> : <Awaiting {...p} />)}
      {p.phase === "published" && <Published {...p} />}
      {p.phase === "rejected" && (
        <>
          <XCircle size={16} className="shrink-0 text-danger" />
          <div className="min-w-0 flex-1 truncate text-sm text-fg">
            Rejected{p.approvedBy ? ` by ${p.approvedBy}` : ""}. The plan was not published.
          </div>
          <Link href="/" className="shrink-0 text-sm font-medium text-accent hover:underline">
            Back to map
          </Link>
        </>
      )}
      {p.phase === "error" && (
        <>
          <AlertCircle size={16} className="shrink-0 text-danger" />
          <div className="min-w-0 flex-1 truncate text-sm text-fg" title={p.error ?? undefined}>
            {p.error ?? "The agent reported an error."}
          </div>
        </>
      )}
    </div>
  );
}

function Running({ progress }: ApprovalProps) {
  const pct = progress.total ? (progress.done / progress.total) * 100 : 4;
  return (
    <>
      <div className="absolute inset-x-0 top-0 h-0.5 bg-muted" aria-hidden>
        <div className="h-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
      <Spinner />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-fg">
          Agent is assembling the plan
          <span className="ml-2 tabular-nums text-fg-3">
            {progress.done} of {progress.total || "?"} steps
          </span>
        </div>
        <div className="truncate text-xs text-fg-3">Review opens when every field is cited or flagged.</div>
      </div>
      <Button disabled icon={Check} variant="primary">
        Approve and publish
      </Button>
    </>
  );
}

function Awaiting(p: ApprovalProps) {
  const busy = p.phase === "submitting";
  return (
    <>
      <div className="flex min-w-0 flex-1 items-center gap-4">
        <span className="hidden @[700px]:inline-flex">
          <StatusBadge tone="warn">Review required</StatusBadge>
        </span>
        <label className="flex shrink-0 items-center gap-2 text-xs text-fg-3">
          <span className="hidden @[640px]:inline">Reviewer</span>
          <input
            value={p.officer}
            onChange={(e) => p.setOfficer(e.target.value)}
            aria-label="Reviewer"
            className="h-8 w-[180px] shrink-0 rounded border border-line-strong bg-surface px-2 text-sm text-fg focus:border-accent focus:outline-none"
          />
        </label>
        {p.verifyCount ? (
          <a href="#walkthrough" className="hidden min-w-0 truncate text-xs text-fg-2 hover:underline @[920px]:block">
            {p.verifyCount} fields to verify on site
          </a>
        ) : null}
      </div>
      <Button onClick={p.onReject} disabled={busy} icon={X} variant="danger">
        Reject
      </Button>
      <Button onClick={p.onEdit} disabled={busy} icon={Pencil}>
        Edit
      </Button>
      <Button onClick={p.onApprove} disabled={busy} loading={busy} icon={Check} variant="primary">
        Approve<span className="-ml-0.5 hidden @[640px]:inline">and publish</span>
      </Button>
    </>
  );
}

function Editing(p: ApprovalProps) {
  const busy = p.phase === "submitting";
  return (
    <>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <StatusBadge tone="accent" icon={Pencil}>
          Editing
        </StatusBadge>
        <span className="min-w-0 truncate text-sm text-fg-2">
          {p.editCount} change{p.editCount === 1 ? "" : "s"}. Edited values are cited to {p.officer || "the officer"}.
        </span>
      </div>
      <Button onClick={p.onCancelEdit} disabled={busy} variant="ghost">
        Cancel
      </Button>
      <Button onClick={p.onApprove} disabled={busy} loading={busy} icon={Check} variant="primary">
        Save and approve
      </Button>
    </>
  );
}

function Published({ published, voiceBrief, approvedBy, officer, unit = "Engine 12" }: ApprovalProps) {
  const pdf = assetUrl(published?.pdf_url);
  const audio = assetUrl(published?.audio_url);
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  useEffect(
    () => () => {
      window.speechSynthesis?.cancel();
      audioRef.current?.pause();
    },
    [],
  );
  const speak = () => {
    if (audio) {
      if (speaking) {
        audioRef.current?.pause();
        setSpeaking(false);
        return;
      }
      audioRef.current?.pause();
      const a = new Audio(audio);
      a.addEventListener("ended", () => setSpeaking(false));
      audioRef.current = a;
      setSpeaking(true);
      a.play().catch(() => setSpeaking(false));
      return;
    }
    const synth = window.speechSynthesis;
    if (!synth || !voiceBrief) return;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    const u = new SpeechSynthesisUtterance(voiceBrief);
    u.rate = 1.02;
    u.onend = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(u);
  };
  const at = fmtTime(published?.approved_at ?? published?.published_at);
  return (
    <>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <CheckCircle2 size={16} className="shrink-0 text-ok" />
        <div className="min-w-0">
          <div className="truncate text-sm text-fg">
            Approved by {approvedBy ?? officer}
            {at ? ` at ${at}` : ""}. Published to {unit}.
          </div>
          <div className="truncate text-xs text-fg-3">The in-cab display and voice brief are updated.</div>
        </div>
      </div>
      <Button onClick={speak} disabled={!voiceBrief && !audio} icon={speaking ? Square : Play}>
        {speaking ? "Stop" : "Play voice brief"}
      </Button>
      {pdf ? (
        <a href={pdf} target="_blank" rel="noreferrer" className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded border border-line-strong bg-surface px-3 text-sm font-medium text-fg hover:bg-subtle">
          <FileText size={14} /> PDF
        </a>
      ) : (
        <Button onClick={() => window.print()} icon={FileText}>
          Print
        </Button>
      )}
      <Link href="/incab" target="_blank" className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded border border-accent bg-accent px-3 text-sm font-medium text-on-accent hover:bg-accent-hover">
        In-cab display <ArrowUpRight size={14} />
      </Link>
    </>
  );
}
