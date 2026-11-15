// Officer approval + Q&A logic. Transport-agnostic (dry-run / Spectrum cloud / Spectrum local).
import type { Inbound, Transport } from "./transport.js";

export type Hazard = string | { type?: string; location?: string; reason?: string; [k: string]: unknown };

export type NotifyBody = {
  run_id: string;
  address?: string;
  summary?: string;
  top_hazards?: Hazard[];
  plan_id?: string; // if backend distinguishes plan_id from run_id; defaults to run_id
  to?: string | string[]; // override recipients (defaults to OFFICER_PHONE)
};

type Run = NotifyBody & {
  plan_id: string;
  code: string; // short code officers can type: "APPROVE 7f3a"
  notifiedAt: number;
  status: "PENDING_APPROVAL" | "APPROVED" | "REJECTED";
  decidedBy?: string;
};

export type BridgeConfig = {
  backendUrl: string;
  officers: string[]; // E.164 numbers / emails allowed to approve
  dashboardUrl?: string;
  unitName: string;
};

const APPROVE_RE = /^(approve[d]?|yes|y|ok|okay|lgtm|confirm(ed)?|go|send it|ship it)\b/i;
const REJECT_RE = /^(reject(ed)?|no|n|deny|denied|decline[d]?|hold)\b/i;
const APPROVE_EMOJI = ["👍", "❤️", "‼️", "✅", "love", "like"];
const REJECT_EMOJI = ["👎", "dislike"];

export function normalizeAddr(a: string): string {
  if (a.includes("@")) return a.trim().toLowerCase();
  const digits = a.replace(/\D/g, "");
  return digits.length > 10 ? digits.slice(-10) : digits; // compare on last 10 digits (US)
}

