#!/usr/bin/env node
// FirstIn product walkthrough for screen recording (SCRIPT.md beats 0:42 to 1:32).
//
//   node demo/record/walkthrough.mjs [--step | --auto] [options]
//
// Modes
//   --step            (default) press Enter in this terminal to advance each beat
//   --auto            beats fire on SCRIPT.md timing, with a countdown per beat
//
// Run source
//   --prewarm         (default) POST a fresh la-002 run `--lead` seconds before the
//                     Generate click; the click in the UI is routed to that run, so the
//                     trace is partly replayed and the rest animates live
//   --lead 20         seconds of head start for the prewarmed run (default 20)
//   --live            no prewarm: the Generate click starts a real run (~30 s)
//   --run <run_id>    reuse an existing run (replays instantly; must still be awaiting
//                     approval unless you skip the approve beat)
//
// Approval
//   (default)         click "Approve and publish" in the UI
//   --imessage        wait for the officer to reply APPROVE from the phone (polls run status)
//
// Window
//   --size auto       (default) 1920x1080 if the screen fits it, else 1440x810 (16:9)
//   --size 1440x900   any WxH viewport; the window is sized so the page is exactly WxH
//   --fullscreen      macOS full screen, no title bar (viewport = screen)
//
// Other
//   --shots <dir>     save a screenshot at the end of each beat (for dry runs)
//   --close           close the browser at the end instead of waiting for Enter
//   --base / --api    web and API origins (defaults :3000 / :8000)
//   --building la-002
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import readline from "node:readline";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(HERE, "../../web");
const require = createRequire(path.join(WEB, "package.json"));
const { chromium } = require("playwright-core");

/* ------------------------------------------------------------------ args */
const argv = process.argv.slice(2);
const flag = (n) => argv.includes(`--${n}`);
const opt = (n, d) => {
  const i = argv.indexOf(`--${n}`);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : d;
};
const AUTO = flag("auto");
const LIVE = flag("live");
const IMESSAGE = flag("imessage");
const REUSE = opt("run", null);
const LEAD = Number(opt("lead", 20));
const BASE = opt("base", "http://localhost:3000").replace(/\/$/, "");
const API = opt("api", "http://localhost:8000").replace(/\/$/, "");
const BID = opt("building", "la-002");
const SIZE = opt("size", "auto");
const FULLSCREEN = flag("fullscreen");
const SHOTS = opt("shots", null) ? path.resolve(opt("shots")) : null;
const CLOSE = flag("close");
const STREET = { "la-002": "1601 Perrino Pl", "la-001": "337 S Broadway", "la-003": "10940 Wilshire Blvd" }[BID] ?? BID;
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

/* ------------------------------------------------------------------ beats (SCRIPT.md) */
const BEATS = [
  { id: "map", t: 42, shot: "Map, 1601 Perrino Pl selected, click Generate pre-plan",
    say: "The facts are already out there, in data nobody hands to the fire service. Here's a warehouse in east LA." },
  { id: "trace", t: 48, shot: "Plan page: steps checking off, analysts in parallel",
    say: "Our agent sends three analysts out at once." },
  { id: "building", t: 52, shot: "Building section: 1969, concrete tilt-up, 70,565 SF, CoStar tags",
    say: "CoStar knows what's inside. A 1969 concrete tilt-up, a health-and-beauty wholesaler, eleven dock doors." },
  { id: "stair", t: 60, shot: "Click Stairwell: Matterport 360, box on the steel stair",
    say: "The Matterport scan shows a steel mezzanine stair and pallets stacked on the floor." },
  { id: "roof", t: 66, shot: "Click Roof access: access plan, ladder walls, staging, numbered doors",
    say: "Vexcel shows solar across the roof, the walls a ladder truck can actually reach, and where to park it." },
  { id: "verify", t: 72, shot: "Height: Verified across 2 sources, then the Verify on site checklist",
    say: "Every line cites its source. Two sources agree on the height. Hydrants it can't see, so it says verify on site instead of guessing." },
  { id: "approve", t: 78, shot: IMESSAGE ? "Phone: reply APPROVE to FirstIn in iMessage" : "Click Approve and publish",
    say: "Nothing goes to a crew until an officer signs off. Even from a text." },
  { id: "incab", t: 82, shot: "/incab, press Brief me, let the audio play ~8 s",
    say: "(Say nothing. Let the brief speak.)" },
];
const END_T = 92;
const fmtT = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/* ------------------------------------------------------------------ terminal */
const C = { dim: "\x1b[2m", b: "\x1b[1m", y: "\x1b[33m", c: "\x1b[36m", g: "\x1b[32m", r: "\x1b[31m", x: "\x1b[0m" };
const rl = readline.createInterface({ input: process.stdin });
const lineQueue = [];
let lineWaiter = null;
rl.on("line", () => (lineWaiter ? (lineWaiter(), (lineWaiter = null)) : lineQueue.push(1)));
const waitEnter = (prompt, ticker) =>
  new Promise((res) => {
    lineQueue.length = 0;
    let iv = null;
    const draw = () => process.stdout.write(`\r\x1b[K${C.dim}${prompt}${ticker ? ticker() : ""}${C.x}`);
    draw();
    if (ticker && process.stdout.isTTY) iv = setInterval(draw, 250);
    lineWaiter = () => {
      if (iv) clearInterval(iv);
      process.stdout.write(process.stdin.isTTY ? "\x1b[1A\r\x1b[K" : "\r\x1b[K\n");
      res();
    };
  });
