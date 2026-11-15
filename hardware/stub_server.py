#!/usr/bin/env python3
"""Tiny stand-in for the FirstIn FastAPI backend (CONTRACTS.md), stdlib only.

Use it to test hardware/incab.py and photon/ without the real agent.

    python3 hardware/stub_server.py               # :8000
    python3 hardware/stub_server.py --port 8001

Endpoints (subset of CONTRACTS.md):
    GET  /incab/active          latest APPROVED plan summary (404 until something is approved)
    GET  /plan/{run_id}         plan JSON + status
    POST /approve/{run_id}      {approved_by, decision: approve|reject, edits?}
    POST /ask                   {plan_id, question} -> {answer}  (keyword lookup over the plan)
    POST /preplan               {building_id} -> {run_id}  (instantly PENDING_APPROVAL; calls photon /notify if PHOTON_URL set)
    GET  /static/brief.<ext>    voice brief audio (generated with macOS `say` if available)
Stub-only helpers:
    POST /stub/approve_next     approve the newest pending run (simulates officer)
    POST /stub/new_plan         same as /preplan with a random demo building
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PHOTON_URL = os.environ.get("PHOTON_URL", "")  # e.g. http://localhost:8010

BUILDINGS = [
    {
        "address": "1234 Example St, Houston, TX",
        "stories": 4, "year_built": 1978, "construction": "Steel frame (era-inferred)",
        "hazards": [
            {"type": "Chlorine/oxidizer", "location": "Floor 1 east", "reason": "Pool-supply tenant"},
            {"type": "Lightweight truss roof", "location": "Roof", "reason": "Construction era"},
            {"type": "Possible asbestos", "location": "Mechanical rooms", "reason": "Built pre-1980"},
        ],
        "stairs": ["North", "South (standpipe)"],
        "roof_access": "North alley, parapet ~3ft",
        "voice_brief": ("Engine 12, four-story office, built 1978, steel frame. Tenant includes a pool-supply "
                        "distributor: possible chlorine on floor one, east side. Two stairwells, north and south. "
                        "Standpipe in the south stair. Roof access via north alley. Exposure: three-story building "
                        "15 feet west."),
    },
    {
        "address": "800 Wilshire Blvd, Los Angeles, CA",
        "stories": 12, "year_built": 1964, "construction": "Reinforced concrete",
        "hazards": [
            {"type": "Emergency generator diesel", "location": "Basement B1", "reason": "Utility room"},
            {"type": "Restaurant grease", "location": "Floor 1 west", "reason": "Tenant use"},
            {"type": "Limited roof access", "location": "Roof", "reason": "Aerial"},
        ],
        "stairs": ["East (standpipe)", "West (standpipe)"],
        "roof_access": "East stair penthouse",
        "voice_brief": ("Engine 12, twelve-story office, built 1964, concrete. Diesel generator in basement. "
                        "Restaurant grease, floor one west. Two stairwells east and west, both with standpipes. "
                        "Roof access via east stair penthouse."),
    },
]

STATE = {"runs": {}, "active_run": None, "audio_dir": tempfile.mkdtemp(prefix="firstin_stub_")}
LOCK = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def make_audio(run_id, text):
    """Return filename of an audio file for the brief, or None."""
    say = shutil.which("say")
    if not say:
        return None
    path = os.path.join(STATE["audio_dir"], f"{run_id}.aiff")
    try:
        subprocess.run([say, "-o", path, text], check=True, timeout=60)
        ff = shutil.which("ffmpeg")
        if ff:
            mp3 = path[:-5] + ".mp3"
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", path, mp3], check=True, timeout=60)
            return os.path.basename(mp3)
        return os.path.basename(path)
    except Exception as e:  # noqa: BLE001
        print("[stub] tts failed:", e)
        return None


def new_run(building_id=None):
    b = random.choice(BUILDINGS) if building_id is None else BUILDINGS[hash(building_id) % len(BUILDINGS)]
    run_id = uuid.uuid4().hex[:12]
    plan = {
        "building": {
            "address": b["address"],
            "stories": {"value": b["stories"], "cite": {"src": "costar", "id": "stub", "conf": 0.98}},
            "year_built": {"value": b["year_built"], "cite": {"src": "costar", "id": "stub", "conf": 0.98}},
            "construction": {"value": b["construction"], "cite": {"src": "inference", "conf": 0.6}},
        },
        "access": {"roof_access": {"value": b["roof_access"], "cite": {"src": "vexcel", "conf": 0.7}}},
        "interior": {"stairwells": [{"loc": s.split(" ")[0], "standpipe": "standpipe" in s} for s in b["stairs"]]},
        "hazards": b["hazards"],
        "voice_brief": b["voice_brief"],
        "status": "PENDING_APPROVAL",
        "approved_by": None,
    }
    with LOCK:
        STATE["runs"][run_id] = {"run_id": run_id, "b": b, "plan": plan, "approved_at": None, "audio": None}
    threading.Thread(target=lambda: STATE["runs"][run_id].update(audio=make_audio(run_id, b["voice_brief"])),
                     daemon=True).start()
    if PHOTON_URL:
        threading.Thread(target=notify_photon, args=(run_id,), daemon=True).start()
    print(f"[stub] new run {run_id} ({b['address']}) PENDING_APPROVAL")
    return run_id


def notify_photon(run_id):
    r = STATE["runs"][run_id]
    body = {
        "run_id": run_id,
        "address": r["b"]["address"],
        "summary": f'{r["b"]["stories"]}-story, built {r["b"]["year_built"]}, {r["b"]["construction"]}',
        "top_hazards": r["b"]["hazards"][:3],
    }
    try:
        req = urllib.request.Request(PHOTON_URL.rstrip("/") + "/notify", data=json.dumps(body).encode(),
                                     headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
        print(f"[stub] notified photon for {run_id}")
    except Exception as e:  # noqa: BLE001
        print(f"[stub] photon notify failed: {e}")


def approve(run_id, approved_by, decision):
    with LOCK:
        r = STATE["runs"].get(run_id)
        if not r:
            return None
        if decision == "reject":
            r["plan"]["status"] = "REJECTED"
        else:
            r["plan"]["status"] = "APPROVED"
            r["plan"]["approved_by"] = approved_by
            r["approved_at"] = now_iso()
            STATE["active_run"] = run_id
    print(f"[stub] run {run_id} -> {r['plan']['status']} by {approved_by}")
    return r


def incab_summary(host):
    rid = STATE["active_run"]
    if not rid:
        return None
    r = STATE["runs"][rid]
    b = r["b"]
    return {
        "plan_id": rid,
        "address": b["address"],
        "stories": b["stories"],
        "year_built": b["year_built"],
        "construction": b["construction"],
        "top_hazards": b["hazards"][:3],
        "stairs": ", ".join(b["stairs"]),
        "roof_access": b["roof_access"],
        "voice_brief": b["voice_brief"],
        "audio_url": f"http://{host}/static/{r['audio']}" if r["audio"] else None,
        "approved_at": r["approved_at"],
    }


def answer(plan_id, q):
    r = STATE["runs"].get(plan_id) or (STATE["runs"].get(STATE["active_run"]) if STATE["active_run"] else None)
    if not r:
        return "No approved plan. VERIFY ON SITE."
    b, q = r["b"], q.lower()
    if "standpipe" in q:
        sp = [s for s in b["stairs"] if "standpipe" in s]
        return f"Standpipe in the {sp[0].split(' ')[0].lower()} stairwell." if sp else "No standpipe recorded. VERIFY ON SITE."
    if "stair" in q:
        return "Stairwells: " + ", ".join(b["stairs"]) + "."
    if "roof" in q:
        return "Roof access: " + b["roof_access"] + "."
    if "hazard" in q or "danger" in q or "chlor" in q:
        return "Hazards: " + "; ".join(f"{h['type']} ({h['location']})" for h in b["hazards"]) + "."
    if "floor" in q or "stor" in q or "built" in q or "year" in q:
        return f"{b['stories']} stories, built {b['year_built']}, {b['construction']}."
    return "Not in the approved plan. VERIFY ON SITE."


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter
        if "/incab/active" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/incab/active":
            s = incab_summary(self.headers.get("host", "localhost:8000"))
            return self._json(200, s) if s else self._json(404, {"detail": "no approved plan"})
        if p.startswith("/plan/"):
            r = STATE["runs"].get(p.split("/")[2])
            return self._json(200, {**r["plan"], "run_id": r["run_id"]}) if r else self._json(404, {"detail": "unknown run"})
        if p == "/buildings":
            return self._json(200, [{"building_id": f"stub-{i}", "address": b["address"]} for i, b in enumerate(BUILDINGS)])
        if p.startswith("/static/"):
            fn = os.path.basename(p)
            fp = os.path.join(STATE["audio_dir"], fn)
            if not os.path.exists(fp):
                return self._json(404, {"detail": "no audio"})
            data = open(fp, "rb").read()
            self.send_response(200)
            self.send_header("content-type", "audio/mpeg" if fn.endswith(".mp3") else "audio/aiff")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        return self._json(404, {"detail": "not found"})

    def do_POST(self):
        p = self.path.split("?")[0]
        body = self._body()
        if p == "/preplan" or p == "/stub/new_plan":
            return self._json(200, {"run_id": new_run(body.get("building_id"))})
        if p.startswith("/approve/"):
            r = approve(p.split("/")[2], body.get("approved_by", "unknown"), body.get("decision", "approve"))
            return self._json(200, {"ok": True, "status": r["plan"]["status"]}) if r else self._json(404, {"detail": "unknown run"})
        if p == "/stub/approve_next":
            pend = [k for k, r in STATE["runs"].items() if r["plan"]["status"] == "PENDING_APPROVAL"]
            if not pend:
                rid = new_run()
                time.sleep(0.1)
            else:
                rid = pend[-1]
            approve(rid, body.get("approved_by", "stub"), "approve")
            return self._json(200, {"ok": True, "run_id": rid})
        if p == "/ask":
            return self._json(200, {"answer": answer(body.get("plan_id", ""), body.get("question", ""))})
        return self._json(404, {"detail": "not found"})


def main():
    global PHOTON_URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--photon", default=PHOTON_URL, help="photon bridge URL to call /notify on new runs")
    ap.add_argument("--seed-approved", action="store_true", help="start with one approved plan")
    a = ap.parse_args()
    PHOTON_URL = a.photon
    if a.seed_approved:
        rid = new_run()
        approve(rid, "seed", "approve")
    print(f"[stub] FirstIn stub backend on http://0.0.0.0:{a.port}  (photon={PHOTON_URL or 'off'})")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
