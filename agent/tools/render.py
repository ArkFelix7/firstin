"""Render an approved plan: HTML tactical sheet, one-page PDF (reportlab), and TTS voice brief."""
from __future__ import annotations

import html
import json
import shutil
import subprocess
from pathlib import Path

import logging

from .. import config

log = logging.getLogger("firstin.render")
from ..tools.validator import VERIFY


def _out_dir(plan: dict) -> Path:
    d = config.OUT_DIR / str(plan.get("plan_id") or "unknown")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _val(node):
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def cite_str(c) -> str:
    if not c:
        return "no source"
    src = c.get("src", "?")
    cid = c.get("id") or ""
    if src == "inference":
        cid = ", ".join(c.get("from") or []) or cid
    conf = c.get("conf")
    cid = str(cid)
    if len(cid) > 30:
        cid = "…" + cid[-28:]
    s = f"{src}:{cid}"
    if conf is not None:
        s += f" ({float(conf):.2f})"
    if c.get("bbox"):
        s += " bbox"
    return s


def _rows(plan: dict) -> list[tuple[str, str, str]]:
    """(label, value, citation) rows for the tactical sheet."""
    b = plan.get("building", {})
    rows = []

    def add(label, node):
        if isinstance(node, dict) and "value" in node:
            rows.append((label, str(node["value"]), cite_str(node.get("cite")) if node["value"] != VERIFY else "VERIFY ON SITE"))

    for k, lab in (("stories", "Stories"), ("height_ft", "Height (ft)"), ("year_built", "Year built"), ("sq_ft", "Area (sf)"),
                   ("building_class", "Class"), ("property_type", "Type"), ("construction", "Construction"),
                   ("sprinklers", "Sprinklers"), ("power", "Electrical service"), ("loading_docks", "Loading docks"),
                   ("roof", "Roof")):
        add(lab, b.get(k))
    occ = plan.get("occupancy", {})
    add("Occupant load", occ.get("occupant_load_estimate"))
    acc = plan.get("access", {})
    for k, lab in (("roof_access", "Roof access"), ("staging", "Staging"), ("hydrants", "Hydrants"),
                   ("access_roads", "Access roads"), ("entries_summary", "Entries/exits")):
        add(lab, acc.get(k))
    it = plan.get("interior", {})
    st = it.get("stairwells")
    if isinstance(st, list):
        for s in st:
            rows.append(("Stairwell", s.get("loc", "?") + (", STANDPIPE" if s.get("standpipe") else ""),
                         cite_str(s.get("cite")) if not s.get("verify_on_site") else "VERIFY ON SITE"))
    else:
        add("Stairwells", st)
    add("Elevators", it.get("elevators"))
    for k, node in (it.get("utilities") or {}).items():
        add(k.replace("_", " ").title(), node)
    for k, node in (it.get("fire_protection") or {}).items():
        add(k.replace("_", " ").upper() if k == "fdc" else k.replace("_", " ").title(), node)
    return rows


def _tenants(plan) -> list[tuple[str, str]]:
    t = _val((plan.get("occupancy") or {}).get("tenants"))
    if not isinstance(t, list):
        return []
    return [(f"{x.get('name')}: {x.get('use') or ''}" + (f" (fl {x['floor']})" if x.get("floor") else ""),
             cite_str(x.get("cite"))) for x in t[:8]]


def _hazards(plan) -> list[tuple[str, str]]:
    return [(f"{h.get('type')}" + (f" ({h.get('location')})" if h.get("location") else "") + "" + (f" [{h.get('reason')}]" if h.get("reason") else ""),
             cite_str(h.get("cite"))) for h in (plan.get("hazards") or []) if isinstance(h, dict)]


def _exposures(plan) -> list[tuple[str, str]]:
    ex = plan.get("exposures")
    if not isinstance(ex, list):
        return []
    return [(f"{e.get('side')}: {e.get('desc')}", cite_str(e.get("cite"))) for e in ex]


def _local_image(url_or_path: str | None) -> Path | None:
    if not url_or_path:
        return None
    p = Path(url_or_path)
    if p.exists():
        return p
    for prefix, base in (("/static/cache/", config.CACHE_DIR), ("/static/out/", config.OUT_DIR)):
        if str(url_or_path).startswith(prefix):
            q = base / str(url_or_path)[len(prefix):]
            if q.exists():
                return q
    return None


def render_html(plan: dict) -> str:
    d = _out_dir(plan)
    e = html.escape
    b = plan.get("building", {})
    media = plan.get("media") or {}
    aerial = media.get("aerial_url")
    panos = media.get("pano_urls") or []

    def tr(rows):
        return "".join(
            f"<tr class='{'verify' if c == 'VERIFY ON SITE' or v == VERIFY else ''}'><th>{e(l)}</th><td>{e(v)}</td><td class='cite'>{e(c)}</td></tr>"
            for l, v, c in rows)

    def li(items):
        return "".join(f"<li>{e(t)} <span class='cite'>[{e(c)}]</span></li>" for t, c in items) or "<li class='verify'>VERIFY ON SITE</li>"

    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Pre-plan {e(str(b.get('address')))}</title>
