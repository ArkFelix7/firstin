# Devpost submission draft

**Project name:** FirstIn
**Tagline:** Know the building before you're inside it.

## Inspiration
In 2007, nine Charleston firefighters died in the Sofa Super Store fire. NIOSH later noted that the department's pre-plan for the building "did not note any unusual hazards." Pre-incident plans tell a crew where the stairs, standpipes, hazards and roof access are before they go in, yet departments report plans for only a fraction of their buildings (Plano: 1,087 of 2,345; New Castle County: 1,200 of 6,000, per FEMA Executive Fire Officer papers). Software already digitized the form. The data collection is still a person walking the building with a clipboard.

CoStar now owns tenant records (CoStar), aerial imagery (Vexcel) and 3D interiors (Matterport) for the same buildings. That is most of a pre-plan, sitting in three APIs.

## What it does
An officer picks a building in Houston or Los Angeles. About 30 seconds later FirstIn has written an NFPA 1660-structured pre-incident plan in which every field cites its source: a CoStar record and field, a Vexcel tile with a bounding box, or a Matterport scan with a box on the 360° panorama. Anything without evidence is marked VERIFY ON SITE, never guessed, and becomes the walk-through checklist.

The officer reviews it on the dashboard or by iMessage, edits if needed and approves. The plan is then published as a one-page tactical PDF and a 20-second voice brief to the engine's in-cab display, where a crew member can ask "where's the standpipe?" and get an answer drawn only from the approved plan.

For 1601 Perrino Pl in Los Angeles, the agent found:
- a 1969 concrete tilt-up warehouse with 11 dock doors and 480 V three-phase service (CoStar);
- a logistics tenant and a grocery and health-and-beauty wholesaler (CoStar);
- rooftop solar and roof ponding (Vexcel);
- pallets of boxed product and an open steel mezzanine stair (Matterport).

It cross-checked the building height between CoStar and Vexcel's surface model, and flagged hydrants, FDC and sprinklers for verification.

## How we built it
- **Agent:** LangChain deepagents. A planner writes NFPA 1660 todos and fans out three analysts in parallel (CoStar, aerial, interior), followed by a hazard reasoner and a validator. Tools write evidence to the agent's virtual filesystem (`/evidence/<source>/<tool>.json`); the plan is assembled to `/plan/final.json`. `interrupt_on={"publish_preplan": True}` with a LangGraph checkpointer gives a real human-in-the-loop gate, resumed by the dashboard or by an iMessage reply.
- **Models:** Claude Sonnet 5.5 for planning and for vision on Vexcel orthos and obliques and on Matterport panoramas (stitched from the GraphQL skybox faces into equirectangular images).
- **Data:**
  - CoStar hackathon kit: commercial property, location occupancy and company detail, joined by PropertyId.
  - Vexcel API v2: ortho and oblique extracts, AI property attributes (roof material, condition, defects, solar) and DSM/DTM elevation for height.
  - Matterport GraphQL: floors, rooms, sweeps, skyboxes, floorplans.
  - All three are linked by CoStar's MatterportModelId.
- **Trust:** a deterministic validator enforces cite-or-flag on every leaf. A seed hazard table (tenant industry, construction era, roof, interior) runs before the model may add up to three cited hazards. CoStar and Vexcel heights are cross-checked (The Tower at 10940 Wilshire: 87.8 m vs 87.2 m). Officer edits are cited to the officer.
- **Backend:** FastAPI with Server-Sent Events for the live trace. reportlab renders the PDF and macOS TTS the brief. A deterministic offline mode replays cached real runs, so the demo survives bad Wi-Fi.
- **Frontend:** Next.js, MapLibre, photo-sphere-viewer. It shows the live trace, the plan sheet, an evidence viewer with boxes, and approve/edit/reject.
- **Messaging:** Photon v2 iMessage bridge. The officer receives the summary and top hazards, replies APPROVE or REJECT, or asks questions.

## Challenges
- Fusing tabular records, aerial pixels and 3D scans into one plan where every claim can be traced back to its source.
- Getting the agent to say "I don't know." VERIFY ON SITE is a feature, not a failure.
- Geocoding: census coordinates were 30 to 210 m off and picked the wrong building, so we use Matterport geolocation, which landed inside the right footprint every time.
- Latency: the first real agent run took 3 minutes because the model hand-edited JSON. Moving evidence writes into the tools and plan assembly into code brought it to about 30 seconds.
- Matterport auto room labels are often wrong for commercial space ("lobby" for a gym), so the agent treats them as low confidence and checks the panorama.

## Accomplishments
- A full cited pre-plan in about 30 seconds, from three independent data sources.
- An officer approved a real plan from an iPhone over iMessage, and it appeared on the in-cab display.
- Independent sources agreeing (CoStar vs Vexcel height, both reporting rooftop solar) is the kind of cross-validation a human pre-planner can't do from a parking lot.

## What we learned
In safety-critical AI, trust comes from provenance and human approval, not from model confidence.

## What's next
- District-wide batch generation and a coverage dashboard ("62% of critical occupancies pre-planned, now 100%").
- Change detection: a new tenant in CoStar or a new aerial capture triggers a plan refresh.
- A field-confirm mode where the officer checks off VERIFY ON SITE items on a phone.
- An API for fire-software platforms such as First Due, ESO and ImageTrend.

## Built with
python, fastapi, langchain, deepagents, langgraph, anthropic-claude, nextjs, typescript, maplibre, photo-sphere-viewer, reportlab, photon, costar, vexcel, matterport

## Tracks
- Main: Healthcare (emergency response and public safety). Confirm with organizers; fallback: Business & Enterprise.
- CoStar: Inside and Out, AI for the Built World
- LangChain: Best use of deepagents
- Photon: Messaging agent
- Amazon: Practical AI
