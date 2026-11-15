#!/usr/bin/env python3
"""FirstIn in-cab unit ("rig tablet") client. README section 8.

Runs on a Raspberry Pi (GPIO button + LED + speaker + Chromium kiosk) or on a
laptop in simulation mode (keyboard instead of GPIO). Python 3.7+ stdlib only;
gpiozero / vosk / pyttsx3 are used if present.

    python3 incab.py --backend http://192.168.1.20:8000            # Pi (auto-detects GPIO)
    python3 incab.py --sim --backend http://localhost:8000          # laptop, keyboard
    python3 incab.py --sim --kiosk --web http://localhost:3000      # also open the /incab card

Keyboard (sim mode, or on a Pi with a keyboard attached):
    SPACE  BRIEF ME (play voice brief; press again to stop)
    a      ask a question (records 5 s if a mic recorder exists, else type it)
    s      show current card again
    q      quit

Hardware (see hardware/README.md):
    Grove button "BRIEF ME"  GPIO17  (tap = brief, hold >1 s = ask)
    LED / Grove LED          GPIO27  (blinks on new plan, solid while a plan is active)
"""
import argparse
import json
import math
import os
import platform
import queue
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave

IS_MAC = platform.system() == "Darwin"
TMP = tempfile.mkdtemp(prefix="firstin_incab_")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# --------------------------------------------------------------------------- HTTP
def http_json(method, url, body=None, timeout=5.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def download(url, timeout=15.0):
    ext = os.path.splitext(url.split("?")[0])[1] or ".mp3"
    path = os.path.join(TMP, "brief" + ext)
    with urllib.request.urlopen(url, timeout=timeout) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    return path


# --------------------------------------------------------------------------- GPIO
class Hardware:
    """gpiozero if available and not --sim; otherwise prints."""

    def __init__(self, sim, button_pin=17, led_pin=27, on_tap=None, on_hold=None, plain_button=False):
        self.led = None
        self.button = None
        self.sim = sim
        if sim:
            log("[hw] simulation mode (keyboard)")
            return
        try:
            from gpiozero import LED, Button  # type: ignore
        except Exception as e:  # noqa: BLE001
            log(f"[hw] gpiozero unavailable ({e.__class__.__name__}); GPIO disabled, keyboard still works")
            self.sim = True
            return
        try:
            self.led = LED(led_pin)
            # Grove button drives SIG HIGH when pressed (has its own pull-down) -> pull_up=False.
            # Plain 2-leg button wired GPIO->GND -> internal pull-up.
            self.button = Button(button_pin, pull_up=plain_button, bounce_time=0.05, hold_time=1.0)
            held = {"v": False}

            def _held():
                held["v"] = True
                if on_hold:
                    on_hold()

            def _released():
                if not held["v"] and on_tap:
                    on_tap()
                held["v"] = False

            self.button.when_held = _held
            self.button.when_released = _released
            log(f"[hw] GPIO ready: button GPIO{button_pin}, LED GPIO{led_pin}")
        except Exception as e:  # noqa: BLE001
            log(f"[hw] GPIO init failed ({e}); continuing without GPIO")
            self.sim = True

    def flash_then_solid(self, seconds=5):
        if self.led:
            self.led.blink(on_time=0.15, off_time=0.15, n=int(seconds / 0.3), background=False)
            self.led.on()
        else:
            log("[LED] *** BLINK BLINK BLINK *** (then solid)")

    def off(self):
        if self.led:
            self.led.off()


# --------------------------------------------------------------------------- audio
def which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


class Audio:
    def __init__(self, dry=False):
        self.dry = dry  # print commands instead of playing (tests / no speaker)
        self.proc = None
        self.lock = threading.Lock()
        self.beep_path = os.path.join(TMP, "beep.wav")
        self._make_beep(self.beep_path)

    @staticmethod
    def _make_beep(path, freqs=(880, 0, 880, 0, 1320), dur=0.12, rate=22050):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = bytearray()
            for f in freqs:
                for i in range(int(rate * dur)):
                    v = 0 if f == 0 else int(12000 * math.sin(2 * math.pi * f * i / rate))
                    frames += struct.pack("<h", v)
            w.writeframes(bytes(frames))

    def _player_cmd(self, path):
        ext = os.path.splitext(path)[1].lower()
        if IS_MAC and which("afplay"):
            return ["afplay", path]
        if ext == ".mp3" and which("mpg123"):
            return ["mpg123", "-q", path]
        if ext in (".wav",) and which("aplay"):
            return ["aplay", "-q", path]
        if which("ffplay"):
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
        if which("cvlc"):
            return ["cvlc", "--play-and-exit", "--quiet", path]
        if which("paplay") and ext == ".wav":
            return ["paplay", path]
        return None

    def _tts_cmd(self, text):
        if which("espeak-ng", "espeak"):
            return [which("espeak-ng", "espeak"), "-s", "160", text]
        if IS_MAC and which("say"):
            return ["say", text]
        return None

    def _run(self, cmd, wait):
        if self.dry:
            log("[audio:dry]", " ".join(cmd[:2]), "..." if len(cmd) > 2 else "")
            return
        with self.lock:
            self.stop()
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p = self.proc
        if wait:
            p.wait()

    def playing(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None

    def beep(self):
        cmd = self._player_cmd(self.beep_path)
        if cmd:
            self._run(cmd, wait=True)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()

    def play_file(self, path, wait=False):
        cmd = self._player_cmd(path)
        if not cmd:
            return False
        self._run(cmd, wait)
        return True

    def say(self, text, wait=False):
        cmd = self._tts_cmd(text)
        if cmd:
            self._run(cmd, wait)
            return True
        try:
            import pyttsx3  # type: ignore
            if self.dry:
                log("[audio:dry] pyttsx3", text[:40])
                return True
            eng = pyttsx3.init()
            eng.say(text)
            eng.runAndWait()
            return True
        except Exception:  # noqa: BLE001
            log("[audio] no player/TTS available. Brief text:\n   ", text)
            return False


# --------------------------------------------------------------------------- STT (optional)
def can_record():
    return bool(which("arecord", "rec") or (IS_MAC and which("ffmpeg")))


def record(seconds=5):
    """Record mono 16 kHz wav. Returns path or None."""
    path = os.path.join(TMP, "ask.wav")
    if which("arecord"):  # Pi / Linux (ALSA)
        cmd = ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", str(seconds), path]
    elif which("rec"):  # sox
        cmd = ["rec", "-q", "-r", "16000", "-c", "1", path, "trim", "0", str(seconds)]
    elif IS_MAC and which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "avfoundation", "-i", ":0",
               "-t", str(seconds), "-ac", "1", "-ar", "16000", path]
    else:
        return None
    log(f"[ask] recording {seconds}s... speak now")
    try:
        subprocess.run(cmd, check=True, timeout=seconds + 10)
        return path
    except Exception as e:  # noqa: BLE001
        log("[ask] record failed:", e)
        return None


def transcribe(path, args):
    """STT, first available: Vosk (offline, Pi-friendly) -> OpenAI Whisper API (OPENAI_API_KEY)."""
    if args.vosk_model and os.path.isdir(args.vosk_model):
        try:
            from vosk import KaldiRecognizer, Model  # type: ignore
            wf = wave.open(path, "rb")
            rec = KaldiRecognizer(Model(args.vosk_model), wf.getframerate())
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
            return json.loads(rec.FinalResult()).get("text", "").strip() or None
        except Exception as e:  # noqa: BLE001
            log("[stt] vosk failed:", e)
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        try:
            boundary = "----firstin" + str(int(time.time()))
            audio = open(path, "rb").read()
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-1\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"ask.wav\"\r\n"
                    f"Content-Type: audio/wav\r\n\r\n").encode() + audio + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=body, method="POST",
                                         headers={"Authorization": f"Bearer {key}",
                                                  "Content-Type": f"multipart/form-data; boundary={boundary}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read()).get("text", "").strip() or None
        except Exception as e:  # noqa: BLE001
            log("[stt] whisper failed:", e)
    return None


# --------------------------------------------------------------------------- kiosk
def launch_kiosk(url):
    candidates = ["chromium-browser", "chromium", "google-chrome"]
    if IS_MAC:
        mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(mac_chrome):
            candidates.insert(0, mac_chrome)
    exe = next((c for c in candidates if os.path.exists(c) or shutil.which(c)), None)
    if not exe:
        log("[kiosk] no Chromium/Chrome found; open", url, "manually")
        return None
    profile = os.path.join(TMP, "chrome-profile")
    cmd = [exe, "--kiosk", "--noerrdialogs", "--disable-infobars", "--no-first-run",
           "--disable-session-crashed-bubble", "--check-for-update-interval=31536000",
           "--autoplay-policy=no-user-gesture-required", f"--user-data-dir={profile}", url]
    log("[kiosk] launching", os.path.basename(exe), url)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- app
def render_card(p):
    def hz(h):
        if isinstance(h, dict):
            return " - ".join(str(x) for x in (h.get("type"), h.get("location")) if x) or json.dumps(h)
        return str(h)

    w = 64
    lines = [
        "=" * w,
        " FIRSTIN PRE-PLAN  (approved {})".format(p.get("approved_at") or "?"),
        "=" * w,
        " " + str(p.get("address", "?")),
        " {} stories | built {} | {}".format(p.get("stories", "?"), p.get("year_built", "?"),
                                             p.get("construction", "?")),
        "-" * w,
        " TOP HAZARDS:",
    ]
    for i, h in enumerate((p.get("top_hazards") or [])[:3], 1):
        lines.append(f"   {i}. {hz(h)}")
    stairs = p.get("stairs")
    if isinstance(stairs, list):
        stairs = ", ".join(s if isinstance(s, str) else s.get("loc", json.dumps(s)) for s in stairs)
    lines += [
        "-" * w,
        f" STAIRS: {stairs or 'VERIFY ON SITE'}",
        f" ROOF:   {p.get('roof_access') or 'VERIFY ON SITE'}",
        "=" * w,
        " [SPACE / BRIEF ME] play brief   [a / hold] ask   [q] quit",
    ]
    return "\n".join(lines)


class InCab:
    def __init__(self, args):
        self.args = args
        self.backend = args.backend.rstrip("/")
        self.plan = None
        self.plan_id = None
        self.events = queue.Queue()
        self.audio = Audio(dry=args.no_audio)
        self.hw = Hardware(args.sim, args.button_pin, args.led_pin,
                           on_tap=lambda: self.events.put("brief"), on_hold=lambda: self.events.put("ask"),
                           plain_button=args.plain_button)
        self.audio_path = None
        self.running = True
        self.keys_paused = threading.Event()  # set while a question is being typed

    # -- polling
    def poll_loop(self):
        last_err = None
        while self.running:
            try:
                p = http_json("GET", self.backend + "/incab/active", timeout=4)
                if p and p.get("plan_id") and p.get("plan_id") != self.plan_id:
                    self.events.put(("new", p))
                last_err = None
            except urllib.error.HTTPError as e:
                if e.code != 404 and last_err != e.code:  # 404 = nothing approved yet
                    log("[poll] HTTP", e.code)
                last_err = e.code
            except Exception as e:  # noqa: BLE001
                msg = e.__class__.__name__
                if last_err != msg:
                    log(f"[poll] backend unreachable ({msg}); retrying every {self.args.interval}s")
                last_err = msg
            time.sleep(self.args.interval)

    # -- keyboard (works in sim mode and on a Pi with a keyboard)
    def key_loop(self):
        if not sys.stdin.isatty():
            return
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while self.running:
                if self.keys_paused.is_set():
                    time.sleep(0.1)
                    continue
                r, _, _ = select.select([sys.stdin], [], [], 0.2)
                if not r:
                    continue
                ch = sys.stdin.read(1)
                if ch == " ":
                    self.events.put("brief")
                elif ch in "aA":
                    if self.args.type_questions or not can_record():
                        self.keys_paused.set()  # hand stdin to the question prompt
                    self.events.put("ask")
                elif ch in "sS":
                    self.events.put("show")
                elif ch in "qQ\x03":
                    self.events.put("quit")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # -- actions
    def on_new_plan(self, p):
        self.plan, self.plan_id, self.audio_path = p, p["plan_id"], None
        log(f"[plan] NEW approved pre-plan {self.plan_id}")
        print(render_card(p), flush=True)
        threading.Thread(target=self.hw.flash_then_solid, daemon=True).start()
        self.audio.beep()
        # prefetch audio so BRIEF ME is instant
        if p.get("audio_url"):
            threading.Thread(target=self._prefetch, args=(p["plan_id"], p["audio_url"]), daemon=True).start()
        if self.args.auto_brief:
            self.events.put("brief")

    def _prefetch(self, pid, url):
        try:
            path = download(url)
            if pid == self.plan_id:
                self.audio_path = path
                log("[audio] brief cached", os.path.basename(path))
        except Exception as e:  # noqa: BLE001
            log("[audio] prefetch failed:", e)

    def brief(self):
        if not self.plan:
            log("[brief] no approved plan yet")
            self.audio.say("No approved pre-plan yet.")
            return
        if self.audio.playing():
            log("[brief] stop")
            self.audio.stop()
            return
        log("[brief] BRIEF ME")
        path = self.audio_path
        if not path and self.plan.get("audio_url"):
            try:
                path = self.audio_path = download(self.plan["audio_url"])
            except Exception as e:  # noqa: BLE001
                log("[brief] audio download failed:", e)
        if path and self.audio.play_file(path):
            return
        self.audio.say(self.plan.get("voice_brief") or "Brief unavailable. Verify on site.")

    def ask(self):
        if not self.plan:
            log("[ask] no approved plan yet")
            return
        self.audio.stop()
        question = None
        wav = None if self.args.type_questions else record(5)
        if wav:
            question = transcribe(wav, self.args)
            if not question:
                log("[ask] no STT configured / nothing heard (see README: Vosk or OPENAI_API_KEY)")
        if not question and sys.stdin.isatty():
            self.keys_paused.set()
            time.sleep(0.25)  # let key_loop release stdin
            question = self._typed_question()
        if not question:
            self.audio.say("Sorry, I didn't catch that.")
            return
        log(f"[ask] Q: {question}")
        try:
            res = http_json("POST", self.backend + "/ask", {"plan_id": self.plan_id, "question": question}, timeout=30)
            answer = (res or {}).get("answer") or "No answer. Verify on site."
        except Exception as e:  # noqa: BLE001
            log("[ask] backend error:", e)
            answer = "I can't reach FirstIn. Verify on site."
        log(f"[ask] A: {answer}")
        self.audio.say(answer)

    def _typed_question(self):
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] |= termios.ICANON | termios.ECHO
        self.keys_paused.set()
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            sys.stdout.write("Question> ")
            sys.stdout.flush()
            return sys.stdin.readline().strip()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            self.keys_paused.clear()

    def run(self):
        log(f"[incab] backend {self.backend}  poll every {self.args.interval}s")
        if self.args.kiosk:
            launch_kiosk(self.args.web.rstrip("/") + "/incab")
        threading.Thread(target=self.poll_loop, daemon=True).start()
        threading.Thread(target=self.key_loop, daemon=True).start()
        if self.hw.sim and sys.stdin.isatty():
            log("[incab] SPACE = BRIEF ME, a = ask, s = show card, q = quit")
        deadline = time.time() + self.args.exit_after if self.args.exit_after else None
        try:
            while self.running:
                try:
                    ev = self.events.get(timeout=0.5)
                except queue.Empty:
                    if deadline and time.time() > deadline:
                        break
                    continue
                if isinstance(ev, tuple) and ev[0] == "new":
                    self.on_new_plan(ev[1])
                elif ev == "brief":
                    self.brief()
                elif ev == "ask":
                    try:
                        self.ask()
                    finally:
                        self.keys_paused.clear()
                elif ev == "show" and self.plan:
                    print(render_card(self.plan), flush=True)
                elif ev == "quit":
                    break
        except KeyboardInterrupt:
            pass
        self.running = False
        self.audio.stop()
        self.hw.off()
        log("[incab] bye")


