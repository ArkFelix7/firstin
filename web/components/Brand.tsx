import Link from "next/link";

/** Flat mark: ink square with a roof-line chevron. Works on light and dark. */
export function LogoMark({ size = 20, inverted = false }: { size?: number; inverted?: boolean }) {
  const bg = inverted ? "#f3f5f7" : "#16191d";
  const fg = inverted ? "#16191d" : "#ffffff";
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden className="shrink-0">
      <rect width="20" height="20" rx="4" fill={bg} />
      <path d="M5 13.5 L10 6.5 L15 13.5" fill="none" stroke={fg} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M8 15.5 H12" stroke="#c4433b" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Brand({ inverted }: { inverted?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2" aria-label="FirstIn home">
      <LogoMark inverted={inverted} />
      <span className="text-sm font-semibold text-fg">FirstIn</span>
    </Link>
  );
}

export function ModeBadge({ mode }: { mode: "live" | "mock" | null }) {
  const label = !mode ? "Connecting" : mode === "live" ? "Agent server connected" : "Replay mode";
  const color = !mode ? "bg-fg-4" : mode === "live" ? "bg-ok" : "bg-warn";
  return (
    <span
      title={mode === "mock" ? "Agent server unreachable. Replaying a recorded run." : undefined}
      className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs text-fg-2"
    >
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}
