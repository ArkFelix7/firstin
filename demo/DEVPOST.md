# Devpost submission

Paste each section into the matching Devpost field. Sources for every number are in `demo/STORY.md`.

---

**Project name:** FirstIn

**Elevator pitch (200 characters max):**
FirstIn writes the fire pre-plan before anyone walks the building: CoStar, Vexcel and Matterport data, a source on every line, an officer's sign-off, and a spoken brief in the cab.

---

## Inspiration

On May 31, 2013, four Houston firefighters were killed when the roof of a burning restaurant on the Southwest Freeway collapsed, twelve minutes after the first engine arrived. A fifth died of his injuries in 2017. The Texas State Fire Marshal's first finding was: "There were no pre-fire plans of this structure... no indication of a record of a site diagram, fire protection systems, or construction methods."

It keeps happening. In September 2025 a Georgia firefighter died in a warehouse where, NIOSH found, "no pre-incident plan was available for crews to view enroute or on arrival." In October 2026 a roof collapse in Durham, North Carolina killed a 24-year-old firefighter searching a burning building.

A pre-incident plan is the document that tells a crew how a building is built, where the stairs and standpipes are, what the tenants store and how to reach the roof, before they get there. Departments make them by walking buildings, and they can't walk them all. NIOSH said so in a 2025 fatality report: "many fire departments are unable to pre-plan for all the structures within their jurisdiction." Plano Fire-Rescue had plans for 1,087 of 2,345 target buildings.

Meanwhile, the facts a pre-plan needs already exist, spread across CoStar's property and tenant records, Vexcel's aerial imagery and Matterport's 3D scans. Nobody had pointed them at the fire service.

## What it does

An officer picks a building in Houston or Los Angeles. In about 30 seconds, FirstIn writes an NFPA 1660-structured pre-incident plan:

- **Building and occupancy (CoStar).** Year built, construction, stories, area, sprinklers, loading docks, electrical service, and every tenant with their industry and headcount.
- **Roof, access and exposures (Vexcel).**
  - Roof type, condition, rooftop solar, and height from the elevation model.
  - The specific walls a ladder truck can reach, drawn on the building outline.
  - A staging area on open pavement.
  - Neighboring buildings with distances.
  - Doors and dock doors spotted in the angled aerial photos.
- **Interior (Matterport).** Stairs, mezzanines, utility rooms and storage seen in 360° scans, with a box drawn on the image.
- **Hazards.** A rule table (tenant industry, construction era, roof, interior) plus up to three model-added hazards. Each one shows the facts it was derived from.

Every line cites its source. Where two sources measure the same thing, FirstIn checks them against each other: at 10940 Wilshire, CoStar's 24 floors at 12 feet give 87.8 m, and Vexcel's elevation model gives 87.2 m. Anything it can't source is marked VERIFY ON SITE and becomes the officer's walk-through checklist.

Nothing reaches a crew until an officer approves it, from the dashboard or by replying APPROVE to an iMessage. The approved plan goes to the engine's in-cab screen as a one-page sheet and a 20-second spoken brief. A firefighter can ask "where's the standpipe?" and get an answer drawn only from the approved plan.

We indexed 3,288 buildings, every CoStar commercial property in Houston and LA with a Matterport scan. Prepared buildings take about 30 seconds and any other building about 50 seconds, generated live.

## How we built it

- **Agent.** LangChain deepagents.
  - A planner writes NFPA 1660 sections as todos and sends three analysts out in parallel (CoStar, aerial, interior), then a hazard reasoner and a validator.
  - Tools write evidence to the agent's virtual filesystem (`/evidence/<source>/<tool>.json`) and the plan to `/plan/final.json`.
  - `interrupt_on={"publish_preplan": True}` with a LangGraph checkpointer is a real human-in-the-loop gate. The dashboard or an iMessage reply resumes it.
- **Models.** Claude Sonnet 5.5 for planning, and for vision on Vexcel orthos and obliques and on Matterport panoramas. We stitched the panoramas from Matterport's six-face skyboxes into equirectangular images.
- **Access geometry.**
  - **Walls:** the ladder walls come straight from Vexcel's building footprint. The model decides which walls are reachable, and a second vision pass checks the drawing.
  - **Staging:** code proposes candidate staging rectangles, rejects any that overlap the building, and has the model classify the ground under the rest.
  - **Doors:** doors found in the obliques are mapped back onto the footprint and compared with CoStar's dock count.
