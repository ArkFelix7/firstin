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
  // --- Recent (2025-2026), newest first. See SOURCES.md "Recent".
  { slug: "recent-brooklyn-sunsetpark-2026", kind: "capture", outlet: "Associated Press, via Spectrum News NY1", date: "November 5, 2026", url: "ny1.com/nyc/all-boroughs/ap-top-news/2026/11/05/house-fire-in-brooklyn-kills-6-people-..." },
  { slug: "recent-durham-collapse-2026", kind: "capture", outlet: "ABC11 Raleigh-Durham (WTVD)", date: "October 8, 2026", url: "abc11.com/post/firefighter-dies-durham-working-massive-fire-2-other-firefighters-injured/19921200" },
  { slug: "recent-niosh-f2026-04-cover-2026", kind: "capture", outlet: "NIOSH Fire Fighter Fatality Investigation, Report F2026-04 (Chicago, Mar. 16, 2026)", date: "November 2026", url: "cdc.gov/niosh/firefighters/programs/pdfs/f202604.pdf" },
  { slug: "recent-la-hope-st-2026", kind: "capture", outlet: "Los Angeles Fire Department, news release", date: "May 11, 2026", url: "lafd.org/news/major-emergency-structure-fire-downtown-los-angeles-one-firefighter-injured" },
  { slug: "recent-niosh-f2025-09-cover-2026", kind: "capture", outlet: "NIOSH Fire Fighter Fatality Investigation, Report F2025-09", date: "March 2026", url: "cdc.gov/niosh/firefighters/programs/pdfs/f202509.pdf" },
  { slug: "recent-niosh-f2025-09-preplan-2026", kind: "capture", outlet: "NIOSH Report F2025-09, Recommendation #8 (p. 28)", date: "March 2026", url: "cdc.gov/niosh/firefighters/programs/pdfs/f202509.pdf" },
  { slug: "recent-chicago-altman-2026", kind: "capture", outlet: "FOX 32 Chicago", date: "March 17, 2026", url: "fox32chicago.com/news/chicago-firefighter-dies-north-side" },
  { slug: "recent-houston-braesridge-2025", kind: "capture", outlet: "KPRC 2 Click2Houston", date: "December 19, 2025", url: "click2houston.com/news/local/2025/12/19/apartment-fire-draws-emergency-response-in-sw-houston" },
  { slug: "recent-la-highrise-2025", kind: "capture", outlet: "CBS Los Angeles", date: "September 16, 2025", url: "cbsnews.com/losangeles/news/downtown-los-angeles-high-rise-fire" },
  { slug: "recent-dekalb-warehouse-2025", kind: "capture", outlet: "Atlanta News First", date: "September 8, 2025", url: "atlantanewsfirst.com/2025/09/09/dekalb-county-firefighter-dies-after-battling-blaze-lithonia-warehouse" },
  { slug: "recent-niosh-f2023-07-cover-2025", kind: "capture", outlet: "NIOSH Fire Fighter Fatality Investigation, Report F2023-07", date: "April 2025", url: "cdc.gov/niosh/firefighters/programs/pdfs/face202307.pdf" },
  { slug: "recent-columbia-sc-collapse-2023", kind: "capture", outlet: "WIS News 10, Columbia, S.C.", date: "May 26, 2023", url: "wistv.com/2023/05/26/columbia-richland-fire-department-multiple-people-rescued-apartment-fire" },
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

const clipURI = (slug) => "data:image/png;base64," + fs.readFileSync(path.join(here, "clips", `${slug}.png`)).toString("base64");
const BG = "background: radial-gradient(ellipse at 50% 40%, #2a2724 0%, #151413 75%);";
async function shot(html, out) {
  const cpage = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await cpage.setContent(`<style>body{margin:0;width:1920px;height:1080px;overflow:hidden;position:relative;${BG}}
    .t{position:absolute;font:400 22px/1 Georgia,serif;letter-spacing:.32em;color:rgba(245,241,232,.55);text-transform:uppercase}</style>${html}`);
  await cpage.waitForTimeout(300);
  await cpage.screenshot({ path: path.join(here, out) });
  await cpage.close();
  console.log("wrote", out);
}
const place = (rows) => rows.map(([slug, l, t, w, r, z]) =>
  `<img src="${clipURI(slug)}" style="position:absolute;left:${l}px;top:${t}px;width:${w}px;transform:rotate(${r}deg);z-index:${z}">`).join("");