const log = (...a) => console.log(`${C.dim}·${C.x}`, ...a);
const warn = (...a) => console.log(`${C.r}!${C.x}`, ...a);
function prompter(beat, i) {
  const next = BEATS[i + 1];
  console.log(`\n${C.c}${C.b}━━ ${fmtT(beat.t)}  ${beat.id.toUpperCase()} ━━${C.x}  ${C.dim}${beat.shot}${C.x}`);
  console.log(`${C.y}${C.b}  ${beat.say}${C.x}`);
  if (next) console.log(`${C.dim}  next ${fmtT(next.t)}: ${next.say.slice(0, 70)}${next.say.length > 70 ? "…" : ""}${C.x}`);
}
async function countdown(ms, label) {
  const end = Date.now() + ms;
  if (!process.stdout.isTTY) {
    console.log(`${label} ${(ms / 1000).toFixed(1)} s`);
    return sleep(ms);
  }
  while (Date.now() < end) {
    process.stdout.write(`\r\x1b[K${C.dim}${label} ${((end - Date.now()) / 1000).toFixed(1)} s${C.x}`);
    await sleep(Math.min(200, end - Date.now()));
  }
  process.stdout.write("\r\x1b[K");
}
const sleep = (ms) => new Promise((r) => setTimeout(r, Math.max(0, ms)));

/* ------------------------------------------------------------------ backend helpers */
async function api(p, init) {
  const r = await fetch(`${API}${p}`, { ...init, headers: { "content-type": "application/json" } });
  if (!r.ok) throw new Error(`${init?.method ?? "GET"} ${p} -> ${r.status}`);
  return r.json();
}
const runStatus = async (id) => (await api(`/runs`)).find((r) => r.run_id === id)?.status;

/* ------------------------------------------------------------------ browser */
const health = await api("/health").catch(() => null);
if (!health?.ok) {
  console.error(`Backend not reachable at ${API}/health. Start it with: make stage`);
  process.exit(1);
}
log(`backend ${health.mode} mode, ${health.buildings} buildings`);

const profile = fs.mkdtempSync(path.join(os.tmpdir(), "firstin-rec-"));
const ctx = await chromium.launchPersistentContext(profile, {
  channel: "chrome",
  headless: false,
  viewport: null, // real window, native devicePixelRatio (2 on Retina)
  chromiumSandbox: true, // otherwise Playwright adds --no-sandbox, which shows a warning infobar
  ignoreDefaultArgs: ["--enable-automation", "--no-sandbox"],
  args: [
    `--app=data:text/html,<title>FirstIn</title><body style="background:%23f6f5f2"></body>`,
    "--disable-infobars",
    "--autoplay-policy=no-user-gesture-required",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate,AutofillServerCommunication,MediaRouter",
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
    "--window-position=0,0",
    "--window-size=1440,860",
    ...(FULLSCREEN ? ["--start-fullscreen"] : []),
  ],
});
const page = ctx.pages()[0] ?? (await ctx.newPage());
await page.bringToFront();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

