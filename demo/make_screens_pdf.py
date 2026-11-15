"""Build a captioned PDF of the demo screenshots.

Usage (from firstin/): agent/.venv/bin/python demo/make_screens_pdf.py
Output: demo/FirstIn-demo-screens.pdf
"""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "FirstIn-demo-screens.pdf"

STEPS = {
    "01-home": ("Pick a building",
                "The officer selects 1601 Perrino Pl on the map. The table shows which data layers exist for each building, and the detail panel shows the aerial tile, CoStar facts and capture dates."),
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
    "11-incab-standby": ("In-cab standby",
                         "Before any plan is approved, the unit stands by."),
}

SECTIONS = [
    ("Live run: 1601 Perrino Pl, Los Angeles (real agent, all three data layers)", "screens-v3", "la-002-"),
    ("Live run: The Ion, 4201 Main St, Houston (real agent)", "screens-v3", "hou-001-"),
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
        files = sorted((ROOT / folder).glob(f"{prefix}*.png"))
        if not files:
            continue
        for f in files:
            key = f.stem[len(prefix):]
            head, sub = STEPS.get(key, (key.replace("-", " ").title(), ""))
            n += 1
            c.setFillColor(BG); c.rect(0, 0, W, IMG_H + BAND, fill=1, stroke=0)
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