<style>
body{{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:24px;color:#111;max-width:1100px}}
h1{{margin:0;font-size:22px}} .sub{{color:#555;margin-bottom:12px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border-bottom:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}}
th{{width:28%;color:#333}} .cite{{color:#666;font-size:11px;font-family:Menlo,monospace}}
.verify td,.verify{{color:#b45309;font-weight:600}}
.haz{{border:3px solid #b91c1c;padding:8px 12px;border-radius:6px;background:#fef2f2}} .haz h2{{color:#b91c1c;margin:0 0 4px}}
img{{max-width:100%;border:1px solid #ccc}} .panos img{{width:48%;margin:1%}}
.brief{{background:#111;color:#fff;padding:10px 14px;border-radius:6px;font-size:15px}}
.status{{float:right;font-weight:700;padding:4px 10px;border-radius:4px;background:{'#16a34a' if plan.get('status') == 'APPROVED' else '#ca8a04'};color:#fff}}
</style></head><body>
<span class="status">{e(str(plan.get('status')))}</span>
<h1>FirstIn Pre-Incident Plan: {e(str(b.get('address')))}</h1>
<div class="sub">NFPA 1660 structure · plan {e(str(plan.get('plan_id')))} · approved by {e(str(plan.get('approved_by') or 'n/a'))} · every field shows its source; orange = VERIFY ON SITE</div>
<div class="brief"><b>VOICE BRIEF:</b> {e(str(plan.get('voice_brief') or ''))}</div>
<div class="grid" style="margin-top:14px">
 <div>
  <div class="haz"><h2>HAZARDS</h2><ul>{li(_hazards(plan))}</ul></div>
  <h3>Building / Access / Interior</h3><table>{tr(_rows(plan))}</table>
 </div>
 <div>
  {'<h3>Aerial (Vexcel)</h3><img src="' + e(aerial) + '">' if aerial else '<h3>Aerial</h3><p class="verify">No aerial imagery</p>'}
  <h3>Tenants (CoStar)</h3><ul>{li(_tenants(plan))}</ul>
  <h3>Exposures</h3><ul>{li(_exposures(plan))}</ul>
  {'<h3>Interior (Matterport)</h3><div class="panos">' + ''.join(f'<img src="{e(u)}">' for u in panos[:4]) + '</div>' if panos else ''}
 </div>
</div>
</body></html>"""
    p = d / "preplan.html"
    p.write_text(doc)
    return str(p)


def _t(s, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def render_pdf(plan: dict) -> str | None:
    """One-page tactical sheet PDF (reportlab); progressively tighter, then multi-page fallback. Path or None."""
    for L, H, one in ((140, 7, True), (90, 5, True), (60, 4, True), (400, 20, False)):
        p = _build_pdf(plan, L, H, one)
        if p:
            return p
    return None


def _build_pdf(plan: dict, L: int, H: int, one_page: bool) -> str | None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        return None
    d = _out_dir(plan)
    path = d / "preplan.pdf"
    b = plan.get("building", {})
    sm = ParagraphStyle("sm", fontName="Helvetica", fontSize=7.2, leading=8.6)
    cs = ParagraphStyle("cs", fontName="Courier", fontSize=5.8, leading=7, textColor=colors.HexColor("#555555"))
    vs = ParagraphStyle("vs", parent=sm, textColor=colors.HexColor("#b45309"), fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=13, leading=15)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=9, leading=11, spaceBefore=3)
    hz = ParagraphStyle("hz", parent=sm, textColor=colors.HexColor("#991b1b"))
    E = html.escape

    story = [Paragraph(f"PRE-INCIDENT PLAN: {E(str(b.get('address')))}", h1),
             Paragraph(f"FirstIn · NFPA 1660 · plan {E(str(plan.get('plan_id')))} · status {E(str(plan.get('status')))} · "
                       f"approved by {E(str(plan.get('approved_by') or 'n/a'))}", cs), Spacer(1, 4),
             Paragraph(f"<b>BRIEF:</b> {E(str(plan.get('voice_brief') or ''))}", sm), Spacer(1, 4)]

    left = [Paragraph("HAZARDS", ParagraphStyle("hh", parent=h2, textColor=colors.HexColor("#b91c1c")))]
    for t, c in _hazards(plan)[:H] or [("VERIFY ON SITE", "")]:
        left.append(Paragraph(f"• {E(_t(t, L))} <font face='Courier' size='5.5' color='#666666'>[{E(c)}]</font>", hz))
    left.append(Paragraph("BUILDING · ACCESS · INTERIOR", h2))
    rows = [[Paragraph(E(l), sm), Paragraph(E(_t(v, L)), vs if v == VERIFY else sm), Paragraph(E(c), cs)] for l, v, c in _rows(plan)]
    if rows:
        t = Table(rows, colWidths=[0.85 * inch, 1.75 * inch, 1.2 * inch])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                               ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        left.append(t)

    right = []
    media = plan.get("media") or {}
    img = _local_image(media.get("aerial_url")) or _local_image(media.get("aerial_path"))
    if img:
        try:
            im = Image(str(img))
            ratio = im.imageHeight / float(im.imageWidth or 1)
            w = 3.3 * inch
            right += [Paragraph("AERIAL (Vexcel)", h2), Image(str(img), width=w, height=min(w * ratio, 2.6 * inch))]
        except Exception:  # noqa: BLE001
            pass
    right.append(Paragraph("TENANTS (CoStar)", h2))
    for t, c in _tenants(plan)[:H] or [("VERIFY ON SITE", "")]:
        right.append(Paragraph(f"• {E(_t(t, L))} <font face='Courier' size='5.5' color='#666666'>[{E(c)}]</font>", sm))
    right.append(Paragraph("EXPOSURES", h2))
    for t, c in _exposures(plan)[:H] or [("VERIFY ON SITE", "")]:
        right.append(Paragraph(f"• {E(_t(t, L))} <font face='Courier' size='5.5' color='#666666'>[{E(c)}]</font>", sm))
    panos = [p for p in (_local_image(u) for u in (media.get("pano_urls") or [])[:2]) if p]
    if panos:
        right.append(Paragraph("INTERIOR (Matterport)", h2))
        for p in panos:
            try:
                im = Image(str(p))
                ratio = im.imageHeight / float(im.imageWidth or 1)
                right.append(Image(str(p), width=3.3 * inch, height=min(3.3 * inch * ratio, 1.3 * inch)))
            except Exception:  # noqa: BLE001
                pass
    vos = plan.get("verify_on_site") or []
    if vos:
        right.append(Paragraph(f"VERIFY ON SITE ({len(vos)})", ParagraphStyle("v2", parent=h2, textColor=colors.HexColor("#b45309"))))
        right.append(Paragraph(E(", ".join(vos[:30])), cs))

    if one_page:
        body = Table([[left, right]], colWidths=[3.9 * inch, 3.5 * inch])
        body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(body)
    else:
        story += left + right
    try:
        doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.4 * inch, rightMargin=0.4 * inch,
                                topMargin=0.35 * inch, bottomMargin=0.35 * inch, title="FirstIn pre-plan")
        doc.build(story)
        if one_page and doc.page > 1:
            raise OverflowError(f"{doc.page} pages")
    except Exception:  # noqa: BLE001
        if one_page:
            log.warning("render_pdf: one-page layout overflowed (L=%s) for %s; tightening", L, plan.get("plan_id"))
        else:
            log.exception("render_pdf failed for %s", plan.get("plan_id"))
        return None
    return str(path)


def tts_brief(text: str, out_path: str | None = None) -> str | None:
    """Speak `text` to an audio file. macOS `say` -> aiff -> mp3 (ffmpeg/lame) or m4a (afconvert)."""
    out = Path(out_path) if out_path else config.OUT_DIR / "brief.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    aiff = out.with_suffix(".aiff")
    say = shutil.which("say")
    if not say:
        return None
    import re as _re

    text = _re.sub(r"\bFDC\b", "F D C", text, flags=_re.I)
    text = text.replace("/", " or ").replace("\u2014", ",").replace("…", "")
    voice = []
    v = __import__("os").environ.get("FIRSTIN_VOICE")
    if v:
        voice = ["-v", v]
    try:
        subprocess.run([say, *voice, "-r", "195", "-o", str(aiff), text], check=True, timeout=60,
                       capture_output=True)
        if shutil.which("ffmpeg"):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), "-codec:a", "libmp3lame", "-q:a", "4",
                            str(out.with_suffix(".mp3"))], check=True, timeout=60, capture_output=True)
            final = out.with_suffix(".mp3")
        elif shutil.which("lame"):
            subprocess.run(["lame", "--quiet", str(aiff), str(out.with_suffix(".mp3"))], check=True, timeout=60)
            final = out.with_suffix(".mp3")
        else:
            subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(aiff), str(out.with_suffix(".m4a"))], check=True,
                           timeout=60)
            final = out.with_suffix(".m4a")
        aiff.unlink(missing_ok=True)
        return str(final)
    except Exception:  # noqa: BLE001
        return str(aiff) if aiff.exists() else None


def write_json(plan: dict, name: str) -> str:
    p = _out_dir(plan) / name
    p.write_text(json.dumps(plan, indent=1, default=str))
    return str(p)
