"""Build a captioned PDF of the demo screenshots.

Usage (from firstin/): agent/.venv/bin/python demo/make_screens_pdf.py
Output: demo/FirstIn-demo-screens.pdf
"""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "FirstIn-demo-screens.pdf"

STEPS = {
    "01-home": ("Pick a building",
                "The officer selects the building on the map. The table shows which data layers exist for each building, and the detail panel shows the aerial tile, CoStar facts and capture dates."),
    "02-plan-running": ("Agent at work",
                        "The deepagents planner splits the job into NFPA 1660 sections and runs the CoStar, aerial and interior analysts in parallel. Steps, subagent timings and tool calls stream live."),
    "03-awaiting-approval": ("Cited pre-plan, awaiting review",
                             "Every field shows its source and confidence. Hazards are ranked first. CoStar and Vexcel heights are cross-checked. Nothing is published until an officer approves."),
    "04-evidence-matterport-360": ("Interior evidence: Matterport 360",
                                   "Selecting a field opens its source. The vision model found the stair in the Matterport panorama, and the outline shows exactly where."),
    "05-evidence-vexcel": ("Aerial evidence: Vexcel",
                           "Roof access, staging and exposures come from the Vexcel orthomosaic. The selected detection is outlined on the tile, with the citation below it."),
    "06-evidence-hazard": ("Hazards with an evidence chain",
                           "Inferred hazards list their tactics, their basis and the cited facts they were derived from. Each link opens the underlying source."),
    "07-verify-on-site": ("Verify on site",
                          "Fields with no citable source are labelled Verify on site and collected into a walk-through checklist. The agent never guesses them."),
    "08-edit-mode": ("Officer edits",
                     "The officer can correct any field before approving. Edited values are cited to the officer."),
    "09-published": ("Approved and published",
                     "On approval FirstIn records who approved and when, renders a one-page PDF and a short voice brief, and publishes to the unit."),
    "10-incab": ("In-cab display",
                 "Engine 12's screen shows the approved plan: top hazards, stairs and roof access. Brief me plays the voice brief en route."),
    "11-access-plan": ("Access plan",
                       "Ladder-access walls in green, the staging area in blue and numbered entries, drawn on the Vexcel context tile at full resolution. Selecting a wall shows its reason and confidence."),
    "12-access-entry-oblique": ("Entry evidence in the oblique",
                                "Selecting an entry zooms the Vexcel oblique image to the door the agent found. Positions on the plan are approximate, the oblique is the evidence."),
    "11-access-high-rise": ("High-rise access",
                            "For towers beyond aerial ladder reach the plan says so first: use interior stairs. Green walls become apparatus set-up positions."),
    "11-incab-standby": ("In-cab standby",
                         "Before any plan is approved, the unit stands by."),
}

SECTIONS = [
    ("1601 Perrino Pl, Los Angeles: one complete run (real agent, all three data layers)", "screens-v3", [
        ("la-002-01-home.png", *STEPS["01-home"], False),
        ("la-002-02-plan-running.png", *STEPS["02-plan-running"], False),
        ("la-002-03-awaiting-approval.png", *STEPS["03-awaiting-approval"], False),
        ("la-002-04-evidence-matterport-360.png", *STEPS["04-evidence-matterport-360"], False),
        ("la-002-11-access-plan.png", *STEPS["11-access-plan"], False),
        ("la-002-12-access-entry-oblique.png", *STEPS["12-access-entry-oblique"], False),
        ("la-002-06-evidence-hazard.png", *STEPS["06-evidence-hazard"], False),
        ("la-002-07-verify-on-site.png", *STEPS["07-verify-on-site"], False),
        ("la-002-08-edit-mode.png", *STEPS["08-edit-mode"], False),
        ("la-002-09-published.png", *STEPS["09-published"], False),
        ("la-002-10-incab.png", *STEPS["10-incab"], False),
    ]),
    ("Officer approval by iMessage (Photon)", "press/imessage", [
        ("combined-real.png", "Officer approval by iMessage",
         "Real screenshots from the officer's iPhone. The approval request arrives through Photon, and the officer can approve, reject or ask a question. Asked where the exit is, FirstIn answered only from the plan.", True),
        ("approve.png", "Approved by reply",
         "The officer replied APPROVE and the plan went live on Engine 12 (recreated from the Photon message log).", True),
    ]),
    ("Two more buildings: what changes from building to building", "screens-v3", [
        ("hou-001-03-awaiting-approval.png", "The Ion, Houston: hazards from the tenant list",
         "CoStar lists 26 tenants. A cafe, three bars and a robotics company become distinct, merged hazards, each citing the tenant records it came from.", False),
        ("hou-001-10-incab.png", "The Ion, Houston: no guessing",
         "CoStar has no construction type for this redeveloped building, so the cab shows Verify on site instead of inferring it from the year.", False),
        ("la-003-11-access-high-rise.png", "10940 Wilshire, Los Angeles: a high-rise",
         "At about 87 m the roof is beyond aerial ladder reach, and the plan says so first: use interior stairs. Green walls are apparatus set-up positions.", False),
        ("la-003-10-incab.png", "10940 Wilshire, Los Angeles: in the cab",
         "24 stories, steel, 1988. Top hazards: assembly occupancy on floor 1, roof damage seen from the air, and coworking floors. Roof access reads high-rise, interior stairs.", False),
    ]),
]

