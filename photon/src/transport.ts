// Messaging transports for the FirstIn iMessage bridge.
//
//  - SpectrumTransport: real iMessage via Photon's spectrum-ts.
//      cloud -> Spectrum Cloud (Photon 2.0 beta project id/secret)   [qualifies for Photon track]
//      local -> @spectrum-ts/imessage-local (this Mac's Messages.app; optional install)
//  - DryRunTransport: console only. Outbound printed, inbound typed on stdin.
//
// API used (verified against spectrum-ts 12.16 source/docs):
//   const app = await Spectrum({ projectId, projectSecret, providers: [imessage.config()] })
//   for await (const [space, message] of app.messages) { message.direction, message.sender?.id, message.content.type/text }
//   const im = imessage(app); const user = await im.user("+1555..."); const dm = await im.space.create(user); await dm.send("...")
//   await space.responding(async () => { ... })   // typing indicator while we work

import * as readline from "node:readline";

export type Inbound = {
  from: string; // sender id (phone/email) — becomes approved_by
  text: string; // normalized text ("" for non-text)
  reaction?: string; // emoji if this was a tapback/reaction
  reply: (text: string) => Promise<void>;
  /** run work with a typing indicator, if the platform supports it */
  responding: <T>(fn: () => Promise<T>) => Promise<T>;
};

export interface Transport {
  name: string;
  start(onInbound: (msg: Inbound) => Promise<void>): Promise<void>;
  send(to: string, text: string): Promise<void>;
  stop(): Promise<void>;
}

// ---------------------------------------------------------------- dry run
export class DryRunTransport implements Transport {
  name = "dry-run";
  private rl?: readline.Interface;
  constructor(private defaultFrom: string) {}

  async send(to: string, text: string) {
    console.log(`\n\x1b[36m[iMessage -> ${to}]\x1b[0m\n${text}\n`);
  }

  async start(onInbound: (msg: Inbound) => Promise<void>) {
    console.log(
      `[dry-run] Type a reply as the officer (${this.defaultFrom}) and press Enter.\n` +
        `          Prefix with "from:+1999 " to impersonate another sender. "react:👍" simulates a tapback.`,
    );
    this.rl = readline.createInterface({ input: process.stdin });
    this.rl.on("line", (line) => {
      let from = this.defaultFrom;
      let text = line.trim();
      const m = /^from:(\S+)\s+(.*)$/.exec(text);
      if (m) {
        from = m[1];
        text = m[2];
      }
      if (!text) return;
      let reaction: string | undefined;
      const r = /^react:(.+)$/.exec(text);
      if (r) {
        reaction = r[1].trim();
        text = "";
      }
      const reply = (t: string) => this.send(from, t);
      onInbound({ from, text, reaction, reply, responding: (fn) => fn() }).catch((e) =>
        console.error("[dry-run] handler error", e),
      );
    });
  }

  async stop() {
    this.rl?.close();
  }
}

// ---------------------------------------------------------------- spectrum
type AnyApp = any; // spectrum-ts generics are deep; keep the bridge loosely typed

export class SpectrumTransport implements Transport {
  name: string;
  private app?: AnyApp;
  private narrow?: (app: AnyApp) => any;
  private spaces = new Map<string, any>(); // phone -> Space (DM)

  constructor(
    private mode: "cloud" | "local",
    private opts: { projectId?: string; projectSecret?: string },
  ) {
    this.name = `spectrum-${mode}`;
  }

  private async init() {
    const { Spectrum } = await import("spectrum-ts");
    if (this.mode === "cloud") {
      if (!this.opts.projectId || !this.opts.projectSecret) {
        throw new Error(
          "PHOTON_MODE=cloud needs SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET (see photon/README.md), or run with --dry-run",
        );
      }
      const { imessage } = await import("spectrum-ts/providers/imessage");
      this.app = await Spectrum({
        projectId: this.opts.projectId,
        projectSecret: this.opts.projectSecret,
        providers: [imessage.config()],
        signal: AbortSignal.timeout(20_000),
      } as any);
      this.narrow = imessage as any;
    } else {
      // Optional dependency: npm i @spectrum-ts/imessage-local  (macOS, Full Disk Access)
      const modName = "@spectrum-ts/imessage-local";
      const { localIMessage } = (await import(modName)) as any;
      this.app = await Spectrum({ providers: [localIMessage.config()] } as any);
      this.narrow = localIMessage;
    }
  }

  private async dm(to: string) {
    let space = this.spaces.get(to);
    if (!space) {
      const im = this.narrow!(this.app);
      const user = await im.user(to);
      space = await im.space.create(user);
      this.spaces.set(to, space);
    }
    return space;
  }

  async send(to: string, text: string) {
    const space = await this.dm(to);
    await space.send(text);
  }