// Collage 1920x1080 from rendered clips (original, 2007-2023)
await shot(place(COLLAGE), "collage.png");

// Recent collage, 2025-2026
const COLLAGE_RECENT = [
  ["recent-durham-collapse-2026", 50, 70, 840, -1.4, 3],
  ["recent-brooklyn-sunsetpark-2026", 960, 50, 900, 1.1, 2],
  ["recent-chicago-altman-2026", 1010, 300, 850, -0.8, 4],
  ["recent-niosh-f2025-09-preplan-2026", 70, 330, 900, 0.9, 5],
  ["recent-houston-braesridge-2025", 1030, 690, 800, 1.6, 6],
  ["recent-dekalb-warehouse-2025", 90, 770, 860, -1.2, 7],
];
await shot(place(COLLAGE_RECENT) + `<div class="t" style="left:60px;top:28px">2025 to 2026</div>`, "collage-recent.png");

// Timeline strip: old and new together. Alternating above/below a horizontal rule.
const TIMELINE = [
  ["charleston-nbc-2007", "June 2007", "Charleston, S.C."],
  ["southwest-inn-nbc-2013", "May 2013", "Houston"],
  ["i10-abc7-2023", "Nov 2023", "Los Angeles"],
  ["recent-dekalb-warehouse-2025", "Sept 2025", "DeKalb Co., Ga."],
  ["recent-houston-braesridge-2025", "Dec 2025", "Houston"],
  ["recent-chicago-altman-2026", "Mar 2026", "Chicago"],
  ["recent-la-hope-st-2026", "May 2026", "Los Angeles"],
  ["recent-durham-collapse-2026", "Oct 2026", "Durham, N.C."],
  ["recent-brooklyn-sunsetpark-2026", "Nov 2026", "Brooklyn, N.Y."],
];
const LINE_Y = 540, X0 = 215, X1 = 1705, CW = 395, GAP = 96;
let tl = `<div style="position:absolute;left:70px;right:70px;top:${LINE_Y}px;height:2px;background:rgba(245,241,232,.35)"></div>`;
TIMELINE.forEach(([slug, when, where], i) => {
  const x = X0 + ((X1 - X0) * i) / (TIMELINE.length - 1);
  const up = i % 2 === 0;
  const dot = slug.startsWith("recent-") ? "#c8462e" : "rgba(245,241,232,.75)";
  tl += `<div style="position:absolute;left:${x - 7}px;top:${LINE_Y - 6}px;width:14px;height:14px;border-radius:50%;background:${dot}"></div>`;
  // label sits between dot and card, on the card's side
  tl += `<div style="position:absolute;left:${x - 110}px;width:220px;text-align:center;top:${up ? LINE_Y - 62 : LINE_Y + 18}px;
    font:600 18px/1.25 Georgia,serif;color:rgba(245,241,232,.88)">${when}<br><span style="font-weight:400;font-size:14px;color:rgba(245,241,232,.55)">${where}</span></div>`;
  tl += `<div style="position:absolute;left:${x}px;top:${up ? LINE_Y - GAP - 6 : LINE_Y + 66}px;width:1px;height:36px;background:rgba(245,241,232,.25)"></div>`;
  const left = Math.max(16, Math.min(1920 - CW - 16, x - CW / 2));
  tl += `<div style="position:absolute;left:${left}px;width:${CW}px;${up ? `bottom:${1080 - LINE_Y + GAP}px` : `top:${LINE_Y + GAP}px`};z-index:${i + 2}">
    <img src="${clipURI(slug)}" style="width:100%;display:block;transform:rotate(${((i % 3) - 1) * 0.8}deg)"></div>`;
});
tl += `<div style="position:absolute;left:60px;bottom:34px;font:15px/1 Georgia,serif;color:rgba(245,241,232,.5)">
  <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:rgba(245,241,232,.75);margin-right:8px"></span>2007 to 2023
  <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#c8462e;margin:0 8px 0 28px"></span>2025 to 2026</div>`;
await shot(tl + `<div class="t" style="left:60px;top:28px">2007 to 2026</div>`, "collage-timeline.png");
await browser.close();
