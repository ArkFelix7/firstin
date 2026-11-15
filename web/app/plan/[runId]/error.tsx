"use client";

import { Button } from "@/components/ui";

export default function PlanError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex h-dvh flex-col items-center justify-center gap-3 bg-canvas text-center">
      <h1 className="text-lg font-semibold text-fg">This plan could not be displayed</h1>
      <p className="max-w-[560px] text-sm text-fg-2">{error.message}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