  async start(onInbound: (msg: Inbound) => Promise<void>) {
    await this.init();
    console.log(`[${this.name}] connected; listening for iMessages`);
    (async () => {
      for await (const [space, message] of this.app.messages) {
        try {
          if (message.direction === "outbound") continue;
          const from: string = message.sender?.id ?? "unknown";
          const c = message.content;
          let text = "";
          let reaction: string | undefined;
          if (c.type === "text") text = c.text;
          else if (c.type === "reply" && c.content?.type === "text") text = c.content.text;
          else if (c.type === "reaction") reaction = c.emoji;
          else continue; // ignore typing/read receipts/attachments etc.
          // remember the DM so outbound for this sender reuses it
          if (!this.spaces.has(from)) this.spaces.set(from, space);
          const reply = async (t: string) => {
            await space.send(t);
          };
          const responding = async <T>(fn: () => Promise<T>): Promise<T> => {
            let out!: T;
            if (typeof space.responding === "function") {
              await space.responding(async () => {
                out = await fn();
              });
              return out;
            }
            return fn();
          };
          // don't block the stream on backend latency
          onInbound({ from, text, reaction, reply, responding }).catch((e) =>
            console.error(`[${this.name}] handler error`, e),
          );
        } catch (e) {
          console.error(`[${this.name}] bad message`, e);
        }
      }
    })().catch((e) => console.error(`[${this.name}] message stream ended`, e));
  }

  async stop() {
    await this.app?.stop?.();
  }
}

// ---------------------------------------------------------------- Photon 2.0 beta (v2)
// Photon Beta (app.beta.photon.codes, ids pho_prj_ / keys pho_sk_). Per docs.photon.codes/docs/beta:
//   send:    POST https://api.photon.codes/v1/projects/{id}/messages   (Idempotency-Key header)
//            body {spaceId, senderId (agent user id), parentMessageId?, content:{type:"text",format:"plain",text}}
//   read:    GET  /v1/projects/{id}/messages?direction=received&platform=imessage&order=desc
//   inbound: Socket.IO at path /v1/projects/{id}/events/ws, emit "subscribe" {startSeq}, receive
//            "delivery" (event, {seq}) with event.type === "message.received", event.data.object = Message
// Shared iMessage lines cannot message first: the officer's handle needs an active assignment and must have
// texted the assigned line since that assignment. Beta iMessage = text + images only (no tapbacks).
type V2Conv = { spaceId: string; agentId: string; lastInboundId?: string };

export class PhotonV2Transport implements Transport {
  name = "photon-v2";
  private convs = new Map<string, V2Conv>(); // normalized officer handle -> conversation
  private socket?: any;
  private cursor = 0;
  private seen = new Set<string>();
  private origin: string;

  constructor(private opts: { projectId: string; apiKey: string; origin?: string }) {
    this.origin = (opts.origin ?? "https://api.photon.codes").replace(/\/$/, "");
  }

  private key(h: string) {
    return h.includes("@") ? h.trim().toLowerCase() : h.replace(/\D/g, "").slice(-10);
  }

  async api(method: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
    const res = await fetch(`${this.origin}/v1/projects/${this.opts.projectId}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.opts.apiKey}`,
        ...(body ? { "content-type": "application/json" } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(15_000),
    });
    const txt = await res.text();
    let data: any = txt;
    try {
      data = txt ? JSON.parse(txt) : {};
    } catch {}
    if (!res.ok) {
      const code = data?.code ?? "";
      const detail = data?.detail ?? data?.title ?? txt.slice(0, 200);
      const err: any = new Error(`Photon ${method} ${path.split("?")[0]} -> ${res.status} ${code} ${detail} (request ${res.headers.get("x-request-id") ?? "?"})`);
      err.status = res.status;
      err.problem = data;
      throw err;
    }
    return data;
  }

  /** Find the DM space + agent user id for a human handle from message history. */
  private async lookup(to: string): Promise<V2Conv | undefined> {
    const k = this.key(to);
    const cached = this.convs.get(k);
    if (cached) return cached;
    const page = await this.api("GET", `/messages?direction=received&platform=imessage&order=desc&pageSize=100`);
    for (const m of page.items ?? []) {
      if (m?.sentBy?.handle && this.key(m.sentBy.handle) === k && m.space?.id && m.receivedBy?.id) {
        const c = { spaceId: m.space.id, agentId: m.receivedBy.id, lastInboundId: m.id };
        this.convs.set(k, c);
        return c;
      }
    }
    return undefined;
  }

