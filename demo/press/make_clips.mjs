// Render "newspaper clipping" cards from raw captures (or typeset headlines) + a 1920x1080 collage.
// Usage (from firstin/): node demo/press/make_clips.mjs
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.resolve(here, "../../web/package.json"));
const { chromium } = require("playwright-core");

// kind: "capture" = cropped screenshot from raw/; "typeset" = real headline set in serif (page paywalled/blocked).
export const CLIPS = [
  { slug: "southwest-inn-nbc-2013", kind: "capture", outlet: "NBC News", date: "May 31, 2013", url: "nbcnews.com/news/us-news/cause-blaze-killed-four-houston-firefighters-under-investigation-flna6C10149696" },
  { slug: "southwest-inn-kprc-niosh-2015", kind: "capture", outlet: "KPRC 2 Click2Houston", date: "July 20, 2015", url: "click2houston.com/news/2015/07/21/final-report-on-southwest-inn-fire-finds-eight-contributing-factors" },
  { slug: "southwest-inn-kprc-dowling-2017", kind: "capture", outlet: "KPRC 2 Click2Houston", date: "March 8, 2017", url: "click2houston.com/news/2017/03/08/capt-bill-dowling-firefighter-injured-in-2013-southwest-inn-fire-dies-at-43" },
  { slug: "niosh-f2013-16-cover", kind: "capture", outlet: "NIOSH Fire Fighter Fatality Investigation, Report F2013-16", date: "July 8, 2015", url: "stacks.cdc.gov/view/cdc/163331" },
  { slug: "sfmo-fy13-08-finding1", kind: "capture", outlet: "Texas State Fire Marshal's Office, Investigation FFF FY 13-08", date: "2014", url: "tdi.texas.gov/reports/fire/documents/fmloddhouston2013.pdf" },
  { slug: "charleston-nbc-2007", kind: "capture", outlet: "NBC News / Associated Press", date: "June 20, 2007", url: "nbcnews.com/id/wbna19331229" },
  { slug: "niosh-f2007-18-cover", kind: "capture", outlet: "NIOSH Fire Fighter Fatality Investigation, Report F2007-18", date: "February 11, 2009", url: "stacks.cdc.gov/view/cdc/163618" },
  { slug: "niosh-f2007-18-preplan-form", kind: "capture", maxw: 620, outlet: "Charleston FD pre-plan form, Apr. 26, 2006, reproduced in NIOSH F2007-18, Appendix III", date: "2009", url: "stacks.cdc.gov/view/cdc/163618" },
  { slug: "i10-abc7-2023", kind: "capture", outlet: "ABC7 Los Angeles", date: "November 12, 2023", url: "abc7.com/post/downtown-la-fire-10-freeway-closed/14044563" },
  { slug: "i10-latimes-2023", kind: "typeset", headline: "10 Freeway in downtown L.A. shut down after fire; Newsom declares state of emergency", byline: "By Ruben Vives", outlet: "Los Angeles Times", date: "November 12, 2023", url: "latimes.com (paywalled; text via everand.com/article/683928155)" },
  { slug: "i10-ap-hazards-2023", kind: "capture", outlet: "Associated Press, via Fire Engineering", date: "November 19, 2023", url: "fireengineering.com/fire-safety/investigators-found-fire-safety-hazards-freeway-arson" },
  { slug: "i10-ap-repairs-2023", kind: "capture", outlet: "Associated Press, via KOMO News", date: "November 17, 2023", url: "komonews.com/news/nation-world/speedy-repairs-to-arson-fire-damaged-la-los-angeles-freeway-..." },
  { slug: "watson-abc13-2023", kind: "capture", outlet: "ABC13 Houston", date: "June 30, 2023", url: "abc13.com/13446456" },
];

const COLLAGE = [
  // slug, left, top, width, rotate(deg), z
  ["niosh-f2013-16-cover", 60, 55, 830, -1.6, 2],
  ["southwest-inn-nbc-2013", 950, 40, 900, 1.2, 3],
  ["sfmo-fy13-08-finding1", 100, 405, 900, 0.8, 5],
  ["niosh-f2007-18-preplan-form", 1440, 372, 430, 2.4, 4],
  ["charleston-nbc-2007", 60, 790, 800, -0.9, 6],
  ["i10-abc7-2023", 850, 735, 560, -1.8, 7],
];