// Visible cursor dot + click ring, injected on every document.
await ctx.addInitScript(() => {
  const css = `
    #__cur{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
      background:rgba(30,64,175,.28);border:2px solid rgba(30,64,175,.9);box-shadow:0 0 0 2px rgba(255,255,255,.8);
      pointer-events:none;z-index:2147483647;transition:transform .12s ease,background .12s ease;will-change:left,top}
    #__cur.down{transform:scale(.7);background:rgba(30,64,175,.55)}
    .__ring{position:fixed;pointer-events:none;z-index:2147483646;border:3px solid rgba(234,88,12,.95);border-radius:8px;
      box-shadow:0 0 0 6px rgba(234,88,12,.18);animation:__ring 1.1s ease-out forwards}
    @keyframes __ring{0%{opacity:0;transform:scale(1.06)}15%{opacity:1;transform:scale(1)}70%{opacity:1}100%{opacity:0}}`;
  const boot = () => {
    if (document.getElementById("__cur")) return;
    const s = document.createElement("style");
    s.textContent = css;
    document.head.appendChild(s);
    const d = document.createElement("div");
    d.id = "__cur";
    const p = JSON.parse(sessionStorage.getItem("__cur") || "null") || { x: -40, y: -40 };
    d.style.left = p.x + "px";
    d.style.top = p.y + "px";
    document.body.appendChild(d);
  };
  addEventListener("mousemove", (e) => {
    const d = document.getElementById("__cur");
    if (!d) return;
    d.style.left = e.clientX + "px";
    d.style.top = e.clientY + "px";
    sessionStorage.setItem("__cur", JSON.stringify({ x: e.clientX, y: e.clientY }));
  }, true);
  addEventListener("mousedown", () => document.getElementById("__cur")?.classList.add("down"), true);
  addEventListener("mouseup", () => document.getElementById("__cur")?.classList.remove("down"), true);
  window.__ring = (r) => {
    const el = document.createElement("div");
    el.className = "__ring";
    Object.assign(el.style, { left: r.x - 5 + "px", top: r.y - 5 + "px", width: r.width + 10 + "px", height: r.height + 10 + "px" });
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 1200);
  };
  // record audio playback so the dry run can confirm the brief actually played
  window.__plays = [];
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    const p = play.call(this);
    const rec = { src: this.currentSrc || this.src, t: Date.now(), ok: null };
    window.__plays.push(rec);
    p?.then?.(() => (rec.ok = true), (e) => (rec.ok = String(e)));
    return p;
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", boot);
  else boot();
});

/* size the window so the page itself is exactly WxH */
async function sizeWindow() {
  if (FULLSCREEN) {
    await sleep(1200);
    return page.evaluate(() => [innerWidth, innerHeight]);
  }
  const scr = await page.evaluate(() => [screen.availWidth, screen.availHeight]);
  let [w, h] = SIZE === "auto" ? (scr[0] >= 1920 && scr[1] >= 1080 + 40 ? [1920, 1080] : [1440, 810]) : SIZE.split("x").map(Number);
  const cdp = await ctx.newCDPSession(page);
  const { windowId } = await cdp.send("Browser.getWindowForTarget");
  for (let i = 0; i < 3; i++) {
    const [iw, ih, ow, oh] = await page.evaluate(() => [innerWidth, innerHeight, outerWidth, outerHeight]);
    if (iw === w && ih === h) break;
    await cdp.send("Browser.setWindowBounds", { windowId, bounds: { left: 0, top: 0, width: ow + (w - iw), height: oh + (h - ih), windowState: "normal" } });
    await sleep(300);
  }
  const got = await page.evaluate(() => [innerWidth, innerHeight, devicePixelRatio]);
  log(`screen ${scr.join("x")}, target ${w}x${h}`);
  if (got[0] !== w || got[1] !== h) warn(`viewport is ${got[0]}x${got[1]} (wanted ${w}x${h}); screen ${scr.join("x")} may be too small`);
  return got;
}

