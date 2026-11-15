# FirstIn in-cab unit (hardware/)

A "rig tablet" that receives approved pre-plans and briefs the crew (main README section 8).

| Path | What it is | Status |
|---|---|---|
| `incab.py` | Pi / laptop client: polls `/incab/active`, LED + beep, card, BRIEF ME audio, hold-to-ask | **Tested** on macOS in sim mode against `stub_server.py` |
| `stub_server.py` | Stand-in for the FastAPI backend (CONTRACTS.md subset). Stdlib only | Tested |
| `pi/firstin-incab.service` | systemd user unit for `incab.py` | Written, not run on a Pi |
| `pi/firstin-kiosk.desktop` | Chromium kiosk autostart on `<laptop>:3000/incab` | Written, not run on a Pi |
| `sensecap/firstin_incab/` | ESP32 SenseCAP Indicator Arduino sketch | **UNTESTED skeleton**, not compiled |

## Quick test on a laptop (no hardware, no real backend)

```bash
# terminal 1: fake backend on :8001 (use :8000 only if the real agent is NOT running)
python3 hardware/stub_server.py --port 8001

# terminal 2: in-cab unit in simulation mode (keyboard = button)
python3 hardware/incab.py --sim --backend http://localhost:8001

# terminal 3: simulate the officer approving a plan
curl -XPOST localhost:8001/stub/approve_next
```

Terminal 2 beeps, prints the card, and "blinks" the LED. Then:
- **SPACE** = BRIEF ME (plays `audio_url`, or speaks `voice_brief` with `say`/espeak). Press again to stop.
- **a** = ask. Type "where's the standpipe?" and the answer is spoken (it goes through `POST /ask`).
- **s** = show the card again. **q** = quit.

Add `--kiosk --web http://localhost:3000` to also open Chrome fullscreen on the web team's `/incab` page.
Other flags: `--auto-brief` plays the brief as soon as a plan arrives, `--no-audio` prints the player command instead of playing, `--interval 2`.

## BOM

