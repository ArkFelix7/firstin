"""publish_preplan: render the approved plan (HTML/PDF/TTS) and make it the active in-cab plan.

HITL-gated in the agent (interrupt_on={"publish_preplan": True}); the officer's
decision/edits are applied to agent/out/{plan_id}/final.json before this runs.
"""
from __future__ import annotations

import json
import time

from .. import config
from ..plan_builder import incab_summary
from . import render

ACTIVE = "active.json"


def load_plan(plan_id: str) -> dict | None:
    for name in ("final.json", "draft.json"):
        p = config.OUT_DIR / plan_id / name
        if p.exists():
            return json.loads(p.read_text())
    return None


def publish_preplan(plan_id: str) -> dict:
    """Publish an officer-approved pre-plan: PDF + HTML tactical sheet + voice brief audio -> in-cab unit."""
    plan = load_plan(plan_id)
    if not plan:
        return {"error": f"no plan {plan_id}"}
    if plan.get("status") != "APPROVED":
        return {"error": f"plan {plan_id} is {plan.get('status')}, not APPROVED"}
    html_path = render.render_html(plan)
    pdf_path = render.render_pdf(plan)
    audio = render.tts_brief(plan.get("voice_brief") or "", str(config.OUT_DIR / plan_id / "brief.mp3"))
    plan["html_url"] = config.static_url(html_path)
    plan["pdf_url"] = config.static_url(pdf_path)
    plan["audio_url"] = config.static_url(audio)
    plan["published_at"] = time.time()
    render.write_json(plan, "final.json")
    summary = incab_summary(plan, plan["audio_url"])
    (config.OUT_DIR / ACTIVE).write_text(json.dumps(summary, indent=1, default=str))
    return {"plan_id": plan_id, "html_url": plan["html_url"], "pdf_url": plan["pdf_url"],
            "audio_url": plan["audio_url"], "incab": summary}


def active_summary() -> dict | None:
    p = config.OUT_DIR / ACTIVE
    if p.exists():
        return json.loads(p.read_text())
    return None
