"use client";

// Hosted-mode access code screen (lib/auth.ts). Renders children untouched unless
// NEXT_PUBLIC_API_URL points at a remote API, so local runs behave exactly as before.

import { KeyRound } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { apiBase } from "@/lib/api";
import { getToken, remoteApi, setApiToken } from "@/lib/auth";
import { LogoMark } from "./Brand";
import { Button, Spinner } from "./ui";

/** The one-field form, shared by the API gate and the /signin page (proxy.ts). */
export function AccessCodeForm({ onSubmit, error }: { onSubmit: (code: string) => Promise<void> | void; error?: string | null }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    try {
      await onSubmit(code.trim());
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex h-dvh items-center justify-center bg-canvas p-4">
      <form onSubmit={submit} className="w-full max-w-xs space-y-4 rounded border border-line bg-surface p-5">
        <div className="flex items-center gap-2">
          <LogoMark />
          <span className="text-sm font-semibold text-fg">FirstIn</span>
        </div>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-fg-2">Access code</span>
          <span className="flex h-8 items-center gap-2 rounded border border-line-strong bg-surface px-2.5 focus-within:border-accent">
            <KeyRound size={14} className="shrink-0 text-fg-3" />
            <input
              type="password"
              autoFocus
              autoComplete="current-password"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full bg-transparent text-sm text-fg placeholder:text-fg-4 focus:outline-none"
            />
          </span>
        </label>
        {error && <p className="text-xs text-danger">{error}</p>}
        <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!code.trim()}>
          Sign in
        </Button>
      </form>
    </div>
  );
}

/** 401 -> the code is wrong/missing; anything else (ok, 5xx, network) -> let the app handle it as today. */
async function apiAccepts(code: string | null): Promise<boolean> {
  try {
    const r = await fetch(`${apiBase()}/buildings/search?limit=1`, {
      cache: "no-store",
      headers: code ? { Authorization: `Bearer ${code}` } : {},
      signal: AbortSignal.timeout(8000),
    });
    return r.status !== 401;
  } catch {
    return true;
  }
}

function RemoteGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [state, setState] = useState<"checking" | "ok" | "signin">("checking");
  const [error, setError] = useState<string | null>(null);

  const onSignin = pathname === "/signin";
  useEffect(() => {
    if (onSignin) return; // page lock screen (proxy.ts); the API check runs after it
    let alive = true;
    const t = getToken();
    apiAccepts(t).then((ok) => {
      if (!alive) return;
      if (ok && t) setApiToken(t);
      if (!ok && t) setError("That code didn't work.");
      setState(ok ? "ok" : "signin");
    });
    return () => {
      alive = false;
    };
  }, [onSignin]);

  if (onSignin || state === "ok") return <>{children}</>;
  if (state === "checking") {
    return (
      <div className="flex h-dvh items-center justify-center bg-canvas text-fg-3">
        <Spinner />
      </div>
    );
  }
  return (
    <AccessCodeForm
      error={error}
      onSubmit={async (code) => {
        if (await apiAccepts(code)) {
          setApiToken(code);
          setError(null);
          setState("ok");
        } else {
          setError("That code didn't work.");
        }
      }}
    />
  );
}

export function AccessGate({ children }: { children: ReactNode }) {
  return remoteApi() ? <RemoteGate>{children}</RemoteGate> : <>{children}</>;
}
