// Quick single-page screenshot for design review.
//   node scripts/shot.mjs <path> <out.png> [width] [height] [waitMs]
import { chromium } from "playwright-core";
const [, , path = "/", out = "/tmp/shot.png", w = "1440", h = "900", wait = "3500"] = process.argv;
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-gl=angle", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: +w, height: +h } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(`http://localhost:3000${path}`, { waitUntil: "load" });
await page.waitForTimeout(+wait);
await page.screenshot({ path: out });
console.log("saved", out, errors.length ? errors : "no console errors");
await browser.close();
