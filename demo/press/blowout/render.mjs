// Renders blowout.html frame by frame (deterministic seek at 30 fps) and encodes
// blowout.mp4, blowout.gif, blowout-final.png and blowout-still.png.
//
// Usage: node firstin/demo/press/blowout/render.mjs   (from anywhere)
//   Flags: --frames-only   render PNGs into frames/ and skip encoding
//          --keep          keep frames/ after encoding
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, copyFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "../../../web");
const require = createRequire(join(WEB, "package.json"));
const { chromium } = require("playwright-core");

const FPS = 30;
const W = 1920, H = 1080;
const HOLD_S = 1; // extra hold of the final frame in the mp4/gif
const STILL_T = 2870; // the flame going out: bent flame, breath, sparks and the displaced puff
const args = new Set(process.argv.slice(2));
const FRAMES = join(HERE, "frames");

function which(bin) {
  try { return execFileSync("which", [bin]).toString().trim(); } catch { return null; }
}

rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
await page.goto(pathToFileURL(join(HERE, "blowout.html")).href + "?render");
await page.evaluate(() => window.__ready);
const total = await page.evaluate(() => window.__TOTAL);
const n = Math.round((total / 1000) * FPS); // frames 0..n inclusive; frame n is the settled final frame

const shot = async (t, path) => {
  await page.evaluate((t) => window.__seek(t), t);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.screenshot({ path, type: "png" });
};

for (let i = 0; i <= n; i++) {
  await shot((i * 1000) / FPS, join(FRAMES, `f${String(i).padStart(4, "0")}.png`));
}
await shot(STILL_T, join(HERE, "blowout-still.png"));
await browser.close();
copyFileSync(join(FRAMES, `f${String(n).padStart(4, "0")}.png`), join(HERE, "blowout-final.png"));
console.log(`rendered ${n + 1} frames (${(total / 1000).toFixed(2)} s) + stills`);

if (args.has("--frames-only")) process.exit(0);

const ffmpeg = which("ffmpeg");
if (!ffmpeg) {
  console.error("ffmpeg not found; frames left in", FRAMES);
  process.exit(1);
}
const input = ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(FRAMES, "f%04d.png")];
const hold = `tpad=stop_mode=clone:stop_duration=${HOLD_S}`;

execFileSync(ffmpeg, [
  ...input,
  "-vf", `${hold},scale=${W}:${H},format=yuv420p`,
  "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "animation",
  "-r", String(FPS), "-movflags", "+faststart",
  join(HERE, "blowout.mp4"),
], { stdio: "inherit" });

// GIF: 960 px wide, 15 fps, palette tuned for flat colour
const pal = join(FRAMES, "palette.png");
execFileSync(ffmpeg, [
  ...input,
  "-vf", `${hold},fps=15,scale=960:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=full`,
  pal,
], { stdio: "inherit" });
const gif = join(HERE, "blowout.gif");
execFileSync(ffmpeg, [
  ...input, "-i", pal,
  "-lavfi", `${hold},fps=15,scale=960:-1:flags=lanczos[v];[v][1:v]paletteuse=dither=sierra2_4a:diff_mode=rectangle`,
  "-loop", "0",
  gif,
], { stdio: "inherit" });
const gifsicle = which("gifsicle");
if (gifsicle) execFileSync(gifsicle, ["-O3", "--batch", gif], { stdio: "inherit" });

if (!args.has("--keep")) rmSync(FRAMES, { recursive: true, force: true });
console.log("wrote blowout.mp4, blowout.gif, blowout-final.png, blowout-still.png");
if (existsSync(FRAMES)) console.log("frames kept in", FRAMES);
