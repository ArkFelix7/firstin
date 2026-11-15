import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
D = Path("/Users/aarya/dev_all/hack-princton/firstin/demo")
OUT = D / "devpost-gallery"; OUT.mkdir(exist_ok=True)
F = D / "video/fonts"
W, H = 1800, 1200
BG, INK, SUB = (244, 245, 247), (22, 25, 29), (90, 97, 107)
title_f = ImageFont.truetype(str(F / "Inter_600SemiBold.ttf"), 38)
sub_f = ImageFont.truetype(str(F / "Inter_400Regular.ttf"), 27)
items = [
 ("screens-v3/la-002-03-awaiting-approval.png", "A cited pre-plan, ready for officer approval", "Every field names its source (CoStar, Vexcel, Matterport) or says Verify on site. 1601 Perrino Pl, Los Angeles."),
 ("screens-v3/la-002-01-home.png", "Pick any of 3,288 buildings in Houston and LA", "Clustered map of the indexed CoStar buildings; prepared buildings are ready in about 30 seconds."),
 ("screens-v3/la-002-02-plan-running.png", "A deepagents planner with three analysts in parallel", "Live trace: NFPA 1660 to-dos, subagents, tool calls and evidence files as they arrive."),
 ("screens-v3/la-002-04-evidence-matterport-360.png", "Interior evidence from Matterport 360° scans", "The vision model found the stair in the panorama; the box shows where."),
 ("screens-v3/la-002-05-evidence-vexcel.png", "Roof and surroundings from Vexcel aerial imagery", "Click any fact to open the tile it came from."),
 ("screens-v3/la-002-11-access-plan.png", "Access plan from the measured footprint", "Ladder walls, a validated staging area and doors found in the angled aerial photos."),
 ("screens-v3/la-002-12-access-entry-oblique.png", "Doors found in oblique aerial photos", "Each entry links back to the oblique image and the spot where it was seen."),
 ("screens-v3/la-002-06-evidence-hazard.png", "Hazards with the facts they came from", "Rule table plus model reasoning; each hazard cites the tenant or construction record behind it."),
 ("screens-v3/la-002-07-verify-on-site.png", "Nothing is guessed", "Fields with no source are marked Verify on site instead of filled in."),
 ("screens-v3/la-002-08-edit-mode.png", "The officer edits before approving", "Edits are saved as officer-cited facts; the agent's publish call waits for this decision."),
 ("press/imessage/combined-real.png", "Approve or ask by iMessage (Photon)", "Real screenshots: an approval request, and a question answered only from the plan."),
 ("screens-v3/la-002-10-incab.png", "In-cab display with a 20-second spoken brief", "Top hazards, stairs and roof access. Brief me plays the voice brief; crews can ask questions."),
 ("screens-v3/la-003-11-access-high-rise.png", "Works on high-rises too", "At about 87 m the roof is beyond aerial ladder reach, so the plan says so first: use interior stairs. Green walls are apparatus set-up positions."),
 ("screens-v3/hou-001-09-published.png", "Published: PDF, voice brief and in-cab", "Approval renders the one-page sheet and audio and pushes the plan to the engine."),
 ("press/collage-timeline.png", "Why: missing building information keeps showing up in fire investigations", "News and investigation headlines with attribution (sources in demo/press/SOURCES.md)."),
]
def wrap(d, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw: cur = t
        else: lines.append(cur); cur = w
    return lines + ([cur] if cur else [])
CROP = {4, 5, 6, 7, 8, 9, 10, 13, 14}
caps = []
for i, (src, title, sub) in enumerate(items, 1):
    im = Image.open(D / src).convert("RGB")
    if i in CROP:  # drop the agent-run column so the plan + evidence are readable
        im = im.crop((300, 50, im.width, im.height))
    cap_h = 170
    box_w, box_h = W - 120, H - cap_h - 60
    s = min(box_w / im.width, box_h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    c = Image.new("RGB", (W, H), BG)
    x, y = (W - im.width) // 2, 50 + (box_h - im.height) // 2
    sh = Image.new("RGB", (im.width + 2, im.height + 2), (214, 218, 224)); c.paste(sh, (x - 1, y - 1))
    c.paste(im, (x, y))
    d = ImageDraw.Draw(c)
    ty = H - cap_h + 10
    cx = max(60, x)
    d.text((cx, ty), title, font=title_f, fill=INK)
    for j, line in enumerate(wrap(d, sub, sub_f, W - 2 * cx)[:2]):
        d.text((cx, ty + 56 + j * 38), line, font=sub_f, fill=SUB)
    name = f"{i:02d}-{Path(src).stem}.jpg"
    c.save(OUT / name, quality=90, optimize=True)
    caps.append(f"{name}\t{title}. {sub}")
(OUT / "CAPTIONS.txt").write_text("\n".join(caps) + "\n")
print("ok", len(items))