/** Whole brief if <= maxWords, else cut at the last sentence boundary within maxWords. Never mid-word. */
export function tidyBrief(text: string | undefined, maxWords = 60): string | undefined {
  if (!text) return undefined;
  let t = text.replace(/\s+/g, " ").trim();
  const words = t.split(" ");
  if (words.length > maxWords) t = words.slice(0, maxWords).join(" ");
  if (!/[.!?]["')]?$/.test(t)) {
    // drop the trailing partial sentence (e.g. a backend-side [:300] cut)
    const m = t.match(/^[\s\S]*[.!?]["')]?(?=\s|$)/);
    if (m) t = m[0];
    else t = t.replace(/[,;:\-\u2014]?\s*\S*$/, "") + "…"; // no sentence end: cut at a word boundary
  }
  return t;
}

function fmtHazard(h: Hazard): string {
  if (typeof h === "string") return h;
  const parts = [h.type, h.location].filter(Boolean);
  return parts.length ? parts.join(" — ") : JSON.stringify(h);
}

/** BACKEND_ACCESS_CODE = the backend's FIRSTIN_ACCESS_CODE (hosted mode). Unset = no header. */
function backendAuthHeader(): Record<string, string> {
  const code = process.env.BACKEND_ACCESS_CODE?.trim();
  return code ? { authorization: `Bearer ${code}` } : {};
}

async function http(method: string, url: string, body?: unknown, timeoutMs = 60_000): Promise<any> {
  const res = await fetch(url, {
    method,
    headers: { ...(body ? { "content-type": "application/json" } : {}), ...backendAuthHeader() },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const txt = await res.text();
  let data: any = txt;
  try {
    data = txt ? JSON.parse(txt) : {};
  } catch {}
  if (!res.ok) throw new Error(`${method} ${url} -> ${res.status} ${typeof data === "string" ? data : JSON.stringify(data)}`);
  return data;
}

export class Bridge {
  runs = new Map<string, Run>();
  /** officer (normalized) -> most recent run_id we messaged them about */
  active = new Map<string, string>();
  /** approval texts that couldn't be delivered (e.g. officer hasn't texted the shared line yet) */
  unsent = new Map<string, string>();

  constructor(
    private cfg: BridgeConfig,
    private transport: Transport,
  ) {}

  isOfficer(from: string) {
    const n = normalizeAddr(from);
    return this.cfg.officers.some((o) => normalizeAddr(o) === n);
  }

  // ------------------------------------------------------------ outbound
  async notify(body: NotifyBody): Promise<{ sent_to: string[]; code: string; errors: string[] }> {
    if (!body?.run_id) throw new Error("run_id required");
    const existing = this.runs.get(body.run_id);
    const run: Run = {
      ...existing,
      ...body,
      plan_id: body.plan_id ?? existing?.plan_id ?? body.run_id,
      code: existing?.code ?? body.run_id.replace(/[^a-zA-Z0-9]/g, "").slice(-4).toLowerCase(),
      notifiedAt: Date.now(),
      status: "PENDING_APPROVAL",
    };
    // Prefer the full voice brief from the plan (backend body.summary may be hard-cut at 300 chars)
    try {
      const plan = await http("GET", `${this.cfg.backendUrl}/plan/${encodeURIComponent(run.run_id)}`, undefined, 3_000);
      const p = plan?.plan ?? plan;
      if (p?.voice_brief) run.summary = p.voice_brief;
      if (!run.address && p?.building?.address) run.address = p.building.address;
    } catch {}
    run.summary = tidyBrief(run.summary);
    this.runs.set(run.run_id, run);

    const to = body.to ? ([] as string[]).concat(body.to) : this.cfg.officers;
    const hazards = (run.top_hazards ?? []).slice(0, 3).map((h, i) => `${i + 1}. ${fmtHazard(h)}`);
    const lines = [
      `FirstIn pre-plan ready for approval`,
      run.address ? `${run.address}` : undefined,
      run.summary ? `\n${run.summary}` : undefined,
      hazards.length ? `\nTop hazards:\n${hazards.join("\n")}` : undefined,
      this.cfg.dashboardUrl ? `\nReview: ${this.cfg.dashboardUrl.replace(/\/$/, "")}/plan/${encodeURIComponent(run.run_id)}` : undefined,
      `\nReply APPROVE, REJECT, or ask a question (e.g. "where's the standpipe?"). [ref ${run.code}]`,
    ].filter(Boolean);
    const msg = lines.join("\n");

    const sent: string[] = [];
    const errors: string[] = [];
    for (const addr of to) {
      this.active.set(normalizeAddr(addr), run.run_id); // map even on failure so a later "hi" -> resend works
      try {
        await this.transport.send(addr, msg);
        sent.push(addr);
      } catch (e) {
        errors.push(`${addr}: ${(e as Error).message}`);
        console.error(`[bridge] send to ${addr} failed: ${(e as Error).message}`);
      }
    }
    if (!sent.length) this.unsent.set(run.run_id, msg);
    console.log(`[bridge] notified run ${run.run_id} -> ${sent.join(", ") || "(nobody)"}`);
    return { sent_to: sent, code: run.code, errors };
  }

  // ------------------------------------------------------------ inbound
  pending(): Run[] {
    return [...this.runs.values()].filter((r) => r.status === "PENDING_APPROVAL").sort((a, b) => b.notifiedAt - a.notifiedAt);
  }

  private resolveRun(from: string, text: string, forDecision = false): Run | undefined {
    // explicit short code or full run id anywhere in the text wins ("APPROVE 7805")
    const tokens = text.toLowerCase().split(/[^a-z0-9_-]+/).filter(Boolean);
    for (const r of this.runs.values()) {
      if (tokens.includes(r.code) || tokens.includes(r.run_id.toLowerCase())) return r;
    }
    // APPROVE/REJECT without a ref -> the most recent pending plan
    if (forDecision) {
      const p = this.pending()[0];
      if (p) return p;
    }
    const id = this.active.get(normalizeAddr(from));
    if (id && this.runs.get(id)) return this.runs.get(id);
    return this.pending()[0];
  }

  /** Reload pending runs from the backend (survives bridge restarts; drops runs the backend no longer has). */
  async syncFromBackend(): Promise<void> {
    let list: any[];
    try {
      list = await http("GET", `${this.cfg.backendUrl}/runs`, undefined, 5_000);
      if (!Array.isArray(list)) return;
    } catch {
      return;
    }
    const known = new Set(list.map((r) => r.run_id));
    for (const r of this.runs.values()) {
      if (r.status === "PENDING_APPROVAL" && !known.has(r.run_id)) {
        console.log(`[bridge] run ${r.run_id} no longer on backend; dropping`);
        this.runs.delete(r.run_id);
      }
    }
    for (const b of list) {
      const existing = this.runs.get(b.run_id);
      if (existing) {
        if (b.status === "APPROVED" || b.status === "REJECTED") existing.status = b.status;
        continue;
      }
      if (b.status !== "PENDING_APPROVAL") continue;
      let address: string | undefined, summary: string | undefined, top_hazards: Hazard[] | undefined;
      try {
        const plan = await http("GET", `${this.cfg.backendUrl}/plan/${encodeURIComponent(b.run_id)}`, undefined, 5_000);
        const p = plan?.plan ?? plan;
        address = p?.building?.address;
        summary = tidyBrief(p?.voice_brief);
        top_hazards = (p?.hazards ?? []).slice(0, 3);
      } catch {}
      this.runs.set(b.run_id, {
        run_id: b.run_id, plan_id: b.run_id, address, summary, top_hazards,
        code: b.run_id.replace(/[^a-zA-Z0-9]/g, "").slice(-4).toLowerCase(),
        notifiedAt: (b.created_at ?? Date.now() / 1000) * 1000,
        status: "PENDING_APPROVAL",
      });
      console.log(`[bridge] reloaded pending run ${b.run_id} (${address ?? "?"}) from backend`);
    }
  }


  async handle(msg: Inbound): Promise<void> {
    const text = msg.text.trim();
    console.log(`[bridge] <- ${msg.from}: ${msg.reaction ? `(reaction ${msg.reaction})` : text}`);

    let intent: "approve" | "reject" | "help" | "status" | "ask" | "ignore" = "ask";
    if (msg.reaction) {
      intent = APPROVE_EMOJI.includes(msg.reaction) ? "approve" : REJECT_EMOJI.includes(msg.reaction) ? "reject" : "ignore";
    } else if (!text) intent = "ignore";
    else if (APPROVE_RE.test(text)) intent = "approve";
    else if (REJECT_RE.test(text)) intent = "reject";
    else if (/^(help|\?)$/i.test(text)) intent = "help";
    else if (/^(status|details|plan)\b/i.test(text)) intent = "status";
    if (intent === "ignore") return;

    // Photon Beta shared lines can't text first: if an approval request couldn't be delivered earlier,
    // deliver it now that the officer has opened the conversation.
    if (this.isOfficer(msg.from) && this.unsent.size) {
      for (const [runId, pending] of this.unsent) {
        if (this.runs.get(runId)?.status === "PENDING_APPROVAL") await msg.reply(pending);
      }
      this.unsent.clear();
      if (!APPROVE_RE.test(text) && !REJECT_RE.test(text)) return;
    }

    if (intent === "help") {
      await msg.reply(
        `FirstIn commands:\nAPPROVE [ref] - publish the pre-plan to the in-cab unit\nREJECT [ref] - send it back\nSTATUS - current plan details\nAnything else is answered from the plan (e.g. "where's the standpipe?").`,
      );
      return;
    }

    if (intent === "approve" || intent === "reject" || !this.runs.size) await this.syncFromBackend();
    const run = this.resolveRun(msg.from, text, intent === "approve" || intent === "reject");

    if (intent === "approve" || intent === "reject") {
      if (!this.isOfficer(msg.from)) {
        await msg.reply("Sorry, only the assigned officer can approve or reject pre-plans.");
        return;
      }
      if (!run) {
        await msg.reply("No pre-plan is waiting for approval right now.");
        return;
      }
      if (run.status !== "PENDING_APPROVAL") {
        await msg.reply(`That pre-plan (${run.address ?? run.run_id}) was already ${run.status.toLowerCase()} by ${run.decidedBy ?? "someone"}.`);
        return;
      }
      await msg.responding(async () => {
        try {
          await http("POST", `${this.cfg.backendUrl}/approve/${encodeURIComponent(run.run_id)}`, {
            approved_by: msg.from,
            decision: intent,
          });
          run.status = intent === "approve" ? "APPROVED" : "REJECTED";
          run.decidedBy = msg.from;
          const others = this.pending().filter((r) => r.run_id !== run.run_id);
          const tail = others.length
            ? `\nStill pending: ${others.map((r) => `${r.address ?? r.run_id} (ref ${r.code})`).join("; ")}`
            : "";
          if (intent === "approve") {
            await msg.reply(`Approved ${run.address ?? run.run_id} (ref ${run.code}). Publishing to ${this.cfg.unitName}...${tail}`);
            void this.confirmInCab(run, msg);
          } else {
            await msg.reply(`Rejected ${run.address ?? run.run_id} (ref ${run.code}). It will not be published; edit it on the dashboard and re-run.${tail}`);
          }
        } catch (e) {
          console.error("[bridge] approve failed", e);
          if (/-> 404/.test((e as Error).message)) {
            this.runs.delete(run.run_id);
            const next = this.pending()[0];
            await msg.reply(`That plan (${run.address ?? run.run_id}, ref ${run.code}) no longer exists on the server.` +
              (next ? ` Latest pending: ${next.address ?? next.run_id} (ref ${next.code}). Reply APPROVE ${next.code}.` : ""));
            return;
          }
          await msg.reply(`Couldn't reach FirstIn to record that (${(e as Error).message.slice(0, 120)}). Try again or use the dashboard.`);
        }
      });
      return;
    }

    if (intent === "status") {
      if (!run) return void (await msg.reply("No active pre-plan."));
      await msg.responding(async () => {
        try {
          const plan = await http("GET", `${this.cfg.backendUrl}/plan/${encodeURIComponent(run.run_id)}`, undefined, 15_000);
          await msg.reply(summarizePlan(plan, run));
        } catch (e) {
          await msg.reply(`Status: ${run.status}. (Couldn't load plan details: ${(e as Error).message.slice(0, 100)})`);
        }
      });
      return;
    }

    // ---- free-text question -> /ask
    if (!run) {
      await msg.reply("FirstIn is connected. Pre-plan approval requests will arrive here. Reply HELP for commands.");
      return;
    }
    await msg.responding(async () => {
      try {
        const res = await http("POST", `${this.cfg.backendUrl}/ask`, { plan_id: run.plan_id, question: text });
        const answer = typeof res === "string" ? res : res?.answer ?? JSON.stringify(res);
        const tail = run.status === "PENDING_APPROVAL" ? `\n\n(Plan still pending. Reply APPROVE or REJECT.)` : "";
        await msg.reply(`${answer}${tail}`);
      } catch (e) {
        console.error("[bridge] ask failed", e);
        await msg.reply(`Couldn't get an answer from the plan right now. VERIFY ON SITE.`);
      }
    });
  }

  /** After approval, poll /incab/active briefly so the officer knows the rig actually has it. */
  private async confirmInCab(run: Run, msg: Inbound) {
    const deadline = Date.now() + 20_000;
    while (Date.now() < deadline) {
      try {
        const a = await http("GET", `${this.cfg.backendUrl}/incab/active`, undefined, 5_000);
        if (a && (a.plan_id === run.plan_id || a.plan_id === run.run_id || (run.address && a.address === run.address))) {
          await msg.reply(`Live on ${this.cfg.unitName} in-cab unit. Crew can press BRIEF ME.`);
          return;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 2000));
    }
    console.warn(`[bridge] run ${run.run_id} approved but not seen on /incab/active within 20s`);
  }
}

function v(x: any): string | undefined {
  if (x == null) return undefined;
  if (typeof x === "object" && "value" in x) return x.value == null ? undefined : String(x.value);
  if (typeof x === "object") return undefined;
  return String(x);
}

export function summarizePlan(plan: any, run: { status: string; address?: string }): string {
  const p = plan?.plan ?? plan ?? {};
  const b = p.building ?? {};
  const lines = [
    `${b.address ?? run.address ?? "Pre-plan"} — ${plan?.status ?? p.status ?? run.status}`,
    [v(b.stories) && `${v(b.stories)} stories`, v(b.year_built) && `built ${v(b.year_built)}`, v(b.construction)].filter(Boolean).join(", "),
  ];
  const hz = (p.hazards ?? []).slice(0, 3).map((h: any) => `- ${fmtHazard(h)}`);
  if (hz.length) lines.push(`Hazards:\n${hz.join("\n")}`);
  const stairs = (p.interior?.stairwells ?? []).map((s: any) => `${s.loc}${s.standpipe ? " (standpipe)" : ""}`);
  if (stairs.length) lines.push(`Stairs: ${stairs.join(", ")}`);
  const roof = v(p.access?.roof_access);
  if (roof) lines.push(`Roof: ${roof}`);
  return lines.filter(Boolean).join("\n");
}