| Qty | Part | Notes |
|---|---|---|
| 1 | Raspberry Pi 4/5 (or 3B+) + 5V PSU + microSD with Raspberry Pi OS (Desktop) | MLH hardware desk |
| 1 | HDMI or DSI display (7" official touch is ideal) | For the Chromium kiosk card |
| 1 | Grove button (or any momentary push button) labeled **BRIEF ME** | GPIO17 |
| 1 | Grove LED (or LED + 330 ohm resistor) | GPIO27 |
| 1 | Speaker: USB speaker, 3.5 mm powered speaker, or Bluetooth (Echo Dot / Home Mini in BT mode) | For the voice brief |
| 0-1 | USB microphone (or USB webcam with a mic) | Only for hold-to-ask |
| 0-1 | Grove Base HAT for Raspberry Pi | Optional. Otherwise use female jumper wires to the Grove cables |
| 1 | Cardboard / 3D-printed case labeled ENGINE 12 | |

## Wiring

Physical pin numbers are on the 40-pin header (pin 1 is the corner next to the SD card on the Pi 4, marked with a square pad).

```
                Raspberry Pi 40-pin header (top view, USB ports at the bottom)
                       3V3  (1) (2)  5V
                     GPIO2  (3) (4)  5V
                     GPIO3  (5) (6)  GND
                     GPIO4  (7) (8)  GPIO14
   LED GND ----------  GND  (9) (10) GPIO15
 BUTTON SIG ------- GPIO17 (11) (12) GPIO18
                    GPIO27 (13) (14) GND ------------- BUTTON GND
   LED SIG -------'   (13 = GPIO27)
                    GPIO22 (15) (16) GPIO23
 BUTTON VCC -------    3V3 (17) (18) GPIO24
                         ...

 Grove button (4-pin cable):  yellow SIG -> pin 11 (GPIO17)
                              red VCC    -> pin 17 (3V3)
                              black GND  -> pin 14 (GND)
                              white NC   -> not connected
   (A Grove button drives SIG HIGH when pressed; incab.py defaults to that.)

 Grove LED (4-pin cable):     yellow SIG -> pin 13 (GPIO27)
                              red VCC    -> pin 1  (3V3)
                              black GND  -> pin 9  (GND)
 Bare LED instead:  GPIO27 (pin 13) --[330 ohm]--|>|-- GND (pin 9)   (long leg = anode toward resistor)

 Plain 2-leg push button instead of Grove:  GPIO17 (pin 11) ---[button]--- GND (pin 14)
   (run incab.py with --plain-button: internal pull-up, no resistor needed)

 Speaker: USB speaker -> any USB port, or 3.5 mm jack (Pi 4), or Bluetooth (see below).
 Mic (optional): USB mic -> any USB port.

 With a Grove Base HAT: button -> port D16 is GPIO16, D5 is GPIO5, etc. Use --button-pin / --led-pin
 to match the port you used (for example: --button-pin 5 --led-pin 16).
```

Button behavior: **tap** = BRIEF ME (press again to stop), **hold for more than 1 second** = ask (records 5 seconds).
The LED blinks for about 5 seconds when a new approved plan arrives, then stays on while a plan is active.

## Pi setup (about 15 minutes)

1. Flash **Raspberry Pi OS with Desktop** using Raspberry Pi Imager. In the settings, set the hostname (`engine12`), user, WiFi (same network as the laptop), and enable SSH.
2. On the laptop, find its LAN IP (`ipconfig getifaddr en0` on macOS). Run the backend so the Pi can reach it:
   `uvicorn ... --host 0.0.0.0 --port 8000`, and the web app with `next dev -H 0.0.0.0` (or `npm run dev -- -H 0.0.0.0`).
   Allow incoming connections in the macOS firewall prompt. Test from the Pi: `curl http://<laptop-ip>:8000/incab/active`.
3. On the Pi:
   ```bash
   sudo apt update
   sudo apt install -y python3-gpiozero mpg123 espeak-ng alsa-utils chromium-browser
   # (on Bookworm the browser package may be called "chromium")
   git clone <repo> ~/firstin   # or scp -r hardware/ pi@engine12.local:~/firstin/hardware
   python3 ~/firstin/hardware/incab.py --backend http://<laptop-ip>:8000 --kiosk --web http://<laptop-ip>:3000
   ```
   Press the button. You should see `[brief] BRIEF ME` in the log.
4. Audio check: `speaker-test -t wav -c 2 -l 1`. To choose the output, use `raspi-config` -> System -> Audio, or right-click the volume icon.
   Bluetooth speaker: `bluetoothctl` -> `scan on` -> `pair XX:..` -> `connect XX:..` -> `trust XX:..`. Echo Dot: say "Alexa, pair Bluetooth".
5. Autostart (so it boots straight into the demo):
   ```bash
   # edit the IPs in both files first
   mkdir -p ~/.config/systemd/user ~/.config/autostart
   cp ~/firstin/hardware/pi/firstin-incab.service ~/.config/systemd/user/
   cp ~/firstin/hardware/pi/firstin-kiosk.desktop ~/.config/autostart/
   systemctl --user daemon-reload && systemctl --user enable --now firstin-incab
   loginctl enable-linger $USER
   journalctl --user -u firstin-incab -f      # logs
   ```
   Do not pass `--kiosk` to the service, because the `.desktop` file launches the kiosk inside the desktop session.
   On Bookworm with Wayland/labwc, if the `.desktop` entry doesn't start, add the same `chromium ... --kiosk URL &` line to `~/.config/labwc/autostart`.
   To exit the kiosk: Alt+F4 or `pkill chromium`.

## Hold-to-ask (optional stretch)

Hold BRIEF ME for more than 1 second. The unit records 5 seconds (`arecord` on the Pi, `sox rec` or `ffmpeg` on a Mac with `--mic`), transcribes it, then `POST /ask {plan_id, question}`, and speaks the `answer`.

Speech-to-text, first available wins:
1. **Vosk (offline, recommended for the Pi; works without WiFi to the internet):**
   ```bash
   pip3 install vosk --break-system-packages
   wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip vosk-model-small-en-us-0.15.zip
   python3 incab.py --vosk-model ~/vosk-model-small-en-us-0.15 ...
   ```
2. **OpenAI Whisper API:** `export OPENAI_API_KEY=...` (sends the 5 s WAV to `api.openai.com`).
3. Neither available: in sim mode you type the question. On a headless Pi it says "Sorry, I didn't catch that."

Mic check on the Pi: `arecord -l` (list devices), then `arecord -d 3 -f S16_LE -r 16000 /tmp/t.wav && aplay /tmp/t.wav`. If the USB mic isn't the default device, create `~/.asoundrc` with `defaults.pcm.card 1` and `defaults.ctl.card 1`.

## Audio and TTS fallbacks

- Brief audio (`audio_url`) is downloaded as soon as a plan arrives, so BRIEF ME is instant. It plays with `afplay` on macOS, otherwise `mpg123`, then `ffplay`, then `cvlc`.
- If there's no `audio_url` or the download fails, the unit speaks `voice_brief` with `espeak-ng`/`espeak`, then macOS `say`, then `pyttsx3`.
- The "new plan" beep is a generated WAV, so no asset files are needed.

## SenseCAP Indicator option (UNTESTED)

`sensecap/firstin_incab/firstin_incab.ino` is a best-effort Arduino sketch for the ESP32-S3 side of the Seeed SenseCAP Indicator. It joins WiFi, polls `/incab/active` every 2 s, flashes the screen on a new plan, and draws the card with Arduino_GFX (no LVGL, to keep it simple). The top user button (GPIO38) redraws the card.

- Arduino IDE: install the esp32 core (2.0.14 or later) and choose board **ESP32S3 Dev Module** with **PSRAM: OPI PSRAM**. Install the libraries **GFX Library for Arduino** and **ArduinoJson 7**.
- Copy `secrets.example.h` to `secrets.h` and set WiFi and the laptop IP.
- **Known gaps:** the pin map (RGB panel, PCA9535 expander for LCD CS/RST, backlight GPIO45) was taken from Seeed's examples and **must be verified** against https://wiki.seeedstudio.com/SenseCAP_Indicator_ESP32_Arduino/. The sketch has never been compiled. There is no audio, because the buzzer and Grove ports belong to the RP2040, so the voice brief must come from the Pi/laptop unit.
- If it takes more than 30 minutes, drop it and use the Pi kiosk. README section 8 already says this.

## Integration notes for the backend and web teams

- `/incab/active` should return **404 (or `{}`/`null`) when nothing is approved**. `incab.py` treats both as "no plan". A new `plan_id` is what triggers the LED, beep and card.
- `audio_url` must be an **absolute URL that the Pi can reach** (`http://<laptop-ip>:8000/static/out/...`). A `localhost` URL breaks on the Pi. A relative path such as `/static/...` also doesn't work yet. The unit falls back to TTS of `voice_brief` in both cases, so the demo still works.
- The web `/incab` page, when loaded on the Pi, must call the backend at the laptop's address and not at `localhost:8000`. For example, derive it from `window.location.hostname`.
- FastAPI must listen on `--host 0.0.0.0`, and CORS must allow the Pi's origin (for the kiosk page).
