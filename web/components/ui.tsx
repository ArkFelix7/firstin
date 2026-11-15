"use client";

// Small, shared primitives. Everything visual in the app is built from these
// plus Tailwind utilities that map to the tokens in globals.css.

import { AlertTriangle, Loader2, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { sourceMeta, type NormCite } from "@/lib/plan";

/* ---------------- Button ---------------- */

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-on-accent border border-accent hover:bg-accent-hover hover:border-accent-hover",
  secondary: "bg-surface text-fg border border-line-strong hover:bg-subtle",
  danger: "bg-surface text-danger border border-line-strong hover:border-danger-line hover:bg-danger-subtle",
  ghost: "text-fg-2 border border-transparent hover:bg-muted hover:text-fg",
};
const SIZE: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-8 px-3 text-sm gap-1.5",
  lg: "h-10 px-4 text-base gap-2",
};

export function Button({
  variant = "secondary",
  size = "md",
  icon: Icon,
  loading,
  children,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; icon?: LucideIcon; loading?: boolean }) {
  const iconSize = size === "lg" ? 16 : 14;
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT[variant]} ${SIZE[size]} ${className}`}
    >
      {loading ? <Loader2 size={iconSize} className="animate-spin" /> : Icon ? <Icon size={iconSize} strokeWidth={2} /> : null}
      {children}
    </button>
  );
}

/* ---------------- Status badge ---------------- */

export type Tone = "neutral" | "accent" | "ok" | "warn" | "danger";
const TONE: Record<Tone, string> = {
  neutral: "bg-muted text-fg-2",
  accent: "bg-accent-subtle text-accent",
  ok: "bg-ok-subtle text-ok",
  warn: "bg-warn-subtle text-warn",
  danger: "bg-danger-subtle text-danger",
};

export function StatusBadge({ tone = "neutral", icon: Icon, children }: { tone?: Tone; icon?: LucideIcon; children: ReactNode }) {
  return (
    <span className={`inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-sm px-1.5 text-2xs font-medium ${TONE[tone]}`}>
      {Icon && <Icon size={12} strokeWidth={2.25} />}
      {children}
    </span>
  );
}

export function planStatusTone(status: string): { tone: Tone; label: string } {
  switch (status) {
    case "APPROVED":
      return { tone: "ok", label: "Approved" };
    case "PENDING_APPROVAL":
      return { tone: "warn", label: "Pending approval" };
    case "REJECTED":
      return { tone: "danger", label: "Rejected" };
    case "DRAFT":
    case "":
      return { tone: "neutral", label: "Draft" };
    default:
      return { tone: "neutral", label: status.charAt(0) + status.slice(1).toLowerCase().replace(/_/g, " ") };
  }
}

/* ---------------- Source attribution ---------------- */

/** Tiny shape per source so attribution survives grayscale and color blindness. */
export function SourceGlyph({ src, size = 8 }: { src: string; size?: number }) {
  const color = sourceMeta(src).color;
  const s = size;
  return (
    <svg width={s} height={s} viewBox="0 0 8 8" aria-hidden className="shrink-0">
      {src === "costar" ? (
        <rect x="0.5" y="0.5" width="7" height="7" rx="1" fill={color} />
      ) : src === "vexcel" ? (
        <path d="M4 0.3 L7.7 4 L4 7.7 L0.3 4 Z" fill={color} />
      ) : src === "matterport" ? (
        <circle cx="4" cy="4" r="3.6" fill={color} />
      ) : src === "officer" ? (
        <path d="M4 0.6 L7.6 7.2 L0.4 7.2 Z" fill={color} />
      ) : (
        <circle cx="4" cy="4" r="3" fill="none" stroke={color} strokeWidth="1.4" />
      )}
    </svg>
  );
}

export function SourceTag({
  cite,
  active,
  onClick,
  showConf = true,
}: {
  cite: NormCite | null;
  active?: boolean;
  onClick?: () => void;
  showConf?: boolean;
}) {
  if (!cite) return <span className="text-2xs text-fg-4">No source</span>;
  const m = sourceMeta(cite.src);
  const conf = cite.conf !== null ? Math.round(cite.conf * 100) : null;
  const Comp = onClick ? "button" : "span";
  return (
    <Comp
      {...(onClick
        ? {
            type: "button" as const,
            onClick: (e: React.MouseEvent) => {
              e.stopPropagation();
              onClick();
            },
          }
        : {})}
      title={`${m.label}${cite.id ? `, record ${cite.id}` : ""}${conf !== null ? `, ${conf}% confidence` : ""}`}
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm px-1 text-2xs ${
        active ? "text-fg" : "text-fg-2"
      } ${onClick ? "hover:bg-muted" : ""}`}
    >
      <SourceGlyph src={cite.src} />
      <span className="font-medium">{m.label}</span>
      {showConf && conf !== null && <span className="tabular-nums text-fg-3">{conf}%</span>}
    </Comp>
  );
}