- **Data.**
  - The CoStar hackathon kit (commercial property, location occupancy and company detail, joined by PropertyId).
  - Vexcel API v2: ortho and oblique extracts, AI roof attributes, and surface and terrain elevation.
  - Matterport GraphQL: floors, rooms, sweeps, skyboxes and floor plans.
  - CoStar's MatterportModelId links all three for the same building.
- **Trust.** A deterministic validator enforces cite-or-flag on every field. Officer edits are cited to the officer.
- **Backend.** FastAPI with Server-Sent Events for the live trace, reportlab for the PDF, and macOS TTS for the brief. An offline mode replays cached real runs, so the demo survives bad Wi-Fi.
- **Frontend.** Next.js, MapLibre with clustering for the 3,288 buildings, and photo-sphere-viewer for the scans.
- **Messaging.** A Photon v2 iMessage bridge. The officer gets the summary and top hazards, replies APPROVE or REJECT, or asks a question.

## Challenges we ran into

- **Making the agent say "I don't know."** The validator, the cite-or-flag rule and the VERIFY ON SITE checklist were more work than the parts that find things.
- **Finding the right building.** Census geocoding put pins 30 to 210 meters off, on the wrong building. We switched to Matterport's geolocation and CoStar's coordinates, and cross-check the measured height against CoStar.
- **Access accuracy.** Our first version drew one loose box for both roof access and staging. We rebuilt it so the walls come from the measured footprint, and a second vision pass rejects anything that doesn't hold up, such as a "staging area" that turned out to be landscaping.
- **Speed.** The first real agent run took three minutes because the model was hand-editing JSON. Moving evidence writes into the tools and plan assembly into code brought it to about 30 seconds.
- **False hazards.** Matterport's automatic room labels are often wrong for commercial space ("lobby" for a gym). Tenant keyword rules flagged a coffee importer as a restaurant. We now treat auto labels as low confidence and only match hazard rules on a tenant's actual industry.

## Accomplishments that we're proud of

- A complete cited pre-plan in about 30 seconds, from three independent data sources.
- An officer approved a real plan from an iPhone by iMessage, and it appeared on the in-cab screen with its spoken brief.
- Independent sources agreeing with each other: CoStar and Vexcel heights within 1%, and both reporting the same rooftop solar. A pre-planner standing in the parking lot can't do that check.

## What we learned

- In safety work, people trust a source more than a confident sentence. The most useful thing the model does is decline to answer when it has nothing to cite.
- The investigation reports were the best product spec we found. NIOSH's recommended pre-plan checklist after the Houston fire reads almost exactly like our schema.

## What's next for FirstIn

- **Department pilots.** We want the ten-minute "confirm the draft" walk-through, with VERIFY ON SITE items checked off on a phone.
- **Platform integration.** An API into First Due, ImageTrend and FlowMSP, and Tablet Command, so plans appear where crews already look.
- **Change detection.** A new tenant in CoStar or a new aerial capture triggers a plan refresh.
- **District coverage.** A dashboard of how many target occupancies have a current plan.

## Built with

python, fastapi, langchain, deepagents, langgraph, anthropic, claude, nextjs, typescript, tailwindcss, maplibre, photo-sphere-viewer, reportlab, photon, imessage, costar, vexcel, matterport

## Links

- Code: https://github.com/ArkFelix7/firstin (make public before submitting)
- Demo video: (add link)

## Tracks

- **Main track:** Healthcare (public safety and emergency response). Confirm with an organizer; the fallback is Business & Enterprise.
- **CoStar:** Inside and Out, AI for the Built World
- **LangChain:** Best Use of Deepagents
- **Photon:** Messaging Agent
- **Amazon:** Practical AI

## Who pays (for the "business" question in judging)

- **Departments already buy pre-plan software.** Reno paid First Due $42,329.91 and Sparks $27,562.50 for a year, from E911 funds. FEMA Fire Prevention and Safety grants list pre-planning software as eligible.
- **Cities have an insurance reason.** ISO's Public Protection Classification gives 12 of 100 training points to pre-fire planning inspections of every commercial building, annually. ISO says insurance is "substantially lower" in well-graded communities. FirstIn turns that annual walk into a confirmation pass.
- **Pricing.** About $10 to $15 per commercial building per year, sold through the platforms departments already use. That puts the US fire-service market at about $40 to $60M a year.
- **For CoStar.** Once the Vexcel acquisition closes (expected Q1 2027), CoStar will own the inside, outside and occupants of the same building. Vexcel already sells to insurance underwriters, the next buyer for these cited hazard fields.
