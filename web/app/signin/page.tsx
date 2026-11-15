"use client";

// Page lock screen for hosted mode (proxy.ts redirects here when SITE_ACCESS_CODE is set).
// Sets the `firstin_key` cookie and reloads the target; the proxy checks the code server-side.

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { AccessCodeForm } from "@/components/AccessGate";
import { setSiteCookie } from "@/lib/auth";

function SignIn() {
  const params = useSearchParams();
  const n = params.get("next") || "/";
  const next = n.startsWith("/") && !n.startsWith("//") ? n : "/";
  return (
    <AccessCodeForm
      error={params.has("error") ? "That code didn't work." : null}
      onSubmit={(code) => {
        setSiteCookie(code);
        window.location.assign(next);
      }}
    />
  );
}

export default function SignInPage() {
  return (
    <Suspense fallback={<div className="h-dvh bg-canvas" />}>
      <SignIn />
    </Suspense>
  );
}
