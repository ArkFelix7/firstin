# Recording the FirstIn demo video

`walkthrough.mjs` drives the real product in Chrome for the 0:42 to 1:32 part of `demo/SCRIPT.md` (map, Generate, live trace, Building, Stairwell 360, Roof access, height check and Verify on site, approval, in-cab Brief me). It shows a visible cursor dot and a short orange ring on every click, and it prints each narration line in the terminal as a teleprompter. You record the screen and read the lines. The press, slide and closing parts are edited in afterwards.

## 1. Before you record

1. **Backend.** From the repo root, start it in real agent mode with no auto-reload:
   ```bash
   make stage
   curl -s localhost:8000/health   # expect "mode":"agent"
   ```
   Don't restart the backend while the walkthrough is running. A restart drops the run, and the script will warn "run ... is unknown to the backend".
2. **Web.** In a second terminal:
   ```bash
   cd web && pnpm dev               # http://localhost:3000
   ```
   Open http://localhost:3000 once in any browser so Next.js compiles `/`, `/plan` and `/incab`. Otherwise the first navigation in the take stalls.
3. **Photon (only for `--imessage`).** The bridge must be running on :8010 (`curl localhost:8010/health`). Every run, including the prewarmed one, texts the phone "pre-plan ready for approval".
4. **Mac.** Turn on Do Not Disturb, quit Slack and Messages on the Mac, set the volume to about 50% and use speakers, not headphones (see the audio notes below). Close other Chrome windows that might come to the front.

## 2. Run it

Run these from the repo root (`firstin/`):

```bash
# Default. Press Enter in the terminal for each beat. A fresh run is prewarmed and
# the UI's Generate click is routed to it. UI approval.
node demo/record/walkthrough.mjs

# Hands-off. Beats fire on SCRIPT.md timing with a countdown in the terminal.
node demo/record/walkthrough.mjs --auto

# Approve from the phone instead. The script waits until the run is APPROVED.
node demo/record/walkthrough.mjs --imessage
```

| Option | What it does |
|---|---|
| `--step` (default) / `--auto` | You set the pace with Enter, or the script follows the beat times in SCRIPT.md. |
| `--prewarm` (default), `--lead 20` | Starts a la-002 run in the background `lead` seconds before the Generate click. Then the page replays the first part of the trace and the rest (hazard reasoner, validator, steps checking off, the plan filling in) animates live. With 20 s the plan lands at about 0:53. A smaller lead shows the analysts running for longer, but the Building beat then waits for the plan. |
| `--live` | No prewarm. The Generate click starts a real run, and the Building beat waits about 25 s for the plan. |
| `--run <run_id>` | Reuses an existing run that is still awaiting approval. The trace replays instantly, so nothing animates. |
| `--size 1920x1080` | Page size. `auto` (the default) uses 1920x1080 if the screen fits it, otherwise 1440x810. Both are 16:9. The built-in Retina screen gives 1440x810 at 2x, which is a 2880x1620 recording. |
| `--fullscreen` | macOS full screen with no title bar. The page is the whole screen, which is 16:10 on a MacBook. |
| `--shots <dir>` | Saves a screenshot at the end of every beat. Use it for dry runs. |
| `--close` | Closes Chrome at the end instead of waiting for Enter. |

The script opens a clean Chrome app window with no tabs, address bar or "controlled by automated software" bar. It uses a throwaway profile and allows autoplay. It then loads the map with 1601 Perrino Pl selected and prints the exact screen rectangle of the page, for example `x 0, y 66, 1440 x 810 points`.

**Flow:** start the screen recording, click into the terminal, then press Enter. In the default prewarm mode the terminal counts down about 15 s ("Agent warming up") while the run gets a head start. Start reading when the 0:42 line appears. In step mode, press Enter when you finish each line. The prompt for the Building and Approve beats shows the run's age. At the end the script prints a table of beat times against SCRIPT.md, and whether the brief audio played.

## 3. Screen recording (Cmd+Shift+5)

