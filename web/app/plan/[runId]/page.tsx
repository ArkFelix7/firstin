import { Suspense } from "react";
import { PlanClient } from "./PlanClient";

export default function PlanPage() {
  return (
    <Suspense fallback={<div className="h-dvh bg-canvas" />}>
      <PlanClient />
    </Suspense>
  );
}
