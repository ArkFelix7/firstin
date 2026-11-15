// Zoomed-out map still for the pitch video close (3,288 buildings, clustered).
//   node demo/video/shot_map.mjs [out.png]   (needs the web app on :3000)
import { createRequire } from "module";
import path from "path";
import { fileURLToPath } from "url";
const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "../../web/package.json"));
const { chromium } = require("playwright-core");
const out = process.argv[2] || path.join(here, "assets/map-zoomed-out.png");
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-gl=angle", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto("http://localhost:3000/", { waitUntil: "load" });
await page.waitForTimeout(5000);
if (process.env.CLOSE_PANEL !== "0") { const x = page.locator("button[aria-label*=lose]").first(); if (await x.count()) await x.click().catch(() => {}); await page.waitForTimeout(500); }
const zoomOut = page.locator(".maplibregl-ctrl-zoom-out");
const n = +(process.env.ZOOM_STEPS || 1);
for (let i = 0; i < n; i++) { await zoomOut.click(); await page.waitForTimeout(700); }
await page.waitForTimeout(4000);
await page.screenshot({ path: out });
console.log("saved", out);
await browser.close();