def main():
    ap = argparse.ArgumentParser(description="FirstIn in-cab unit")
    ap.add_argument("--backend", default=os.environ.get("FIRSTIN_BACKEND", "http://localhost:8000"))
    ap.add_argument("--web", default=os.environ.get("FIRSTIN_WEB", "http://localhost:3000"),
                    help="dashboard base URL; kiosk opens <web>/incab")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--sim", action="store_true", help="force simulation mode (no GPIO)")
    ap.add_argument("--kiosk", action="store_true", help="launch Chromium fullscreen on <web>/incab")
    ap.add_argument("--button-pin", type=int, default=17)
    ap.add_argument("--led-pin", type=int, default=27)
    ap.add_argument("--plain-button", action="store_true",
                    help="2-leg button wired GPIO->GND (internal pull-up) instead of a Grove button module")
    ap.add_argument("--auto-brief", action="store_true", help="play brief automatically on new plan")
    ap.add_argument("--no-audio", action="store_true", help="print audio commands instead of playing")
    ap.add_argument("--type-questions", action="store_true", help="ask: type instead of recording")
    ap.add_argument("--mic", action="store_true", help="sim mode: record from the mic for 'a' instead of typing")
    ap.add_argument("--vosk-model", default=os.environ.get("VOSK_MODEL", ""), help="path to Vosk model dir")
    ap.add_argument("--exit-after", type=float, default=0, help="exit after N seconds (tests)")
    args = ap.parse_args()
    if not args.sim and IS_MAC:
        args.sim = True
    if args.sim and not args.mic:
        args.type_questions = True
    InCab(args).run()


if __name__ == "__main__":
    main()
