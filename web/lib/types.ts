// Shapes from CONTRACTS.md / README §7. Kept deliberately permissive: the
// backend is being built concurrently, so every consumer normalizes input.

export type SourceKey = "costar" | "vexcel" | "matterport" | "inference" | "officer";

export interface Cite {
  src: SourceKey | string;
  id?: string | null;
  // README §7 examples use these aliases instead of `id`
  tile?: string;
  sweep?: string;
  record_id?: string;
  model?: string;
  model_id?: string;
  conf?: number;
  bbox?: [number, number, number, number] | null;
  url?: string | null;
  from?: string[] | null;
  [k: string]: unknown;
}

export interface Field<T = unknown> {
  value: T;
  cite: Cite | null;
}

export interface Building {
  building_id: string;
  address: string;
  city: string;
  lat: number;
  lng: number;
  costar_id?: string | null;
  matterport_model_ids?: string[];
  has?: { costar?: boolean; vexcel?: boolean; matterport?: boolean };
  name?: string;
  /** Prepared demo building (agent cache warm, ~30 s run). */
  featured?: boolean;
  /** Agent inputs cached locally; uncached runs fetch live (~50 s). */
  cached?: boolean;
  property_type?: string | null;
  stories?: number | null;
  year_built?: number | null;
  rba_sqft?: number | null;
}

export type PlanStatus = "DRAFT" | "PENDING_APPROVAL" | "APPROVED" | "REJECTED";

// Plan is intentionally loose: sections are optional while streaming in.
export interface Plan {
  plan_id?: string;
  building?: Record<string, unknown> & { address?: string; costar_id?: string };
  occupancy?: Record<string, unknown>;
  access?: Record<string, unknown>;
  interior?: Record<string, unknown>;
  fire_protection?: Record<string, unknown>;
  hazards?: Array<Record<string, unknown>>;
  exposures?: Array<Record<string, unknown>>;
  voice_brief?: string;
  status?: PlanStatus | string;
  approved_by?: string | null;
  [k: string]: unknown;
}

export type EventType =
  | "todo"
  | "subagent_start"
  | "subagent_end"
  | "tool_call"
  | "tool_result"
  | "evidence"
  | "plan"
  | "interrupt"
  | "published"
  | "log"
  | "error"
  | "done";

export interface AgentEvent {
  type: EventType | string;
  ts?: number | string;
  payload?: Record<string, unknown>;
}

export interface IncabSummary {
  plan_id: string;
  address: string;
  stories?: number | string | null;
  year_built?: number | string | null;
  construction?: string | null;
  top_hazards?: Array<string | { type?: string; location?: string; [k: string]: unknown }>;
  /** Structured hazards (newer backends): preferred over top_hazards strings. */
  top_hazards_detail?: Array<{ type?: string; location?: string | null; conf?: number | null }>;
  roof_access_short?: string | null;
  construction_detail?: string | null;
  approved_by?: string | null;
  stairs?: string | string[] | null;
  roof_access?: string | null;
  voice_brief?: string | null;
  audio_url?: string | null;
  approved_at?: string | number | null;
}

export interface ApproveBody {
  approved_by: string;
  decision: "approve" | "reject";
  edits?: Record<string, unknown>;
}
