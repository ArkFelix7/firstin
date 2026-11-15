// Render the iMessage recreations from transcript.json.
// Usage (from firstin/): node demo/press/imessage/render.mjs
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire("/Users/aarya/dev_all/hack-princton/firstin/web/package.json");
const { chromium } = require("playwright-core");

const DIR = dirname(fileURLToPath(import.meta.url));
const transcript = JSON.parse(readFileSync(join(DIR, "transcript.json"), "utf8"));
// Long bot messages that do not fit: keep these whole lines (by index), "…" marks dropped lines.
const ELIDE = JSON.parse(process.env.ELIDE || "null") || {
  0: [0, 1, "…", 5, 6, 7, 8, "…"],
  4: [0, 1, "…", 12],
};

const browser = await chromium.launch({ channel: "chrome" });
async function shot(view, dsf, out, sel) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: dsf });
  await page.addInitScript(([t, e]) => { window.TRANSCRIPT = t; window.ELIDE = e; }, [transcript, ELIDE]);
  await page.goto("file://" + join(DIR, "render.html") + "?view=" + view);
  await page.evaluate(() => window.build());
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => Promise.all([...document.images].map(i => i.decode())));
  const overflow = await page.evaluate(() => window.OVERFLOW);
  await page.locator(sel).screenshot({ path: join(DIR, out), omitBackground: true });
  console.log(out, "overflow px:", overflow);
  await page.close();
}
await shot("approve", 3, "approve.png", ".phone");
await shot("standpipe", 3, "standpipe.png", ".phone");
await shot("combined", 2, "combined.png", ".slide");
await shot("combined-real", 2, "combined-real.png", ".slide");
await browser.close();