  async send(to: string, text: string) {
    const conv = await this.lookup(to);
    if (!conv) {
      throw new Error(
        `No iMessage conversation with ${to} yet. Photon Beta shared lines can't text first: ` +
          `${to} must have a shared-line assignment and send any message to the assigned Photon number first.`,
      );
    }
    const res = await this.api(
      "POST",
      `/messages`,
      { spaceId: conv.spaceId, senderId: conv.agentId, content: { type: "text", format: "plain", text } },
      { "idempotency-key": `firstin-${Date.now()}-${Math.random().toString(36).slice(2, 10)}` },
    );
    console.log(`[photon-v2] -> ${to}: accepted message ${res?.id ?? "?"} status=${res?.status ?? "?"}`);
  }

  private async typing(conv: V2Conv, on: boolean) {
    try {
      await this.api("POST", `/spaces/${conv.spaceId}/typing`, { senderId: conv.agentId, typing: on });
    } catch {}
  }

  private handleMessage(m: any, onInbound: (msg: Inbound) => Promise<void>) {
    if (!m || m.platform !== "imessage" || m.status !== "received") return;
    if (m.sentBy?.kind && m.sentBy.kind !== "human") return;
    if (this.seen.has(m.id)) return;
    this.seen.add(m.id);
    const from: string = m.sentBy?.handle ?? m.sentBy?.id ?? "unknown";
    const conv: V2Conv = { spaceId: m.space?.id, agentId: m.receivedBy?.id, lastInboundId: m.id };
    if (conv.spaceId && conv.agentId) this.convs.set(this.key(from), conv);
    const c = m.content ?? {};
    let text = "";
    if (c.type === "text") text = c.text ?? "";
    else if (c.type === "group") text = (c.parts ?? []).filter((p: any) => p.type === "text").map((p: any) => p.text).join("\n");
    else {
      console.log(`[photon-v2] <- ${from}: (${c.type}) ignored`);
      return;
    }
    const reply = async (t: string) => {
      await this.api(
        "POST",
        `/messages`,
        // no parentMessageId: threaded replies came back message.failed on the Beta shared line
        { spaceId: conv.spaceId, senderId: conv.agentId, content: { type: "text", format: "plain", text: t } },
        { "idempotency-key": `firstin-reply-${m.id}-${Buffer.from(t).toString("base64url").slice(0, 24)}-${t.length}` },
      );
    };
    const responding = async <T>(fn: () => Promise<T>): Promise<T> => {
      await this.typing(conv, true);
      try {
        return await fn();
      } finally {
        void this.typing(conv, false);
      }
    };
    onInbound({ from, text, reply, responding }).catch((e) => console.error("[photon-v2] handler error", e));
  }

  async start(onInbound: (msg: Inbound) => Promise<void>) {
    // fail fast on bad credentials
    const plat = await this.api("GET", `/platforms/imessage`);
    const asg = await this.api("GET", `/platforms/imessage/assignments`).catch(() => ({ assignments: [] }));
    console.log(
      `[photon-v2] project ok; imessage mode=${plat?.mode} assignments=` +
        (asg.assignments ?? []).map((a: any) => `${a.handle}->${a.assignedPhoneNumber}`).join(", "),
    );
    const { io } = await import("socket.io-client");
    const socket = io(this.origin, {
      path: `/v1/projects/${this.opts.projectId}/events/ws`,
      addTrailingSlash: false,
      transports: ["websocket"],
      extraHeaders: { Authorization: `Bearer ${this.opts.apiKey}` },
      autoConnect: false,
    });
    this.socket = socket;
    socket.on("connect", () => {
      socket.timeout(10_000).emit("subscribe", { startSeq: this.cursor }, (err: any, result: any) => {
        if (err) {
          console.error("[photon-v2] subscribe timed out; reconnecting");
          socket.io.engine.close();
        } else if (result && result.ok === false) console.error("[photon-v2] subscribe failed", result.error?.code);
        else console.log(`[photon-v2] socket subscribed (startSeq=${this.cursor})`);
      });
    });
    socket.on("delivery", (event: any, meta: { seq: number }) => {
      if (meta?.seq && meta.seq <= this.cursor) return;
      if (meta?.seq) this.cursor = meta.seq;
      console.log(`[photon-v2] event ${event?.type} seq=${meta?.seq}`);
      if (event?.type === "message.received") this.handleMessage(event.data?.object, onInbound);
      else if (event?.type === "message.failed") console.error("[photon-v2] send failed:", JSON.stringify(event.data?.object?.failure ?? event.data).slice(0, 300));
    });
    socket.on("delivery_error", (e: any) => console.error("[photon-v2] delivery_error", e?.code, e?.message));
    socket.on("connect_error", (e: any) => console.error("[photon-v2] connect_error", e?.message));
    socket.on("disconnect", (r: string) => console.warn("[photon-v2] socket disconnected:", r));
    socket.connect();
  }

  async stop() {
    this.socket?.close();
  }
}