1. Press Cmd+Shift+5 and choose **Record Selected Portion** (the dashed rectangle with a dot). macOS can't record a single window, so drag the rectangle exactly over the page area the script printed, just below the Chrome title bar. A few pixels over is fine, because you crop in the editor.
2. In **Options**:
   - **Microphone:** "MacBook Pro Microphone", or your USB or lav mic.
   - **Timer:** None.
   - **Show Mouse Clicks:** off. The script draws its own cursor dot and click rings, and the real pointer may not show in the recording.
   - **Remember Last Selection:** on, so a retake uses the same rectangle.
   - **Save to:** Desktop or Movies.
3. Click **Record**, then click into the terminal and press Enter.
4. To stop, click the stop button in the menu bar or press Cmd+Ctrl+Esc.

**Audio:** the Cmd+Shift+5 tool records the microphone only, never system audio. The 8-second voice brief reaches the take only through the speakers and the mic, so use speakers, not headphones. For a clean version, download the brief and lay it on its own track in the edit:
```bash
curl -s localhost:8000/incab/active | python3 -c 'import sys,json;print(json.load(sys.stdin)["audio_url"])' | xargs curl -so ~/Desktop/brief.mp3
```
If you use the clean file, turn the take's audio down to zero during the brief so you don't hear it twice.

## 4. Assemble the video (iMovie or CapCut)

Use a 16:9 project at 1080p and 30 fps. Times follow `demo/SCRIPT.md`.

| Time | Clip | Notes |
|---|---|---|
| 0:00 to 0:14 | `demo/press/collage.png` | Still image. In iMovie use Crop, then Ken Burns: start wide and end on the NBC headline. In CapCut add keyframes on scale. |
| 0:14 to 0:26 | `demo/press/clips/sfmo-fy13-08-finding1.png` | Full frame. Add a highlight box or rectangle over "no pre-fire plans". |
| 0:26 to 0:36 | `demo/press/clips/niosh-f2007-18-preplan-form.png` | Caption: "A real pre-plan. Charleston, 2006." |
| 0:36 to 0:42 | Quote slide (Keynote, exported as an image) | "Many fire departments are unable to pre-plan for all the structures within their jurisdiction." NIOSH, 2025 |
| 0:42 to 1:32 | **Your screen recording** | Trim the countdown off the front. Cut the dead air after Approve while it publishes, about 7 s with the spinner on the button. Keep the in-cab brief playing in full. |
| 1:32 to 1:52 | Business slide (Keynote) | Three lines from SCRIPT.md. |
| 1:52 to 1:55 | Map zoomed out over LA | A screenshot or a 3 s recording of http://localhost:3000 zoomed out, with the caption "3,288 buildings indexed. About 30 seconds each." |
| 1:55 to 2:00 | `demo/press/blowout/blowout.mp4` | 1920x1080, about 5.0 s. Let it run under the last line, and hold the final frame. If you're short on time, `blowout-final.png` or `blowout-still.png` works as a still. |

**Narration for the press part (0:00 to 0:42):** in iMovie use Window > Record Voiceover, and in CapCut use the mic button above the timeline. Read those lines over the stills. The product part already has your voice from the screen recording.

**iMovie:** File > New Movie, then drag the files into the timeline. If the 2880x1620 recording has a sliver of title bar, use Crop > Fill. To export, choose File > Share > File, set Resolution to 1080p and Quality to High, and choose Compress: Better Quality.

**CapCut:** New project, then set the canvas to 16:9. Import and arrange the clips. To export, set Resolution to 1080p, Frame rate to 30 fps, and Format to MP4.

## Troubleshooting

- **Building beat waits a long time.** The agent is slower than usual, and the beat waits up to 90 s for the plan. Raise `--lead` (for example `--lead 25`) or use the timing table to see where the time went.
- **"run ... is unknown to the backend".** The backend restarted after the run started. Run the walkthrough again.
- **The viewport warning says the window is too small.** Hide the Dock or pass `--size 1280x720`.
- **No sound from Brief me.** Check the summary line ("audio: played brief.mp3") and the Mac's output volume. Autoplay is already allowed by the launch flags.
- **The map tiles are blank on the first load.** The web dev server was still compiling. Reload once before recording, or run it again.