/** Availability marker for a data layer (map list, legend). */
export function LayerLabel({ src, children }: { src: string; children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-fg-2">
      <SourceGlyph src={src} />
      {children ?? sourceMeta(src).label}
    </span>
  );
}

/* ---------------- Values ---------------- */

export function VerifyValue({ compact }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-medium text-warn">
      <AlertTriangle size={compact ? 12 : 14} strokeWidth={2.25} className="shrink-0" />
      Verify on site
    </span>
  );
}

export function Spinner({ size = 14, className = "" }: { size?: number; className?: string }) {
  return <Loader2 size={size} className={`shrink-0 animate-spin text-fg-3 ${className}`} />;
}

/* ---------------- Layout ---------------- */

export function PanelHeader({ title, meta, children }: { title: ReactNode; meta?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex h-10 shrink-0 items-center justify-between gap-3 border-b border-line px-4">
      <div className="flex min-w-0 items-center gap-2">
        <h2 className="truncate text-sm font-semibold text-fg">{title}</h2>
        {meta && <span className="truncate text-xs text-fg-3">{meta}</span>}
      </div>
      {children}
    </div>
  );
}

export function Section({ id, title, meta, aside, children }: { id?: string; title: ReactNode; meta?: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-4">
      <header className="flex items-end justify-between gap-4 pb-2">
        <div className="flex items-baseline gap-2">
          <h2 className="text-base font-semibold text-fg">{title}</h2>
          {meta && <span className="text-xs text-fg-3">{meta}</span>}
        </div>
        {aside && <div className="flex items-center gap-2 text-xs text-fg-3">{aside}</div>}
      </header>
      {children}
    </section>
  );
}

/** Key/value list with hairlines (definition list). */
export function KV({ rows, labelWidth = 120 }: { rows: Array<[ReactNode, ReactNode]>; labelWidth?: number }) {
  return (
    <dl className="divide-y divide-line">
      {rows.map(([k, v], i) => (
        <div key={i} className="grid gap-3 py-1.5" style={{ gridTemplateColumns: `${labelWidth}px minmax(0,1fr)` }}>
          <dt className="text-xs leading-5 text-fg-3">{k}</dt>
          <dd className="min-w-0 break-words text-sm text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-2xs text-fg-2 ${className}`}>{children}</span>;
}

/* ---------------- Table ---------------- */

export function Th({ children, align = "left", className = "" }: { children?: ReactNode; align?: "left" | "right"; className?: string }) {
  return (
    <th className={`h-8 border-b border-line bg-subtle px-3 text-xs font-medium text-fg-3 ${align === "right" ? "text-right" : "text-left"} ${className}`}>
      {children}
    </th>
  );
}

export function Td({ children, align = "left", className = "", colSpan }: { children?: ReactNode; align?: "left" | "right"; className?: string; colSpan?: number }) {
  return (
    <td colSpan={colSpan} className={`border-b border-line px-3 py-2 align-top text-sm ${align === "right" ? "text-right" : ""} ${className}`}>
      {children}
    </td>
  );
}
