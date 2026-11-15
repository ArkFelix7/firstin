"""Render an approved plan: HTML tactical sheet, one-page PDF (reportlab), and TTS voice brief."""
from __future__ import annotations

import html
import json
import os
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


def _tts_text(text: str) -> str:
    import re as _re

    text = _re.sub(r"\bFDC\b", "F D C", text, flags=_re.I)
    return text.replace("/", " or ").replace("\u2014", ",").replace("\u2026", "")


def _run(cmd: list[str], **kw) -> None:
    subprocess.run(cmd, check=True, timeout=60, capture_output=True, **kw)


def _to_mp3(src: Path, out: Path) -> Path:
    """src (aiff/wav) -> mp3 via ffmpeg or lame; m4a via afconvert (macOS); else keep src."""
    mp3 = out.with_suffix(".mp3")
    if shutil.which("ffmpeg"):
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-codec:a", "libmp3lame", "-q:a", "4", str(mp3)])
        return mp3
    if shutil.which("lame"):
        _run(["lame", "--quiet", str(src), str(mp3)])
        return mp3
    if shutil.which("afconvert"):
        m4a = out.with_suffix(".m4a")
        _run(["afconvert", "-f", "m4af", "-d", "aac", str(src), str(m4a)])
        return m4a
    return src


def _tts_say(text: str, out: Path) -> Path | None:
    say = shutil.which("say")
    if not say:
        return None
    aiff = out.with_suffix(".aiff")
    v = os.environ.get("FIRSTIN_VOICE")
    _run([say, *(["-v", v] if v else []), "-r", "195", "-o", str(aiff), text])
    return aiff


def _tts_piper(text: str, out: Path) -> Path | None:
    exe, model = shutil.which("piper"), os.environ.get("PIPER_MODEL", "")
    if not exe or not model or not Path(model).exists():
        return None
    wav = out.with_suffix(".wav")
    _run([exe, "-m", model, "-f", str(wav)], input=text.encode())
    return wav


def _tts_espeak(text: str, out: Path) -> Path | None:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        return None
    wav = out.with_suffix(".wav")
    _run([exe, "-v", os.environ.get("FIRSTIN_ESPEAK_VOICE", "en-us"), "-s", "165", "-w", str(wav), text])
    return wav


def _tts_pico(text: str, out: Path) -> Path | None:
    exe = shutil.which("pico2wave")
    if not exe:
        return None
    wav = out.with_suffix(".wav")
    _run([exe, "-l", "en-US", "-w", str(wav), text])
    return wav


TTS_ENGINES = (("say", _tts_say), ("piper", _tts_piper), ("espeak-ng", _tts_espeak), ("pico2wave", _tts_pico))


def tts_brief(text: str, out_path: str | None = None) -> str | None:
    """Speak `text` to an audio file (mp3 when ffmpeg/lame exist).

    Engine chain: macOS `say` -> `piper` (env PIPER_MODEL) -> `espeak-ng` -> `pico2wave`.
    If every engine fails, an already rendered brief at the target path is kept.
    """
    out = Path(out_path) if out_path else config.OUT_DIR / "brief.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = _tts_text(text)
    for name, engine in TTS_ENGINES:
        raw: Path | None = None
        try:
            raw = engine(text, out)
            if not raw or not raw.exists():
                continue
            final = _to_mp3(raw, out)
            if final != raw:
                raw.unlink(missing_ok=True)
            print(f"[tts] engine={name} -> {final.name}", flush=True)
            log.info("tts_brief: engine=%s file=%s", name, final)
            return str(final)
        except Exception as e:  # noqa: BLE001
            log.warning("tts_brief: %s failed: %s", name, e)
            if raw is not None and raw.exists():
                print(f"[tts] engine={name} (unconverted) -> {raw.name}", flush=True)
                return str(raw)
    for ext in (".mp3", ".m4a", ".wav"):
        pre = out.with_suffix(ext)
        if pre.exists() and pre.stat().st_size > 0:
            print(f"[tts] no engine worked; keeping pre-rendered {pre.name}", flush=True)
            return str(pre)
    print("[tts] no TTS engine available (say/piper/espeak-ng/pico2wave); no audio brief", flush=True)
    return None


def write_json(plan: dict, name: str) -> str:
    p = _out_dir(plan) / name
    p.write_text(json.dumps(plan, indent=1, default=str))
    return str(p)
