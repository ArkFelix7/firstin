# FirstIn pitch video (2 min)

| File | What it is |
|---|---|
| `firstin-pitch-2min.mp4` | 1920x1080, 30 fps, H.264 crf 18, AAC 48 kHz. 2:01.8. Burned-in captions. The only audio is the real voice brief, so you can narrate live over it. |
| `firstin-pitch-2min-voiced.mp4` | Same picture, plus a synthetic narration track (macOS `say`, voice Samantha). **This is a fallback.** Use a human voice if you can. |
| `firstin-pitch-2min.srt` | The same captions as an SRT file, for Devpost and YouTube. |

## Rebuild

    agent/.venv/bin/python demo/video/build_pitch.py           # about 2 min
    agent/.venv/bin/python demo/video/build_pitch.py --sheet   # also writes build/contact-*.png (a frame every 2 s)

The build can be re-run safely. It reads `demo/SCRIPT.md` assets from `demo/press/`, keeps intermediates in `demo/video/build/`, and caches the `say` clips by their text. Voice and speed can be overridden with `PITCH_VOICE=... PITCH_SAY_RATE=...`. To refresh the zoomed-out map still, run `node demo/video/shot_map.mjs` with the web app running on :3000. Without it, the build falls back to the wide home screenshot.

This ffmpeg build has no drawtext or libass, so Pillow renders all text, using the Inter fonts in `demo/video/fonts/`. Captions are composited frame by frame.

## Segments

Times are output times. Each cut is a 0.4 s cross-fade (0.3 s inside the approve and in-cab beats).

| Time | Source | On screen | Caption (narration) |
|---|---|---|---|
| 0:00–0:14 | `press/collage-timeline.png` | Opens on Durham, Oct 2026 (right end), pans right to left across 2026 and 2025, then pushes in on the Houston, May 2013 NBC headline | Five weeks ago in Durham... / It keeps happening. / In Houston, in 2013... / Four firefighters never came out. |
| 0:14–0:25 | `press/clips/sfmo-fy13-08-finding1.png` | Full frame, slow push. A yellow marker sweeps over "no pre-fire plans" as the line is spoken (about 0:17) | The state fire marshal's first finding... / No site diagram... |
| 0:25–0:31 | `press/clips/niosh-f2007-18-preplan-form.png` | The handwritten form pans top to bottom. Beside it: "A real pre-plan. Charleston, 2006." | Plans like that come from an officer... / Nobody can walk every building. |
| 0:31–0:41 | `press/clips/recent-niosh-f2025-09-preplan-2026.png` | Marker sweeps over "no pre-incident plan was available" (about 0:34) and "three-ring binders" (about 0:37) | Last year a Georgia firefighter died... / The old ones sat in binders. |
| 0:41–1:19.6 | product demo 0:00–0:38.6 | Map, Generate, agent run, building, Matterport 360, access plan, verified height, verify-on-site checklist, Approve bar | Product lines from the 0:42 to 1:18 rows of SCRIPT.md |
| 1:19.2–1:20.6 | product demo 0:39.4–0:40.8 | The Approve and publish click | Nothing goes to a crew until an officer signs off. |
| 1:20.2–1:23.2 | `press/imessage/combined-real.png` | The real iPhone screenshots | Even from a text. |
| 1:22.9–1:23.9 | product demo 0:44.0–0:45.0 | "Approved by Capt. Station 12... Published to Engine 12" (the about 4 s publishing gap is cut) | none |
| 1:23.6–1:34.8 | product demo 0:46.5–0:51.95 + 0:56.30–1:02.10 | In-cab, Brief me. The brief plays from about 1:24.3 to 1:34.6, with a "Voice brief, played in the cab" label | **No caption.** Audio: "Engine 12, one-story industrial, built 1969, concrete tilt-up. Hazards: rooftop solar array, asbestos-containing materials, concrete tilt-up walls." It fades out over 0.4 s. |
| 1:34.4–1:52.8 | typeset slide | "Who pays" on off-white. Departments, Cities and How we sell each appear as their sentence starts | Fire departments already pay... / A city's insurance grade... / With our draft waiting... / We sell per building... |
| 1:52.4–1:56.2 | `assets/map-zoomed-out.png` (the live app, LA clusters) | Slow zoom out, with a card reading "3,288 buildings indexed. About 30 seconds each." | We've already indexed 3,288 buildings in Houston and LA. |
| 1:55.8–2:01.8 | `press/blowout/blowout.mp4`, in full | The firefighter blows out the flame, then the title card | The next crew should know the building... (the caption ends before the title fades in, at about 1:59.6) |

## Voice-brief cut

The full brief starts at demo 0:47.23. I timed its phrases with `silencedetect` and checked them against the brief text in `agent/out/la-002-576e4f4c/draft.json`. "concrete tilt-up walls." ends at demo 1:01.61, which is 14.4 s into the brief, more than the 10 s the script allows. So the cut also removes the middle sentence "Tenant MDB Transportation: possible high fire load, floor 1." (demo 0:51.95–0:56.30, which falls in the silences on both sides). What plays runs about 10.3 s and ends on "...concrete tilt-up walls". The in-cab screen doesn't change while the brief plays, so the splice can't be seen, apart from the header clock jumping a few seconds.

## Synthetic narration (fallback)

- Voice: **Samantha**. No Premium or Enhanced English voice is installed on this Mac. If you install "Ava (Premium)" or "Zoe (Premium)", rebuild with `PITCH_VOICE="Ava (Premium)"`.
- Rate: `say -r 182`. Speech runs at about 187 wpm while she is talking. With the pauses included, the narration averages about 150 wpm. At 170 wpm the cut would run about 2:06.
- Each caption chunk is synthesized on its own and placed at the caption's start. The brief audio is ducked by 14 dB wherever narration is active, but the schedule never overlaps them.
- Pronunciation fixes: "Nyosh" for NIOSH, "Fema", "Co-Star", "L.A.", and "thirty-two eighty-eight" for 3,288. The captions keep the written forms.
- Levels (`volumedetect`): speech sections average about -20 dB, peaks reach -2.9 dB, and the brief sits at the same level as the narration.

No music or ambient bed. Silence was the better choice.