function tornPath(seed) {
  // jagged bottom edge polygon for clip-path, deterministic per slug
  let s = [...seed].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  const rnd = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
  const pts = ["0% 0%", "100% 0%"];
  const n = 46;
  for (let i = n; i >= 0; i--) {
    const x = (i / n) * 100;
    const y = 100 - rnd() * 1.6 - (i % 2) * 0.5;
    pts.push(`${x.toFixed(2)}% calc(${y.toFixed(2)}% - ${(rnd() * 5).toFixed(1)}px)`);
  }
  return `polygon(${pts.join(",")})`;
}

const CSS = `
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: transparent; font-family: Georgia, "Times New Roman", serif; }
  .card {
    display: inline-block; position: relative; padding: 26px 28px 30px; color: #1d1b17;
    background:
      radial-gradient(ellipse at 20% 10%, rgba(255,255,255,.55), transparent 60%),
      radial-gradient(ellipse at 90% 90%, rgba(120,100,60,.07), transparent 55%),
      repeating-linear-gradient(0deg, rgba(0,0,0,.012) 0 1px, transparent 1px 3px),
      #f5f1e8;
    box-shadow: 0 1px 0 rgba(0,0,0,.04);
  }
  .shadow { display: inline-block; filter: drop-shadow(0 6px 14px rgba(0,0,0,.22)) drop-shadow(0 1px 2px rgba(0,0,0,.18)); padding: 18px; }
  .img { display: block; border: 1px solid rgba(0,0,0,.08); }
  .meta { margin-top: 14px; padding-top: 9px; border-top: 1px solid rgba(29,27,23,.35);
          font: 13px/1.45 Georgia, serif; letter-spacing: .02em; color: #3b372f; max-width: 100%; }
  .meta b { font-variant: small-caps; letter-spacing: .06em; font-weight: 600; color: #1d1b17; }
  .meta .u { display:block; font-family: Menlo, monospace; font-size: 11px; color: #6b655a; word-break: break-all; }
  .ts { width: 900px; }
  .ts .kicker { font: 600 12px/1 Georgia, serif; letter-spacing: .22em; text-transform: uppercase; color: #6b655a;
                border-bottom: 2px solid #1d1b17; padding-bottom: 8px; margin-bottom: 14px; }
  .ts h1 { font: 700 46px/1.08 Georgia, "Times New Roman", serif; letter-spacing: -.01em; }
  .ts .by { margin-top: 12px; font: italic 16px/1.3 Georgia, serif; color: #3b372f; }
  .ts .note { margin-top: 6px; font: 11px/1.3 Menlo, monospace; color: #8a8377; }
`;

function cardHTML(c, dataUri) {
  const body = c.kind === "typeset"
    ? `<div class="ts"><div class="kicker">${c.outlet}</div><h1>${c.headline}</h1><div class="by">${c.byline} &middot; ${c.date}</div><div class="note">Headline typeset from the original (page paywalled); not a screenshot.</div></div>`
    : `<img class="img" src="${dataUri}" style="width:${c.maxw ?? 1000}px">`;
  return `<div class="shadow"><div class="card" style="clip-path:${tornPath(c.slug)}">${body}
    <div class="meta" style="width:${c.kind === "typeset" ? 900 : c.maxw ?? 1000}px"><b>${c.outlet}</b> &middot; ${c.date}<span class="u">${c.url}</span></div></div></div>`;
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 1400 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
fs.mkdirSync(path.join(here, "clips"), { recursive: true });

for (const c of CLIPS) {
  let uri = "";
  if (c.kind === "capture") {
    const f = path.join(here, "raw", `${c.slug}.png`);
    if (!fs.existsSync(f)) { console.warn("missing", f); continue; }
    uri = "data:image/png;base64," + fs.readFileSync(f).toString("base64");
  }
  await page.setContent(`<style>${CSS}</style>${cardHTML(c, uri)}`);
  await page.waitForTimeout(150);
  await page.locator(".shadow").screenshot({ path: path.join(here, "clips", `${c.slug}.png`), omitBackground: true });
  console.log("clip", c.slug);
}

// Collage 1920x1080 from rendered clips
const items = COLLAGE.map(([slug, l, t, w, r, z]) => {
  const uri = "data:image/png;base64," + fs.readFileSync(path.join(here, "clips", `${slug}.png`)).toString("base64");
  return `<img src="${uri}" style="position:absolute;left:${l}px;top:${t}px;width:${w}px;transform:rotate(${r}deg);z-index:${z}">`;
}).join("");
const cpage = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await cpage.setContent(`<style>body{margin:0;width:1920px;height:1080px;overflow:hidden;
  background: radial-gradient(ellipse at 50% 40%, #2a2724 0%, #151413 75%);}</style>${items}`);
await cpage.waitForTimeout(300);
await cpage.screenshot({ path: path.join(here, "collage.png") });
console.log("collage done");
await browser.close();
