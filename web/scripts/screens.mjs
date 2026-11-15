// Capture demo screenshots of the full flow.
//   node scripts/screens.mjs [--mock] [--building la-002] [--prefix live-la-002] [--out ../demo/screens] [--only plan|incab] [--width 1440 --height 900]
// Uses the locally installed Google Chrome via playwright-core. Dev server must be on :3000.
import { chromium } from "playwright-core";
import path from "node:path";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, arr) => {
    if (a.startsWith("--")) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : "1"]);
    return acc;
  }, []),
);
const BASE = args.base ?? "http://localhost:3000";
const OUT = path.resolve(args.out ?? "../demo/screens");
const BID = args.building ?? "la-002";
const MOCK = !!args.mock;
const PREFIX = args.prefix ?? `${MOCK ? "mock" : "live"}-${BID}`;
const q = MOCK ? "?mock=1" : "";

const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-gl=angle", "--enable-unsafe-swiftshader"] });
const ctx = await browser.newContext({ viewport: { width: Number(args.width ?? 1440), height: Number(args.height ?? 900) }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
const shot = async (name) => {
  await page.screenshot({ path: path.join(OUT, `${PREFIX}-${name}.png`) });
  console.log("saved", `${PREFIX}-${name}.png`);
};
const wait = (ms) => page.waitForTimeout(ms);
const tryClick = async (loc, label) => {
  try {
    await loc.first().click({ timeout: 3000 });
    return true;
  } catch {
    console.log("skip click:", label);
    return false;
  }
};

if (!args.only || args.only === "plan") {
  await page.goto(`${BASE}/${q}`, { waitUntil: "load" });
  await page.waitForSelector("text=Buildings");
  await wait(2500);
  const street = { "la-002": "1601 Perrino Pl", "la-001": "337 S Broadway", "la-003": "10940 Wilshire Blvd", "hou-001": "4201 Main St", "hou-002": "2520 Washington Ave" }[BID];
  if (BID.startsWith("hou")) await tryClick(page.getByRole("tab", { name: "Houston" }), "city");
  await wait(800);
  await page.locator("aside button", { hasText: street }).first().click();
  await wait(3500);
  await shot("01-home");
  await page.getByRole("button", { name: /Generate pre-plan/ }).click();
  await page.waitForURL(/\/plan\//);
  await wait(5500);
  await shot("02-plan-running");
  await page.locator("button:has-text('Reject'):enabled").waitFor({ timeout: 90000 });
  await wait(3500);
  await shot("03-awaiting-approval");
  if (await tryClick(page.locator('[data-path="interior.stairwells.0.loc"]'), "stairwell")) {
    await wait(4000);
    await shot("04-evidence-matterport-360");
  }
  // a Vexcel-cited field (roof/access/exposure) so the ortho + bbox shows
  const vxSel = ['[data-path="access.roof_access"]', '[data-path^="access."]', '[data-path^="exposures."]', '[data-path="building.roof"]'];
  let vxOk = false;
  for (const sel of vxSel) {
    const loc = page.locator(sel).filter({ has: page.getByRole("button", { name: /^Vexcel/ }) });
    if ((await loc.count()) > 0 && (await tryClick(loc, sel))) {
      vxOk = true;
      break;
    }
  }
  if (vxOk) {
    await wait(2500);
    await shot("05-evidence-vexcel");
  }
  if (await tryClick(page.locator('#hazards tbody tr'), "hazard")) {
    await wait(3500);
    await shot("06-evidence-hazard");
  }
  if (await tryClick(page.locator('[data-path="access.hydrants"]'), "hydrants")) {
    await wait(800);
    await shot("07-verify-on-site");
  }
  // The run may already have been approved elsewhere (e.g. iMessage via Photon) → skip the edit step.
  if (await tryClick(page.getByRole("button", { name: /^Edit$/ }), "edit (already approved?)")) {
    await wait(500);
    const hyd = page.locator('[data-path="access.hydrants"] input');
    await hyd.fill("Hydrant confirmed on walk-through, NE corner").catch(() => console.log("skip edit"));
    await wait(400);
    await shot("08-edit-mode");
    await tryClick(page.getByRole("button", { name: /Save and approve/ }), "save & approve");
  }
  await page.getByText(/Published to/).waitFor({ timeout: 30000 });
  await wait(1500);
  await shot("09-published");
}

if (!args.only || args.only === "incab") {
  await page.goto(`${BASE}/incab${q}`, { waitUntil: "load" });
  await wait(3000);
  await shot("10-incab");
}

console.log("console errors:", errors.length ? errors : "none");
await browser.close();