/* ------------------------------------------------------------------ human-like input */
let mouse = { x: 700, y: 500 };
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
async function glide(x, y, ms) {
  const from = { ...mouse };
  const dist = Math.hypot(x - from.x, y - from.y);
  const dur = ms ?? Math.min(1100, 350 + dist * 0.7);
  const n = Math.max(8, Math.round(dur / 16));
  // slight arc so it doesn't look robotic
  const nx = -(y - from.y) / (dist || 1), ny = (x - from.x) / (dist || 1), bow = Math.min(40, dist * 0.08);
  for (let i = 1; i <= n; i++) {
    const t = ease(i / n), arc = Math.sin(Math.PI * t) * bow;
    await page.mouse.move(from.x + (x - from.x) * t + nx * arc, from.y + (y - from.y) * t + ny * arc);
    await sleep(dur / n - 4);
  }
  mouse = { x, y };
}
async function box(loc) {
  const el = loc.first();
  await el.waitFor({ state: "visible", timeout: 15000 });
  return el.boundingBox();
}
async function smoothScroll(loc, block = "center") {
  const el = loc.first();
  await el.waitFor({ state: "attached", timeout: 15000 });
  // scroll only the nearest scrolling container (scrollIntoView would also nudge the page root)
  await el.evaluate((n, b) => {
    let sc = n.parentElement;
    while (sc && !(sc.scrollHeight > sc.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement;
    if (!sc) return n.scrollIntoView({ behavior: "smooth", block: b });
    const r = n.getBoundingClientRect(), c = sc.getBoundingClientRect();
    const off = b === "start" ? r.top - c.top - 8 : r.top - c.top - (c.height - r.height) / 2;
    sc.scrollTo({ top: sc.scrollTop + off, behavior: "smooth" });
  }, block);
  let last = null;
  for (let i = 0; i < 30; i++) {
    await sleep(80);
    const y = (await el.boundingBox())?.y;
    if (last !== null && Math.abs(y - last) < 0.5) break;
    last = y;
  }
}
async function hover(loc, { dx = 0.5, dy = 0.5, ms } = {}) {
  const b = await box(loc);
  await glide(b.x + b.width * dx, b.y + b.height * dy, ms);
  return b;
}
async function ring(loc) {
  const b = await box(loc);
  await page.evaluate((r) => window.__ring?.(r), b);
}
async function click(loc, opts = {}) {
  const b = await hover(loc, opts);
  await sleep(180);
  await page.evaluate((r) => window.__ring?.(r), b);
  await sleep(120);
  await page.mouse.down();
  await sleep(70);
  await page.mouse.up();
}
const poke = () => page.mouse.move(mouse.x, mouse.y); // redraw the dot after navigation

/* ------------------------------------------------------------------ run source */
let runId = REUSE;
let runT0 = null;
async function startRun() {
  const r = await api("/preplan", { method: "POST", body: JSON.stringify({ building_id: BID, notify: !!IMESSAGE }) });
  runId = r.run_id;
  runT0 = Date.now();
  log(`prewarm run ${runId} (${r.mode})`);
}
const runAge = () => (runT0 ? `  [run ${runId} age ${((Date.now() - runT0) / 1000).toFixed(0)} s]` : "");

async function routeGenerate() {
  if (LIVE) return;
  await page.route(`${API}/preplan`, async (route) => {
    const cors = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "POST, OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    await sleep(350); // feel like a real round trip
    return route.fulfill({ status: 200, headers: cors, contentType: "application/json", body: JSON.stringify({ run_id: runId, mode: "agent", stream_url: `/stream/${runId}` }) });
  });
}

/* ------------------------------------------------------------------ beat actions */
const sel = {
  card: () => page.locator("aside button", { hasText: STREET }),
  generate: () => page.getByRole("button", { name: /Generate pre-plan/ }),
  section: (t) => page.locator("section").filter({ has: page.locator("h2", { hasText: new RegExp(`^${t}$`) }) }),
  approve: () => page.locator("button:has-text('Approve'):enabled"),
};
const ready = (t) => sel.section(t).filter({ hasNotText: "Waiting for" });

const actions = {
  async map() {
    await hover(sel.card(), { dx: 0.35 });
    await sleep(1800);
    await hover(sel.generate(), { dx: 0.3 });
    await sleep(1600);
    await click(sel.generate());
    if (LIVE) runT0 = Date.now();
    else if (runT0) log(`Generate clicked, run age ${((Date.now() - runT0) / 1000).toFixed(1)} s`);
    await page.waitForURL(/\/plan\//, { timeout: 15000 });
    if (LIVE) runId = decodeURIComponent(page.url().match(/\/plan\/([^?]+)/)[1]);
    await poke();
  },
  async trace() {
    await page.getByText("Subagents").first().waitFor({ timeout: 10000 });
    await hover(page.locator("aside li").first(), { dx: 0.3, ms: 700 });
    await sleep(700);
    const lanes = page.locator("aside ul li");
    for (let i = 0; i < 3; i++) {
      await hover(lanes.nth(i), { dx: 0.35, ms: 450 });
      await sleep(400);
    }
  },
  async building() {
    const t = Date.now();
    if (runId && !(await runStatus(runId).catch(() => null))) warn(`run ${runId} is unknown to the backend (was it restarted?). Re-run the walkthrough.`);
    await ready("Building").waitFor({ timeout: 90000 });
    if (Date.now() - t > 500) log(`waited ${((Date.now() - t) / 1000).toFixed(1)} s for the plan`);
    await sleep(400);
    await smoothScroll(sel.section("Building"), "start");
    await click(page.locator('[data-path="building.year_built"]'));
    await sleep(1600);
    await hover(page.locator('[data-path="building.sq_ft"]'), { dy: 0.4 });
    await sleep(1200);
    // "eleven dock doors": the Loading docks row, if it is on screen
    const docks = sel.section("Building").getByText("Loading docks", { exact: true }).first();
    const db = await docks.boundingBox().catch(() => null);
    const vh = await page.evaluate(() => innerHeight);
    if (db && db.y > 60 && db.y < vh - 90) await hover(docks, { dx: 2.2 });
  },
  async stair() {
    const s = page.locator('[data-path="interior.stairwells.0.loc"]');
    await smoothScroll(s);
    await click(s, { dx: 0.25 });
    await sleep(900);
    // let the pano settle, hover it gently
    const aside = page.locator("main + aside");
    const b = await aside.boundingBox();
    if (b) await glide(b.x + b.width * 0.12, b.y + b.height * 0.62, 900); // park beside the pano, not on the box
  },
  async roof() {
    const r = page.locator('[data-path="access.roof_access"]');
    await smoothScroll(r);
    await click(r, { dx: 0.25 });
    await sleep(1200);
    const aside = page.locator("main + aside");
    const b = await aside.boundingBox();
    if (b) {
      await glide(b.x + b.width * 0.45, b.y + b.height * 0.3, 900);
      await sleep(600);
      await glide(b.x + b.width * 0.6, b.y + b.height * 0.42, 900);
    }
  },
  async verify() {
    const h = page.getByText(/Verified across 2 sources/).first();
    if (await h.count()) {
      await smoothScroll(sel.section("Building"), "start");
      const tile = h.locator("xpath=../..");
      await hover(tile, { dx: 0.3 });
      await ring(tile);
      await sleep(2600);
    } else warn("height cross-check row not found");
    const w = page.locator("#walkthrough");
    await smoothScroll(w, "start");
    const hyd = page.locator('[data-path="check:access.hydrants"]');
    const item = (await hyd.count()) ? hyd : page.locator('[data-path^="check:"]');
    await click(item, { dx: 0.25 });
  },
  async approve() {
    await sel.approve().waitFor({ timeout: 90000 });
    if (IMESSAGE) {
      log(`waiting for APPROVE from the phone (run ${runId})...`);
      const btn = page.locator("button:has-text('Approve'):enabled");
      await hover(btn, { dx: 0.4 }).catch(() => {});
      for (;;) {
        const st = await runStatus(runId).catch(() => null);
        if (st === "APPROVED" || st === "REJECTED") {
          log(`run ${st}`);
          break;
        }
        await sleep(700);
      }
    } else {
      await click(sel.approve());
    }
    const tp = Date.now();
    await page.getByText(/Published to/).waitFor({ timeout: 30000 });
    log(`published ${((Date.now() - tp) / 1000).toFixed(1)} s after approval`);
    await sleep(600);
    await hover(page.getByText(/Published to/).first(), { dx: 0.2 });
  },
  async incab() {
    for (let i = 0; i < 40; i++) {
      const a = await api("/incab/active").catch(() => null);
      if (a?.plan_id === runId) break;
      await sleep(250);
    }
    await page.goto(`${BASE}/incab`, { waitUntil: "load" });
    await poke();
    const brief = page.getByRole("button", { name: /Brief me/ });
    await brief.waitFor({ timeout: 15000 });
    await page.getByText(new RegExp(STREET.split(" ")[0])).first().waitFor({ timeout: 10000 }).catch(() => {});
    await sleep(1000);
    await click(brief, { dx: 0.4 });
  },
};

/* ------------------------------------------------------------------ main */
await page.goto(`${BASE}/`, { waitUntil: "load" });
const vp = await sizeWindow();
log(`viewport ${vp[0]}x${vp[1]} @${vp[2]}x, profile ${profile}`);
await page.waitForSelector("text=Buildings");
await sleep(1500);
await poke();
await click(sel.card(), { dx: 0.35 }); // pre-roll: building selected, map flies to it
await sleep(2500);
await routeGenerate();

const preClick = 5; // seconds from the map beat start to the Generate click (measured ~5 s)
console.log(`\n${C.b}FirstIn walkthrough${C.x}  mode=${AUTO ? "auto" : "step"}  run=${REUSE ? `reuse ${REUSE}` : LIVE ? "live" : `prewarm, ${LEAD}s lead`}  approval=${IMESSAGE ? "iMessage" : "UI"}`);
const rect = await page.evaluate(() => ({ x: screenX, y: screenY + (outerHeight - innerHeight), w: innerWidth, h: innerHeight }));
console.log(`${C.dim}Start recording now: Cmd+Shift+5, "Record Selected Portion", drag exactly over the page (below the title bar):`);
console.log(`  x ${rect.x}, y ${rect.y}, ${rect.w} x ${rect.h} points. Then Record. Click into this terminal before pressing Enter.${C.x}`);
await waitEnter("Press Enter to begin. ");

let warm = 0;
if (!REUSE && !LIVE) {
  await startRun();
  warm = Math.max(0, LEAD - preClick);
}
if (warm > 0) await countdown(warm * 1000, "Agent warming up, first beat in");
else await countdown(3000, "First beat in");

const T0 = Date.now(); // == 0:42 on the SCRIPT.md clock
const timings = [];
for (let i = 0; i < BEATS.length; i++) {
  const beat = BEATS[i];
  if (i > 0) {
    if (AUTO) {
      const due = T0 + (beat.t - 42) * 1000;
      if (due > Date.now()) await countdown(due - Date.now(), `next: ${beat.id} in`);
    } else {
      await waitEnter(`Enter for ${fmtT(beat.t)} ${beat.id} `, beat.id === "building" || beat.id === "approve" ? runAge : null);
    }
  }
  const start = (Date.now() - T0) / 1000 + 42;
  prompter(beat, i);
  try {
    await actions[beat.id]();
  } catch (e) {
    warn(`${beat.id}: ${e.message.split("\n")[0]}`);
  }
  const end = (Date.now() - T0) / 1000 + 42;
  timings.push({ id: beat.id, script: beat.t, start, end });
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${String(i + 1).padStart(2, "0")}-${beat.id}.png`) }).catch(() => {});
}

// let the brief play out
if (AUTO) await countdown(Math.max(9000, (T0 + (END_T - 42) * 1000) - Date.now()), "voice brief playing, end in");
else await waitEnter("Enter when the brief has finished. ");
const plays = await page.evaluate(() => window.__plays ?? []).catch(() => []);
const finish = (Date.now() - T0) / 1000 + 42;

console.log(`\n${C.b}Beat timing vs SCRIPT.md${C.x}`);
for (const [i, t] of timings.entries()) {
  const nextScript = BEATS[i + 1]?.t ?? END_T;
  console.log(`  ${t.id.padEnd(9)} script ${fmtT(t.script)}  actual ${fmtT(t.start)} (${t.start - t.script >= 0 ? "+" : ""}${(t.start - t.script).toFixed(1)} s)  action ${(t.end - t.start).toFixed(1)} s  window ${nextScript - t.script} s`);
}
console.log(`  end       script ${fmtT(END_T)}  actual ${fmtT(finish)}`);
console.log(`  audio: ${plays.length ? plays.map((p) => `${p.ok === true ? "played" : `failed ${p.ok}`} ${p.src.split("/").pop()}`).join(", ") : "no audio element played (speechSynthesis fallback?)"}`);
console.log(`  run: ${runId}  page errors: ${errors.length ? errors.slice(0, 3).join(" | ") : "none"}`);
console.log(`\n${C.g}Done. Stop the recording (Cmd+Ctrl+Esc or the stop button in the menu bar).${C.x}`);
if (!CLOSE) await waitEnter("Enter to close the browser. ");
rl.close();
await ctx.close();
fs.rmSync(profile, { recursive: true, force: true });
