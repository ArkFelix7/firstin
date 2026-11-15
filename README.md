# FirstIn

**Know the building before you're inside it.**

FirstIn writes firefighter pre-incident plans automatically. An AI agent reads three data layers for the same building: CoStar property and tenant records, Vexcel aerial imagery, and Matterport 3D scans. It assembles an NFPA 1660-structured plan in which every field cites its source. Fields with no evidence are marked **VERIFY ON SITE** instead of guessed. A fire officer approves the plan on the dashboard or by iMessage, and it is then published to the engine's in-cab display as a one-page PDF and a 20-second voice brief.

HackPrinceton Fall 2026. Tracks: CoStar *AI for the Built World*, LangChain *Best use of deepagents*, Photon *Messaging agent*, Amazon *Practical AI*.

## Why

Pre-plans tell crews where the stairs, standpipes, hazards and roof access are before they go in. Departments document coverage of only a fraction of their buildings: Plano 1,087 of 2,345 and New Castle County 1,200 of 6,000, per FEMA EFO papers. After the 2007 Charleston Sofa Super Store fire killed nine firefighters, NIOSH noted that the store's pre-plan "did not note any unusual hazards." The forms are already digital. Collecting the data is the bottleneck, and that is what FirstIn automates.

## What it does

1. **Pick a building** on the map (Houston or Los Angeles).
2. **The agent plans and fans out.** A deepagents planner splits the job into NFPA 1660 sections and runs three analysts in parallel:
   - **CoStar analyst:** year built, construction, stories, area, sprinklers, loading docks, electrical service, tenants with industry and headcount.
   - **Aerial analyst (Vexcel + vision):** roof type and condition, rooftop solar, footprint, height from the surface model, staging, access roads, exposures, with bounding boxes on the tile.
   - **Interior analyst (Matterport + vision):** stairs, mezzanines, utility rooms, storage, fire protection seen in 360° panoramas, with the box drawn on the pano.
3. **Hazard reasoner.** A seed rule table (tenant industry, construction era, roof, interior observations) plus up to three model-added hazards, each with the chain of cited facts it came from.
4. **Cross-check.** CoStar height and Vexcel surface-model height are compared. Example: The Tower, 10940 Wilshire, CoStar 24 floors x 12 ft = 87.8 m vs Vexcel 87.2 m, 99% agreement.
5. **Validator.** Any leaf without a citation becomes VERIFY ON SITE, which doubles as the walk-through checklist.
6. **Human in the loop.** The agent's `publish_preplan` call is interrupted until an officer approves, edits or rejects, from the dashboard or by replying APPROVE over iMessage (Photon).
7. **Publish.** A one-page tactical PDF, a ~20-second voice brief, and the in-cab display (`/incab`) with a BRIEF ME button and spoken Q&A answered only from the approved plan.

Example brief (1601 Perrino Pl, Los Angeles):

> Engine 12, one-story industrial, built 1969, concrete tilt-up. Tenant MDB Transportation: possible high fire load, floor 1. Hazards: rooftop solar array, asbestos-containing materials, concrete tilt-up walls. Two stairs in the scan. Roof access: southwest long side; solar PV on roof. Exposure south: commercial building, 64 feet.

## Architecture

```
web/ (Next.js)  ── SSE trace, plan, evidence, approve ──►  agent/ (FastAPI + deepagents)
                                                            ├─ planner (write_todos, NFPA sections)
                                                            ├─ costar-analyst     → CoStar kit
                                                            ├─ aerial-analyst     → Vexcel API v2 + Claude vision
                                                            ├─ interior-analyst   → Matterport GraphQL + Claude vision
                                                            ├─ hazard-reasoner    → hazards.yaml rules + model
                                                            ├─ validator          → cite-or-flag
                                                            └─ interrupt_on publish_preplan → officer
photon/ (Photon v2 iMessage bridge) ◄── notify / APPROVE / Q&A ──► agent/
/incab (browser or Raspberry Pi kiosk, hardware/) ◄── GET /incab/active
```

Evidence is written to the agent's virtual filesystem (`/evidence/<source>/<tool>.json`) and the plan to `/plan/draft.json` and `/plan/final.json`. The API contract is in [CONTRACTS.md](CONTRACTS.md).

## Run it

Requirements: Python 3.12 (via uv), Node 20+, pnpm. Copy `.env.example` to `.env` and fill in the sponsor keys and `ANTHROPIC_API_KEY`. Put the CoStar hackathon kit in `agent/data/costar/kit/`. It is proprietary and git-ignored.

Sponsor data (imagery, scans, CoStar-derived registry) is not committed. Rebuild it locally with your own keys:

```bash
agent/.venv/bin/python -m agent.scripts.registry_build                 # building registry from the CoStar kit
agent/.venv/bin/python -m agent.scripts.registry_precache la-002 ...   # Matterport + Vexcel caches
make warm-vision                                                       # cached vision answers
```

```bash
make venv                 # Python env
make stage                # backend on :8000 (real agent; no auto-reload)
# or: make stage-offline  # replays cached real runs, no network needed
cd web && pnpm install && pnpm dev          # dashboard on :3000
cd photon && npm install && npm start       # optional: iMessage approval on :8010
```

Open http://localhost:3000, pick a building and generate a pre-plan. The in-cab view is http://localhost:3000/incab.

Other targets: `make test`, `make warm-vision` (caches vision answers so offline replays use real model output), `make backend` (dev with reload).

## Repo layout

| Path | What |
|---|---|
| `agent/` | FastAPI server, deepagents agent, deterministic offline pipeline, tools, prompts, hazard rules, tests |
| `agent/tools/` | `costar.py`, `vexcel.py`, `matterport.py`, `vision.py`, `hazard_rules.py`, `validator.py`, `render.py` (PDF, TTS) |
| `web/` | Next.js dashboard: map, live agent trace, plan sheet, evidence viewer, approval, `/incab` |
| `photon/` | Photon v2 iMessage bridge: approval requests, APPROVE/REJECT, Q&A |
| `hardware/` | Raspberry Pi in-cab client (button, LED, speaker) and an untested ESP32 SenseCAP sketch |
| `demo/` | Screenshots and the screenshot PDF builder |

## Honest limits

- Plans are decision support, not authority. Nothing publishes without an officer.
- Matterport scans usually cover one suite, not a whole building, and auto room labels are often wrong for commercial space; the agent treats them as low confidence and checks against the panorama.
- Building lat/lng comes from Matterport geolocation; census geocoding was 30 to 210 m off.
- Coverage figures cited above are from individual departments' EFO papers, not a national census.

## Built with

Python, FastAPI, LangChain deepagents, LangGraph, Claude (Sonnet 5.5, vision), Next.js, MapLibre, photo-sphere-viewer, reportlab, Photon, CoStar, Vexcel, Matterport.
