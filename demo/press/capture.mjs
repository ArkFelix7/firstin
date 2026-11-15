// Capture headline + deck + byline/date regions of news articles as cropped PNGs.
// Usage: node demo/press/capture.mjs [slug ...]   (run from firstin/)
// Captures only the headline region (not article body). Paywalled pages are not bypassed.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.resolve(here, "../../web/package.json"));
const { chromium } = require("playwright-core");

// sel: optional selector for the headline (default h1). w: optional fixed crop width.
// below: px below the h1 bottom to include deck + byline/date. extra selectors are unioned in if present.
export const TARGETS = [
  { slug: "southwest-inn-nbc-2013", url: "https://www.nbcnews.com/news/us-news/cause-blaze-killed-four-houston-firefighters-under-investigation-flna6C10149696", below: 150 },
  { slug: "southwest-inn-kprc-niosh-2015", url: "https://www.click2houston.com/news/2015/07/21/final-report-on-southwest-inn-fire-finds-eight-contributing-factors", below: 16 },
  { slug: "southwest-inn-kprc-dowling-2017", url: "https://www.click2houston.com/news/2017/03/08/capt-bill-dowling-firefighter-injured-in-2013-southwest-inn-fire-dies-at-43", below: 16 },
  { slug: "charleston-nbc-2007", url: "https://www.nbcnews.com/id/wbna19331229", below: 126 },
  { slug: "i10-ap-hazards-2023", url: "https://www.fireengineering.com/fire-safety/investigators-found-fire-safety-hazards-freeway-arson/", below: 116 },
  { slug: "i10-ap-repairs-2023", url: "https://komonews.com/news/nation-world/speedy-repairs-to-arson-fire-damaged-la-los-angeles-freeway-promise-early-reopening-governor-gavin-newsom-interstate-10-pallets-cars-construction-materials-sanitizer-arrests", below: 118 },
  { slug: "i10-abc7-2023", url: "https://abc7.com/post/downtown-la-fire-10-freeway-closed/14044563/", below: 140 },
  { slug: "watson-abc13-2023", url: "https://abc13.com/13446456", below: 140 },
  // watson-khou-2023: KHOU returns 403 to automated browsers -> typeset instead (see SOURCES.md)
  // --- Recent (2025-2026). Headline + deck/date only; crops stop above any lead photo.
  { slug: "recent-brooklyn-sunsetpark-2026", url: "https://ny1.com/nyc/all-boroughs/ap-top-news/2026/11/05/house-fire-in-brooklyn-kills-6-people-and-injures-7-more-than-200-firefighters-respond1", below: 80 },
  { slug: "recent-durham-collapse-2026", url: "https://abc11.com/post/firefighter-dies-durham-working-massive-fire-2-other-firefighters-injured/19921200/", below: 16 },
  { slug: "recent-la-hope-st-2026", url: "https://lafd.org/news/major-emergency-structure-fire-downtown-los-angeles-one-firefighter-injured", below: 68, sel: 'h1:has-text("Major Emergency"), h2:has-text("Major Emergency"), h3:has-text("Major Emergency")' },
  { slug: "recent-chicago-altman-2026", url: "https://www.fox32chicago.com/news/chicago-firefighter-dies-north-side", below: 60 },
  { slug: "recent-houston-braesridge-2025", url: "https://www.click2houston.com/news/local/2025/12/19/apartment-fire-draws-emergency-response-in-sw-houston/", below: 8 },
  { slug: "recent-la-highrise-2025", url: "https://www.cbsnews.com/losangeles/news/downtown-los-angeles-high-rise-fire/", below: 90 },
  { slug: "recent-dekalb-warehouse-2025", url: "https://www.atlantanewsfirst.com/2025/09/09/dekalb-county-firefighter-dies-after-battling-blaze-lithonia-warehouse/", below: 6 },
  { slug: "recent-columbia-sc-collapse-2023", url: "https://www.wistv.com/2023/05/26/columbia-richland-fire-department-multiple-people-rescued-apartment-fire/", below: 5 },
];

const COOKIE_TEXT = /^(accept( all)?|i accept|agree|i agree|got it|ok|okay|continue|allow all|close)$/i;

async function dismiss(page) {
  for (const frame of page.frames()) {
    try {
      const btns = frame.getByRole("button");
      const n = Math.min(await btns.count(), 60);
      for (let i = 0; i < n; i++) {
        const b = btns.nth(i);
        const t = ((await b.innerText({ timeout: 300 }).catch(() => "")) || "").trim();
        if (COOKIE_TEXT.test(t) && (await b.isVisible().catch(() => false))) {
          await b.click({ timeout: 1000 }).catch(() => {});
        }
      }
    } catch {}
  }
  await page.keyboard.press("Escape").catch(() => {});
}

async function captureOne(browser, t) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const res = { slug: t.slug, url: t.url };
  try {
    const r = await page.goto(t.url, { waitUntil: "domcontentloaded", timeout: 45000 });
    res.status = r?.status();
    await page.waitForTimeout(3500);
    await dismiss(page);
    await page.waitForTimeout(800);
    const h1 = page.locator(t.sel ?? "h1").first();
    await h1.scrollIntoViewIfNeeded({ timeout: 5000 });
    await page.evaluate(() => window.scrollBy(0, -140));
    await page.waitForTimeout(600);
    res.headline = (await h1.innerText()).trim();
    const b = await h1.boundingBox();
    const x = Math.max(0, b.x - 24);
    const y = Math.max(0, b.y - 24);
    const w = Math.min(1280 - x, t.w ?? Math.max(b.width + 48, 760));
    const h = Math.min(900 - y, b.height + 24 + (t.below ?? 160));
    const out = path.join(here, "raw", `${t.slug}.png`);
    await page.screenshot({ path: out, clip: { x, y, width: w, height: h } });
    res.file = out;
  } catch (e) {
    res.error = String(e).slice(0, 200);
  }
  await ctx.close();
  return res;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const only = process.argv.slice(2);
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const results = [];
  for (const t of TARGETS.filter((t) => !only.length || only.includes(t.slug))) {
    const r = await captureOne(browser, t);
    console.log(JSON.stringify(r));
    results.push(r);
  }
  await browser.close();
  fs.writeFileSync(path.join(here, "raw", "capture-log.json"), JSON.stringify(results, null, 2));
}
