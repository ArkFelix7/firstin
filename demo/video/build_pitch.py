#!/usr/bin/env python3
"""Build the 2-minute FirstIn pitch video.

    agent/.venv/bin/python demo/video/build_pitch.py            # full build
    agent/.venv/bin/python demo/video/build_pitch.py --sheet    # + contact sheet

Outputs (in demo/video/):
    firstin-pitch-2min.mp4         captions + voice-brief audio (narrate over it)
    firstin-pitch-2min-voiced.mp4  same + synthetic `say` narration (fallback)
    firstin-pitch-2min.srt         caption file for Devpost / YouTube
    build/                         intermediates (safe to delete)

Re-runnable: it picks up demo/press/collage-timeline.png automatically if it
exists (pan 2007 -> 2026, then the push into Houston 2013 on collage.png).
ffmpeg here has no drawtext/libass, so all text is rendered with Pillow.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PRESS = ROOT / "demo" / "press"
BUILD = HERE / "build"
FONTS = HERE / "fonts"
DEMO = HERE / "firstin-product-demo.mp4"
BLOWOUT = PRESS / "blowout" / "blowout.mp4"
OUT_A = HERE / "firstin-pitch-2min.mp4"
OUT_B = HERE / "firstin-pitch-2min-voiced.mp4"
OUT_SRT = HERE / "firstin-pitch-2min.srt"

W, H, FPS = 1920, 1080, 30
SR = 48000
XF = 0.4  # default cross-fade between segments

# Palette (web/DESIGN.md)
OFFWHITE = (244, 242, 238)
INK = (22, 25, 29)
FG2 = (61, 67, 75)
FG3 = (107, 112, 120)
LINE = (217, 213, 206)
ACCENT = (37, 84, 199)
PRESS_BG = (21, 20, 19)  # collage background

VOICE = os.environ.get("PITCH_VOICE", "Samantha")
SAY_RATE = int(os.environ.get("PITCH_SAY_RATE", "182"))

# Product demo cut points (seconds in firstin-product-demo.mp4).
# Brief audio starts at 47.23. Phrases (silencedetect): ... "concrete tilt-up." ends
# 51.76 | "Tenant MDB Transportation ... floor 1." 52.17-56.13 | "Hazards: rooftop
# solar array, asbestos-containing materials, concrete tilt-up walls." 56.45-61.61 |
# "Two stairs..." starts 61.91. We drop the tenant sentence so the brief runs ~10 s
# and still ends on "...concrete tilt-up walls."
PROD_A = (0.0, 38.6)          # map -> agent -> building -> 360 -> access -> verify -> approve bar
PROD_B1 = (39.4, 40.8)        # click Approve and publish
PROD_B2 = (44.0, 45.0)        # "Approved by Capt. Station 12 ... Published to Engine 12" (publishing gap cut)
PROD_C1 = (46.5, 51.95)       # in-cab, Brief me, first sentence of the brief
PROD_C2 = (56.30, 62.10)      # "Hazards: ... concrete tilt-up walls."
BRIEF_FADE_END = 61.88        # 0.4 s fade-out ends here (before "Two stairs" at 61.91)


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    name = {"regular": "Inter_400Regular", "medium": "Inter_500Medium",
            "semibold": "Inter_600SemiBold", "bold": "Inter_700Bold",
            "italic": "Inter_400Regular_Italic"}[weight]
    return ImageFont.truetype(str(FONTS / f"{name}.ttf"), size)


def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode:
        sys.exit(f"command failed: {' '.join(map(str, cmd))[:400]}")
    return r


def probe_duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout
    return float(out.strip())


def ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def ease_io_cubic(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


# ---------------------------------------------------------------------------
# Frame writer: pipe RGB frames into ffmpeg
# ---------------------------------------------------------------------------
class Writer:
    def __init__(self, path: Path, crf: int = 12):
        self.p = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
             "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)

    def write(self, img):
        if isinstance(img, Image.Image):
            img = np.asarray(img.convert("RGB"))
        self.p.stdin.write(np.ascontiguousarray(img, dtype=np.uint8).tobytes())

    def close(self):
        self.p.stdin.close()
        if self.p.wait():
            sys.exit("ffmpeg writer failed")


def crop_zoom(src: Image.Image, cx: float, cy: float, cw: float) -> Image.Image:
    """Return a WxH frame showing a cw-wide (16:9) window centred on (cx, cy)."""
    ch = cw * H / W
    s = cw / W
    # affine maps output (x,y) -> input (a x + b y + c, d x + e y + f)
    return src.transform((W, H), Image.AFFINE,
                         (s, 0, cx - cw / 2, 0, s, cy - ch / 2),
                         resample=Image.BICUBIC)


def clamp_window(cx, cy, cw, sw, sh):
    ch = cw * H / W
    cx = min(max(cx, cw / 2), sw - cw / 2)
    cy = min(max(cy, ch / 2), sh - ch / 2)
    return cx, cy


# ---------------------------------------------------------------------------
# Segment renderers (stills -> mp4)
# ---------------------------------------------------------------------------
# Camera keyframes (t, cx, cy, crop width) in source pixels; each leg eased in/out.
# collage-timeline.png (1920x1080): Durham Oct 2026 clipping ~ (1330-1710, 645-735),
# Houston May 2013 NBC clipping ~ (212-592, 645-790), headline at y 660-705.
TIMELINE_KEYS = [
    (0.0, 1500, 640, 1060),   # open on Durham, Oct 2026 (newest, right end)
    (4.2, 1470, 645, 1000),   # slow drift while "Five weeks ago in Durham..."
    (9.6, 520, 650, 1120),    # "It keeps happening." pan right to left across 2026 -> 2013
    (14.4, 405, 700, 780),    # push in on the Houston 2013 headline
]
# collage.png fallback: full frame -> NBC Houston 2013 headline (985,70)-(1815,335)
COLLAGE_KEYS = [(0.0, 960, 540, 1920), (14.4, 1400, 250, 1000)]


def keyframe_cam(keys, t):
    for (t0, x0, y0, w0), (t1, x1, y1, w1) in zip(keys, keys[1:]):
        if t <= t1:
            u = (t - t0) / (t1 - t0)
            # linear drift on the first leg of the timeline, eased elsewhere
            e = ease_io_cubic(u)
            return x0 + (x1 - x0) * e, y0 + (y1 - y0) * e, w0 + (w1 - w0) * e
    return keys[-1][1:]


def render_fire(path: Path, dur: float):
    tl = PRESS / "collage-timeline.png"
    src = Image.open(tl if tl.exists() else PRESS / "collage.png").convert("RGB")
    keys = TIMELINE_KEYS if tl.exists() else COLLAGE_KEYS
    scale_t = dur / keys[-1][0]
    keys = [(k[0] * scale_t,) + tuple(k[1:]) for k in keys]
    n = round(dur * FPS)
    w = Writer(path)
    for i in range(n):
        cx, cy, cw = keyframe_cam(keys, i / FPS)
        cx, cy = clamp_window(cx, cy, cw, *src.size)
        w.write(crop_zoom(src, cx, cy, cw))
    w.close()


def render_clip(path: Path, dur: float, src: Path, marks: list[tuple[tuple, float]],
                width: int = 1800, top: int | None = None):
    """A press clipping on the dark press background, with yellow marker sweeps.
    marks: [((x0, y0, x1, y1) in source pixels, sweep start time), ...]"""
    clip = Image.open(src).convert("RGBA")
    scale = width / clip.width
    clip = clip.resize((width, round(clip.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), PRESS_BG)
    ox = (W - clip.width) // 2
    oy = top if top is not None else max(20, (860 - clip.height) // 2)
    canvas.paste(clip, (ox, oy), clip)
    base = np.asarray(canvas).astype(np.float32)
    rects = [((r[0] * scale + ox, r[1] * scale + oy, r[2] * scale + ox, r[3] * scale + oy), t0)
             for r, t0 in marks]
    yellow = np.array([255, 222, 89], np.float32) / 255.0
    allx = [v for (r, _) in rects for v in (r[0], r[2])] or [W / 2]
    ally = [v for (r, _) in rects for v in (r[1], r[3])] or [H / 2]
    fx, fy = (min(allx) + max(allx)) / 2, (min(ally) + max(ally)) / 2
    n = round(dur * FPS)
    sweep = 1.0
    w = Writer(path)
    for i in range(n):
        t = i / FPS
        frame = base.copy()
        for (hx0, hy0, hx1, hy1), t0 in rects:
            pr = ease((t - t0) / sweep)
            if pr <= 0:
                continue
            ys, ye, xs, xe = int(hy0), int(hy1), int(hx0), int(hx0 + (hx1 - hx0) * pr)
            if xe > xs:
                a = 0.55
                frame[ys:ye, xs:xe] = frame[ys:ye, xs:xe] * (1 - a + a * yellow)
        img = Image.fromarray(frame.clip(0, 255).astype(np.uint8))
        z = 1.0 + 0.035 * (t / dur)
        cx, cy = fx * 0.3 + W / 2 * 0.7, fy * 0.3 + H / 2 * 0.7
        w.write(crop_zoom(img, cx, cy, W / z))
    w.close()


def render_preplan(path: Path, dur: float):
    form = Image.open(PRESS / "clips" / "niosh-f2007-18-preplan-form.png").convert("RGBA")
    fw = 980
    form = form.resize((fw, round(form.height * fw / form.width)), Image.LANCZOS)
    fx = 150
    y0, y1 = 40, H - form.height - 20
    title_f, sub_f, small_f = font("semibold", 54), font("regular", 54), font("regular", 26)
    n = round(dur * FPS)
    w = Writer(path)
    for i in range(n):
        t = i / FPS
        img = Image.new("RGB", (W, H), PRESS_BG)
        y = y0 + (y1 - y0) * ease_io_cubic(t / dur)
        img.paste(form, (fx, round(y)), form)
        a = ease((t - 0.5) / 0.6)
        if a > 0:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            tx = fx + fw + 110
            d.text((tx, 330), "A real pre-plan.", font=title_f, fill=OFFWHITE + (int(255 * a),))
            d.text((tx, 400), "Charleston, 2006.", font=sub_f, fill=(176, 170, 160, int(255 * a)))
            d.line((tx, 500, tx + 90, 500), fill=(120, 116, 110, int(255 * a)), width=2)
            d.text((tx, 524), "Handwritten Charleston FD form,", font=small_f, fill=(150, 145, 137, int(255 * a)))
            d.text((tx, 560), "reproduced in NIOSH F2007-18.", font=small_f, fill=(150, 145, 137, int(255 * a)))
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
        w.write(img)
    w.close()


def wrap_px(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


WHO_ROWS = [
    ("Departments", "already pay $27K to $42K a year for pre-plan software, from 911 funds. "
                    "FEMA prevention grants cover it."),
    ("Cities", "the ISO grade credits pre-planning every commercial building, every year. "
               "Better grade, lower premiums."),
    ("How we sell", "about $10 to $15 per building per year, inside First Due, ImageTrend "
                    "and Tablet Command."),
]


def render_whopays(path: Path, dur: float, reveal_ts: list[float]):
    lf, bf, hf = font("semibold", 50), font("regular", 40), font("semibold", 30)
    x, max_w = 220, 1480
    rows = []
    y = 210
    for label, body in WHO_ROWS:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((x, y), label, font=lf, fill=INK + (255,))
        lines = wrap_px(body, bf, max_w)
        for k, ln in enumerate(lines):
            d.text((x, y + 70 + k * 54), ln, font=bf, fill=FG2 + (255,))
        h = 70 + len(lines) * 54
        rows.append(layer)
        y += h + 52
    base = Image.new("RGB", (W, H), OFFWHITE)
    d = ImageDraw.Draw(base)
    d.text((x, 130), "Who pays", font=hf, fill=ACCENT)
    n = round(dur * FPS)
    w = Writer(path)
    for i in range(n):
        t = i / FPS
        img = base.convert("RGBA")
        for layer, rt in zip(rows, reveal_ts):
            a = ease((t - rt) / 0.55)
            if a <= 0:
                continue
            dy = round(18 * (1 - a))
            l2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            l2.paste(layer, (0, dy))
            if a < 1:
                al = np.asarray(l2).copy()
                al[..., 3] = (al[..., 3] * a).astype(np.uint8)
                l2 = Image.fromarray(al)
            img = Image.alpha_composite(img, l2)
        w.write(img.convert("RGB"))
    w.close()


def render_imessage(path: Path, dur: float):
    src = Image.open(PRESS / "imessage" / "combined-real.png").convert("RGB")
    bgc = src.getpixel((20, 20))
    s = 0.86
    im = src.resize((round(W * s), round(H * s)), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), bgc)
    canvas.paste(im, ((W - im.width) // 2, 8))
    n = round(dur * FPS)
    w = Writer(path)
    for i in range(n):
        t = i / FPS
        z = 1.0 + 0.025 * t / dur
        w.write(crop_zoom(canvas, W / 2, H / 2 - 40, W / z))
    w.close()


def render_map(path: Path, dur: float):
    p = HERE / "assets" / "map-zoomed-out.png"
    if not p.exists():
        p = ROOT / "demo" / "screens-v3" / "wide" / "la-002-01-home.png"
    src = Image.open(p).convert("RGB")
    if src.size != (W, H):
        src = src.resize((W, round(src.height * W / src.width)), Image.LANCZOS)
        c = Image.new("RGB", (W, H), OFFWHITE)
        c.paste(src, (0, 0))
        src = c
    big, small = font("semibold", 44), font("regular", 30)
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    cx1, cy0, cy1 = 1860, 700, 860
    cx0 = cx1 - 72 - int(max(big.getlength("3,288 buildings indexed."), small.getlength("About 30 seconds each.")))
    d.rounded_rectangle((cx0 + 2, cy0 + 4, cx1 + 2, cy1 + 6), 10, fill=(0, 0, 0, 30))
    d.rounded_rectangle((cx0, cy0, cx1, cy1), 10, fill=(255, 255, 255, 255), outline=LINE + (255,), width=2)
    d.text((cx0 + 36, cy0 + 30), "3,288 buildings indexed.", font=big, fill=INK + (255,))
    d.text((cx0 + 36, cy0 + 96), "About 30 seconds each.", font=small, fill=FG3 + (255,))
    n = round(dur * FPS)
    w = Writer(path)
    for i in range(n):
        t = i / FPS
        z = 1.12 - 0.12 * ease_io_cubic(t / dur)
        img = crop_zoom(src, 1060 + 0 * z, 520, W / z).convert("RGBA")
        a = ease((t - 0.25) / 0.45)
        if a > 0:
            al = np.asarray(card).copy()
            al[..., 3] = (al[..., 3] * a).astype(np.uint8)
            img = Image.alpha_composite(img, Image.fromarray(al))
        w.write(img.convert("RGB"))
    w.close()


def cut_video(path: Path, ranges: list[tuple[float, float]], src: Path = DEMO, audio=False,
              fade=None):
    """Trim one or more ranges from src and concatenate (hard cut) into path."""
    parts, filt = [], []
    for k, (a, b) in enumerate(ranges):
        filt.append(f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p[v{k}]")
        if audio:
            filt.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,aresample={SR},"
                        f"afade=t=in:d=0.02,afade=t=out:st={b - a - 0.03:.3f}:d=0.03[a{k}]")
        parts.append(f"[v{k}]" + (f"[a{k}]" if audio else ""))
    n = len(ranges)
    filt.append("".join(parts) + f"concat=n={n}:v=1:a={1 if audio else 0}[v]" + ("[a0x]" if audio else ""))
    maps = ["-map", "[v]"]
    if audio:
        af = "[a0x]anull"
        if fade:
            af = f"[a0x]afade=t=out:st={fade[0]:.3f}:d={fade[1]:.3f}"
        filt.append(af + "[a]")
        maps += ["-map", "[a]", "-c:a", "pcm_s16le"]
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
         "-filter_complex", ";".join(filt), *maps, "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "12", str(path)])


# ---------------------------------------------------------------------------
# Narration (captions + synthetic voice)
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    seg: str            # anchor segment
    at: float           # anchor offset into that segment (earliest start)
    text: str           # caption text (from SCRIPT.md)
    speak: str = ""     # what `say` reads (pronunciation fixes)
    gap: float = 0.3    # min gap after the previous chunk
    start: float = 0.0
    dur: float = 0.0
    wav: Path | None = None


CHUNKS = [
    Chunk("fire", 0.5, "Five weeks ago in Durham, a roof came down on a firefighter searching a burning building."),
    Chunk("fire", 0, "It keeps happening.", gap=0.35),
    Chunk("fire", 0, "In Houston, in 2013, the roof came down twelve minutes after the first engine arrived.",
          "In Houston, in twenty thirteen, the roof came down twelve minutes after the first engine arrived.", gap=0.4),
    Chunk("fire", 0, "Four firefighters never came out.", gap=0.35),
    Chunk("finding", 0.6, "The state fire marshal's first finding was simple. There were no pre-fire plans for that building.", gap=0.6),
    Chunk("finding", 0, "No site diagram. No record of how it was built.", gap=0.35),
    Chunk("preplan", 0.4, "Plans like that come from an officer walking the building with a clipboard."),
    Chunk("preplan", 0, "Nobody can walk every building.", gap=0.3),
    Chunk("niosh", 0.3, "Last year a Georgia firefighter died in a warehouse where, NIOSH wrote, no pre-incident plan was available.",
          "Last year a Georgia firefighter died in a warehouse where, [[slnc 80]] Nyosh wrote, [[slnc 80]] no pre-incident plan was available.", gap=0.3),
    Chunk("niosh", 0, "The old ones sat in binders.", gap=0.3),
    Chunk("prodA", 0.3, "The facts are already out there, in data nobody hands to the fire service.", gap=0.3),
    Chunk("prodA", 0, "Here's a warehouse in east LA.", "Here's a warehouse in east L.A.", gap=0.25),
    Chunk("prodA", 6.8, "Our agent sends three analysts out at once.", gap=0.3),
    Chunk("prodA", 10.6, "CoStar knows what's inside.", "Co-Star knows what's inside."),
    Chunk("prodA", 0, "A 1969 concrete tilt-up, a health-and-beauty wholesaler, eleven dock doors.",
          "A nineteen sixty-nine concrete tilt-up, a health and beauty wholesaler, eleven dock doors.", gap=0.25),
    Chunk("prodA", 18.6, "The Matterport scan shows a steel mezzanine stair and pallets stacked on the floor."),
    Chunk("prodA", 24.6, "Vexcel shows solar across the roof, the walls a ladder truck can actually reach, and where to park it."),
    Chunk("prodA", 31.0, "Every line cites a source. Hydrants it can't see, so it says verify on site, never a guess."),
    Chunk("prodA", 36.4, "Nothing goes to a crew until an officer signs off.", gap=0.3),
    Chunk("imsg", 0.2, "Even from a text.", gap=0.2),
    Chunk("whopays", 0.75, "Fire departments already pay for pre-planning software, and FEMA prevention grants fund it.",
          "Fire departments already pay for pre-planning software, and Fema prevention grants fund it."),
    Chunk("whopays", 0, "A city's insurance grade rewards pre-planning every commercial building, every year.", gap=0.45),
    Chunk("whopays", 0, "With our draft waiting, the walk becomes a check.", gap=0.45),
    Chunk("whopays", 0, "We sell per building, inside the software departments already use.", gap=0.45),
    Chunk("map", 0.0, "We've already indexed 3,288 buildings in Houston and LA.",
          "We've already indexed thirty-two eighty-eight buildings in Houston and L.A.", gap=0.35),
    Chunk("blowout", 0.0, "The next crew should know the building before they're inside it.", gap=0.2),
]
WHO_REVEAL_CHUNKS = [20, 21, 23]  # indices into CHUNKS that reveal rows 1..3


def synth(chunks: list[Chunk]):
    d = BUILD / "say"
    d.mkdir(parents=True, exist_ok=True)
    for k, c in enumerate(chunks):
        speak = c.speak or c.text
        key = f"{VOICE}|{SAY_RATE}|{speak}"
        wav = d / f"c{k:02d}.wav"
        meta = d / f"c{k:02d}.json"
        if not (wav.exists() and meta.exists() and json.loads(meta.read_text()).get("key") == key):
            aiff = d / f"c{k:02d}.aiff"
            run(["say", "-v", VOICE, "-r", str(SAY_RATE), "-o", str(aiff), speak])
            # trim leading/trailing silence so timing is tight
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(aiff),
                 "-af", "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        "silenceremove=start_periods=1:start_threshold=-50dB,areverse,"
                        f"aresample={SR}", "-ac", "1", str(wav)])
            meta.write_text(json.dumps({"key": key}))
        c.wav = wav
        c.dur = probe_duration(wav)


def read_wav(p: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(p),
                          "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def write_wav(p: Path, x: np.ndarray):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "s16le",
                    "-ar", str(SR), "-ac", "1", "-i", "-", str(p)], input=pcm, check=True)


def rms_db(x):
    x = x[np.abs(x) > 1e-3]
    return 20 * math.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-9) if len(x) else -99


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------
CAP_F = None
CAP_MAXW = 1440
CAP_BOTTOM = 1000  # box bottom (keeps the product's docked Approve bar at y>1020 visible)


def caption_lines(text: str) -> list[str]:
    lines = wrap_px(text, CAP_F, CAP_MAXW)
    if len(lines) == 2:  # balance two lines
        words = text.split()
        best = None
        for k in range(1, len(words)):
            a, b = " ".join(words[:k]), " ".join(words[k:])
            wa, wb = CAP_F.getlength(a), CAP_F.getlength(b)
            if max(wa, wb) <= CAP_MAXW:
                score = abs(wa - wb)
                if best is None or score < best[0]:
                    best = (score, [a, b])
        if best:
            lines = best[1]
    assert len(lines) <= 2, f"caption too long: {text}"
    return lines


def render_caption(text: str) -> tuple[np.ndarray, int, int]:
    lines = caption_lines(text)
    lh = 56
    padx, pady = 34, 18
    tw = max(CAP_F.getlength(l) for l in lines)
    bw, bh = int(tw + 2 * padx), int(lh * len(lines) + 2 * pady - 6)
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), 16, fill=(14, 16, 19, 168))
    for k, ln in enumerate(lines):
        lw = CAP_F.getlength(ln)
        d.text(((bw - lw) / 2, pady + k * lh - 2), ln, font=CAP_F, fill=(255, 255, 255, 255))
    x = (W - bw) // 2
    y = CAP_BOTTOM - bh
    return np.asarray(img), x, y


def render_label(text: str) -> tuple[np.ndarray, int, int]:
    f = font("medium", 30)
    tw = f.getlength(text)
    bw, bh = int(tw + 40 + 34), 58
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), 10, fill=OFFWHITE + (240,))
    # small speaker glyph
    cx, cy = 26, bh // 2
    d.polygon([(cx - 8, cy - 5), (cx - 3, cy - 5), (cx + 4, cy - 11), (cx + 4, cy + 11),
               (cx - 3, cy + 5), (cx - 8, cy + 5)], fill=ACCENT)
    d.text((44, bh / 2 - 19), text, font=f, fill=INK)
    return np.asarray(img), 1100, 790


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
@dataclass
class Seg:
    name: str
    dur: float
    xf: float = XF          # cross-fade INTO this segment
    path: Path | None = None
    start: float = 0.0


def main():
    global CAP_F
    CAP_F = font("medium", 42)
    BUILD.mkdir(exist_ok=True)
    sheet = "--sheet" in sys.argv

    c_dur = (PROD_C1[1] - PROD_C1[0]) + (PROD_C2[1] - PROD_C2[0])
    segs = [
        Seg("fire", 14.4, xf=0),
        Seg("finding", 11.0),
        Seg("preplan", 6.6),
        Seg("niosh", 10.6),
        Seg("prodA", PROD_A[1] - PROD_A[0]),
        Seg("prodB1", PROD_B1[1] - PROD_B1[0]),
        Seg("imsg", 3.0),
        Seg("prodB2", PROD_B2[1] - PROD_B2[0], xf=0.3),
        Seg("prodC", c_dur, xf=0.3),
        Seg("whopays", 18.0),   # auto-fit to its narration below
        Seg("map", 3.8),
        Seg("blowout", probe_duration(BLOWOUT)),
    ]
    synth(CHUNKS)

    def layout():
        t = 0.0
        for k, sg in enumerate(segs):
            sg.start = t - (sg.xf if k else 0)
            t = sg.start + sg.dur
        prev_end = 0.0
        for c in CHUNKS:
            c.start = max(S[c.seg].start + c.at, prev_end + c.gap)
            prev_end = c.start + c.dur
        return t

    S = {sg.name: sg for sg in segs}
    layout()
    last_who = [c for c in CHUNKS if c.seg == "whopays"][-1]
    S["whopays"].dur = last_who.start + last_who.dur + 0.6 - S["whopays"].start
    total = layout()
    words = sum(len(c.text.split()) for c in CHUNKS)
    speech = sum(c.dur for c in CHUNKS)
    print(f"timeline {total:.2f}s; narration {words} words, {speech:.1f}s speech "
          f"= {words / speech * 60:.0f} wpm ({VOICE}, rate {SAY_RATE})")
    for c in CHUNKS:
        print(f"  {c.start:6.2f}-{c.start + c.dur:6.2f}  [{c.seg}] {c.text[:70]}")
    brief_start = S["prodC"].start + (47.23 - PROD_C1[0])
    brief_end = S["prodC"].start + (PROD_C1[1] - PROD_C1[0]) + (BRIEF_FADE_END - PROD_C2[0])
    print(f"voice brief plays {brief_start:.2f}-{brief_end:.2f}")
    for c in CHUNKS:
        if c.start < brief_end and c.start + c.dur > S["prodC"].start:
            print(f"  WARNING: narration overlaps the in-cab segment: {c.text[:50]}")
    title_t = S["blowout"].start + 3.85
    if CHUNKS[-1].start + CHUNKS[-1].dur > title_t:
        print("  WARNING: last line runs into the title card")

    # caption display windows
    caps = []
    for k, c in enumerate(CHUNKS):
        a = c.start - 0.12
        b = c.start + c.dur + 0.35
        if k + 1 < len(CHUNKS):
            b = min(b, CHUNKS[k + 1].start - 0.2)
        if c.seg == "blowout":
            b = min(b, title_t - 0.1)
        caps.append((a, b, c.text))

    # --- render segments ---
    seg_dir = BUILD / "segments"
    seg_dir.mkdir(exist_ok=True)
    for s in segs:
        s.path = seg_dir / f"{s.name}.mp4" if s.name != "prodC" else seg_dir / "prodC.mov"
    print("rendering segments...")
    render_fire(S["fire"].path, S["fire"].dur)
    g1 = CHUNKS[4]
    # "There were no pre-fire plans" begins after "The state fire marshal's first finding was simple."
    fs = S["finding"].start
    render_clip(S["finding"].path, S["finding"].dur, PRESS / "clips" / "sfmo-fy13-08-finding1.png",
                [((516, 188, 888, 254), g1.start - fs + g1.dur * 0.50)], top=170)
    render_preplan(S["preplan"].path, S["preplan"].dur)
    t3, t4 = CHUNKS[8], CHUNKS[9]
    ns = S["niosh"].start
    render_clip(S["niosh"].path, S["niosh"].dur, PRESS / "clips" / "recent-niosh-f2025-09-preplan-2026.png",
                [((426, 560, 1060, 612), t3.start - ns + t3.dur * 0.60),
                 ((1416, 663, 1724, 714), t4.start - ns + t4.dur * 0.35)], width=1640, top=40)
    render_imessage(S["imsg"].path, S["imsg"].dur)
    render_whopays(S["whopays"].path, S["whopays"].dur,
                   [CHUNKS[i].start - S["whopays"].start for i in WHO_REVEAL_CHUNKS])
    render_map(S["map"].path, S["map"].dur)
    cut_video(S["prodA"].path, [PROD_A])
    cut_video(S["prodB1"].path, [PROD_B1])
    cut_video(S["prodB2"].path, [PROD_B2])
    c1 = PROD_C1[1] - PROD_C1[0]
    cut_video(S["prodC"].path, [PROD_C1, PROD_C2], audio=True,
              fade=(c1 + BRIEF_FADE_END - PROD_C2[0] - 0.4, 0.4))
    cut_video(S["blowout"].path, [(0, S["blowout"].dur)], src=BLOWOUT)

    # --- base video: cross-fade chain ---
    print("assembling base video...")
    base = BUILD / "base.mp4"
    inputs, filt = [], []
    for k, s in enumerate(segs):
        inputs += ["-i", str(s.path)]
        filt.append(f"[{k}:v]settb=AVTB,fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[s{k}]")
    cur, acc = "[s0]", segs[0].dur
    for k in range(1, len(segs)):
        s = segs[k]
        off = acc - s.xf
        out = f"[x{k}]"
        if s.xf > 0:
            filt.append(f"{cur}[s{k}]xfade=transition=fade:duration={s.xf}:offset={off:.4f}{out}")
        else:
            filt.append(f"{cur}[s{k}]concat=n=2:v=1:a=0{out}")
        cur, acc = out, off + s.dur
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex",
         ";".join(filt), "-map", cur, "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
         "-pix_fmt", "yuv420p", str(base)])
    print(f"  base duration {probe_duration(base):.2f}s (expected {total:.2f})")

    # --- audio ---
    n_samp = int(math.ceil(total * SR)) + SR
    brief = np.zeros(n_samp, np.float32)
    b = read_wav(S["prodC"].path)
    i0 = int(S["prodC"].start * SR)
    brief[i0:i0 + len(b)] = b[: n_samp - i0]
    brief *= 10 ** ((-19.0 - rms_db(b)) / 20)  # speech RMS ~ -19 dBFS
    narr = np.zeros(n_samp, np.float32)
    for c in CHUNKS:
        x = read_wav(c.wav)
        x *= 10 ** ((-19.0 - rms_db(x)) / 20)
        j = int(c.start * SR)
        narr[j:j + len(x)] += x[: n_samp - j]
    # duck the brief wherever narration is active (they shouldn't overlap; belt and braces)
    env = np.convolve(np.abs(narr), np.ones(int(0.05 * SR)) / (0.05 * SR), mode="same")
    duck = np.where(env > 0.003, 10 ** (-14 / 20), 1.0).astype(np.float32)
    duck = np.convolve(duck, np.ones(int(0.15 * SR)) / (0.15 * SR), mode="same").astype(np.float32)
    n_out = int(round(total * SR))
    a_track = brief[:n_out]
    b_track = (brief * duck + narr)[:n_out]
    peak = max(np.abs(b_track).max(), np.abs(a_track).max())
    if peak > 0.95:
        a_track, b_track = a_track * 0.95 / peak, b_track * 0.95 / peak
    wav_a, wav_b = BUILD / "audio_a.wav", BUILD / "audio_b.wav"
    write_wav(wav_a, a_track)
    write_wav(wav_b, b_track)

    # --- captions composite + final encode ---
    print("burning captions...")
    cap_imgs = [render_caption(txt) for _, _, txt in caps]
    label = render_label("Voice brief, played in the cab")
    lab_a, lab_b = S["prodC"].start + 0.5, min(brief_end, S["whopays"].start) - 0.05
    dec = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(base),
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    video_only = BUILD / "captioned.mp4"
    enc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video_only)],
        stdin=subprocess.PIPE)
    fsz = W * H * 3

    def comp(frame, rgba, x, y, a):
        h, w = rgba.shape[:2]
        al = rgba[..., 3:4].astype(np.float32) / 255.0 * a
        reg = frame[y:y + h, x:x + w].astype(np.float32)
        frame[y:y + h, x:x + w] = (reg * (1 - al) + rgba[..., :3] * al).astype(np.uint8)

    fi = 0
    while True:
        buf = dec.stdout.read(fsz)
        if len(buf) < fsz:
            break
        frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        tt = fi / FPS
        for (a, b2, _), (img, x, y) in zip(caps, cap_imgs):
            if a <= tt <= b2:
                al = min(1.0, (tt - a) / 0.12, (b2 - tt) / 0.12)
                comp(frame, img, x, y, max(0.0, al))
        if lab_a <= tt <= lab_b:
            al = min(1.0, (tt - lab_a) / 0.25, (lab_b - tt) / 0.25)
            comp(frame, label[0], label[1], label[2], max(0.0, al))
        enc.stdin.write(frame.tobytes())
        fi += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()

    for out, wav in ((OUT_A, wav_a), (OUT_B, wav_b)):
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_only), "-i", str(wav),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest", "-movflags", "+faststart",
             "-metadata", "title=FirstIn pitch (2 min)" + (" - synthetic narration fallback" if out == OUT_B else ""),
             str(out)])

    with open(OUT_SRT, "w") as f:
        for k, (a, b2, txt) in enumerate(caps, 1):
            f.write(f"{k}\n{srt_time(max(0, a))} --> {srt_time(b2)}\n{txt}\n\n")

    (BUILD / "timeline.json").write_text(json.dumps({
        "total": total,
        "segments": [{"name": s.name, "start": round(s.start, 2), "end": round(s.start + s.dur, 2)} for s in segs],
        "captions": [{"start": round(a, 2), "end": round(b2, 2), "text": t_} for a, b2, t_ in caps],
        "brief": [round(brief_start, 2), round(brief_end, 2)],
        "voice": VOICE, "rate": SAY_RATE,
        "timeline_collage": (PRESS / "collage-timeline.png").exists(),
    }, indent=1))
    for out in (OUT_A, OUT_B):
        print(f"wrote {out.relative_to(ROOT)}  {probe_duration(out):.2f}s")
    print(f"wrote {OUT_SRT.relative_to(ROOT)}  ({len(caps)} cues)")

    if sheet:
        contact_sheet(OUT_A)


def contact_sheet(src: Path):
    """Frames every 2 s, two sheets, each frame stamped with its time."""
    d = BUILD / "sheet"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir()
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(src), "-vf",
         "fps=1/2,scale=480:-1", str(d / "f%03d.png")])
    frames = sorted(d.glob("f*.png"))
    f = font("semibold", 22)
    per = 32
    for si in range(0, len(frames), per):
        group = frames[si:si + per]
        cols, rows = 4, math.ceil(len(group) / 4)
        sheet = Image.new("RGB", (cols * 480, rows * 270), (0, 0, 0))
        for k, p in enumerate(group):
            im = Image.open(p).convert("RGB")
            dd = ImageDraw.Draw(im)
            t = (si + k) * 2
            dd.rectangle((0, 0, 78, 30), fill=(0, 0, 0))
            dd.text((6, 3), f"{t // 60}:{t % 60:02d}", font=f, fill=(255, 220, 0))
            sheet.paste(im, ((k % cols) * 480, (k // cols) * 270))
        out = BUILD / f"contact-{si // per + 1}.png"
        sheet.save(out)
        print(f"contact sheet {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
