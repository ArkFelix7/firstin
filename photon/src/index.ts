// FirstIn Photon bridge: iMessage approval + Q&A for pre-plans.
//
//   npx tsx src/index.ts            # PHOTON_MODE from env (cloud | local)
//   npx tsx src/index.ts --dry-run  # console simulation, no credentials needed
//
// HTTP (default :8010):
//   POST /notify   {run_id, address, summary, top_hazards, plan_id?, to?}  <- backend calls on approval interrupt
//   POST /simulate {from?, text}                                          <- fake an inbound iMessage (testing)
//   GET  /health, GET /runs
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { config as loadEnv } from "dotenv";
import { Bridge } from "./bridge.js";
import { DryRunTransport, PhotonV2Transport, SpectrumTransport, type Transport } from "./transport.js";

const here = dirname(fileURLToPath(import.meta.url));
loadEnv({ path: resolve(here, "../.env"), quiet: true } as any);
loadEnv({ path: resolve(here, "../../.env"), quiet: true } as any); // repo root fallback; never printed

// v2 (Photon Beta) names first; legacy SPECTRUM_* names still read.
const projectId = process.env.PHOTON_PROJECT_ID || process.env.SPECTRUM_PROJECT_ID || "";
const apiKey = process.env.PHOTON_API_KEY || process.env.SPECTRUM_PROJECT_SECRET || "";
const dryRun = process.argv.includes("--dry-run") || process.env.PHOTON_MODE === "dry-run";
// pho_prj_ ids belong to the Photon 2.0 Beta platform -> default to v2
const mode = (process.env.PHOTON_MODE || (projectId.startsWith("pho_prj_") ? "v2" : "cloud")) as "v2" | "cloud" | "local" | "dry-run";
const officers = (process.env.OFFICER_PHONE ?? "+15555550123").split(",").map((s) => s.trim()).filter(Boolean);
const port = Number(process.env.PHOTON_PORT ?? 8010);

const transport: Transport = dryRun
  ? new DryRunTransport(officers[0])
  : mode === "v2" || (mode === "cloud" && projectId.startsWith("pho_prj_"))
    ? new PhotonV2Transport({ projectId, apiKey, origin: process.env.PHOTON_API_ORIGIN })
    : new SpectrumTransport(mode === "local" ? "local" : "cloud", { projectId, projectSecret: apiKey });

const bridge = new Bridge(
  {
    backendUrl: (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, ""),
    officers,
    dashboardUrl: process.env.DASHBOARD_URL || undefined,
    unitName: process.env.UNIT_NAME ?? "Engine 12",
  },
  transport,
);

function readJson(req: IncomingMessage): Promise<any> {
  return new Promise((ok, fail) => {
    let s = "";
    req.on("data", (c) => (s += c));
    req.on("end", () => {
      try {
        ok(s ? JSON.parse(s) : {});
      } catch (e) {
        fail(e);
      }
    });
    req.on("error", fail);
  });
}

function send(res: ServerResponse, code: number, body: unknown) {
  res.writeHead(code, { "content-type": "application/json", "access-control-allow-origin": "*" });
  res.end(JSON.stringify(body));
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", "http://x");
    if (req.method === "OPTIONS") {
      res.writeHead(204, { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type", "access-control-allow-methods": "GET,POST" });
      return res.end();
    }
    if (req.method === "GET" && url.pathname === "/health") return send(res, 200, { ok: true, transport: transport.name, officers: officers.length });
    if (req.method === "GET" && url.pathname === "/runs") return send(res, 200, [...bridge.runs.values()]);
    if (req.method === "POST" && url.pathname === "/notify") {
      const body = await readJson(req);
      if (!body.run_id) return send(res, 400, { error: "run_id required" });
      const out = await bridge.notify(body);
      return send(res, 200, { ok: true, ...out });
    }
    if (req.method === "POST" && url.pathname === "/simulate") {
      const body = await readJson(req);
      const from = body.from ?? officers[0];
      const replies: string[] = [];
      await bridge.handle({
        from,
        text: body.text ?? "",
        reaction: body.reaction,
        reply: async (t) => {
          replies.push(t);
          await transport.send(from, t).catch(() => {});
        },
        responding: (fn) => fn(),
      });
      return send(res, 200, { ok: true, replies });
    }
    send(res, 404, { error: "not found" });
  } catch (e) {
    console.error("[http]", e);
    send(res, 500, { error: (e as Error).message });
  }
});

try {
  await transport.start((m) => bridge.handle(m));
} catch (e) {
  console.error(`[photon] could not start ${transport.name}: ${(e as Error).message}`);
  console.error(`[photon] tip: run 'npm run dry-run' to test without Photon credentials.`);
  process.exit(1);
}
await bridge.syncFromBackend(); // restore pending runs after a restart
setInterval(() => void bridge.syncFromBackend(), 30_000).unref();
// PHOTON_HOST=127.0.0.1 on the server keeps the bridge private (only the backend calls it). Unset = all interfaces.
const host = process.env.PHOTON_HOST || undefined;
server.listen(port, host, () => {
  console.log(`[photon] FirstIn bridge on http://${host ?? "localhost"}:${port} (transport=${transport.name}, backend=${process.env.BACKEND_URL ?? "http://localhost:8000"})`);
});

const shutdown = async () => {
  server.close();
  await transport.stop().catch(() => {});
  process.exit(0);
};
process.once("SIGINT", shutdown);
process.once("SIGTERM", shutdown);