BG = HexColor("#ffffff")
ACCENT = HexColor("#2554c7")
FG = HexColor("#16191d")
MUTED = HexColor("#4a525c")
LINE = HexColor("#e3e6ea")


def wrap(c, text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if c.stringWidth(t, font, size) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def main():
    W, IMG_H, BAND = 1440, 900, 150
    c = canvas.Canvas(str(OUT), pagesize=(W, IMG_H + BAND))
    c.setTitle("FirstIn: demo screenshots")

    # cover
    c.setFillColor(BG); c.rect(0, 0, W, IMG_H + BAND, fill=1, stroke=0)
    c.setFillColor(FG); c.setFont("Helvetica-Bold", 72); c.drawString(100, 640, "FirstIn")
    c.setFillColor(FG); c.setFont("Helvetica", 34)
    c.drawString(100, 580, "Know the building before you're inside it.")
    c.setFillColor(MUTED); c.setFont("Helvetica", 22)
    for i, line in enumerate([
        "Cited NFPA 1660 pre-incident plans from CoStar, Vexcel and Matterport,",
        "approved by an officer and briefed to the crew in the cab.",
        "HackPrinceton Fall 2026. Demo screenshots.",
    ]):
        c.drawString(100, 510 - i * 34, line)
    c.showPage()

    n = 0
    for title, folder, prefix in SECTIONS:
        if isinstance(prefix, list):  # explicit images with captions, fitted proportionally
            pages = [(ROOT / folder / name, head, sub, fit) for name, head, sub, fit in prefix
                     if (ROOT / folder / name).exists()]
        else:
            pages = []
            for f in sorted((ROOT / folder).glob(f"{prefix}*.png")):
                key = f.stem[len(prefix):]
                head, sub = STEPS.get(key, (key.replace("-", " ").title(), ""))
                pages.append((f, head, sub, False))
        for f, head, sub, fit in pages:
            n += 1
            c.setFillColor(BG); c.rect(0, 0, W, IMG_H + BAND, fill=1, stroke=0)
            if fit:
                iw, ih = ImageReader(str(f)).getSize()
                k = min(W / iw, IMG_H / ih)
                dw, dh = iw * k, ih * k
                c.drawImage(str(f), (W - dw) / 2, BAND + (IMG_H - dh) / 2, width=dw, height=dh, mask="auto")
            else:
                c.drawImage(str(f), 0, BAND, width=W, height=IMG_H)
            c.setStrokeColor(LINE); c.line(0, BAND, W, BAND)
            c.setFillColor(MUTED); c.setFont("Helvetica", 14)
            c.drawString(40, BAND - 30, title)
            c.drawRightString(W - 40, BAND - 30, f"{n}")
            c.setFillColor(FG); c.setFont("Helvetica-Bold", 28)
            c.drawString(40, BAND - 66, head)
            c.setFillColor(MUTED); c.setFont("Helvetica", 18)
            for i, line in enumerate(wrap(c, sub, "Helvetica", 18, W - 80)[:3]):
                c.drawString(40, BAND - 96 - i * 22, line)
            c.showPage()
    c.save()
    print(f"wrote {OUT} ({n} screenshots)")


if __name__ == "__main__":
    main()
