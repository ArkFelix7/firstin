## Inspiration

On May 31, 2013, Houston firefighters went into a burning restaurant on the Southwest Freeway. Twelve minutes after the first engine arrived, the roof came down. Four of them never came out, and a fifth died of his injuries in 2017. The Texas State Fire Marshal's first finding was short: *"There were no pre-fire plans of this structure... no indication of a record of a site diagram, fire protection systems, or construction methods."*

We assumed that was history. It isn't. In September 2025 a Georgia firefighter died in a warehouse where, NIOSH found, *"no pre-incident plan was available for crews to view enroute or on arrival."* The plans that department did have sat in three-ring binders. Five weeks ago in Durham, North Carolina, a roof collapse killed a 24-year-old firefighter searching a burning building.

A pre-incident plan tells a crew how a building is built, where the stairs and standpipes are, what the tenants store and how to reach the roof, before they get there. Departments make them by walking buildings with a clipboard, and they can't walk them all. NIOSH wrote it plainly in 2025: *"many fire departments are unable to pre-plan for all the structures within their jurisdiction."* Plano Fire-Rescue had plans for 1,087 of 2,345 target buildings.

The facts a pre-plan needs already exist. CoStar knows who is inside a building and how it was built. Vexcel can see the roof, the solar panels and the street a ladder truck would park on. Matterport has scanned the stairs and the storage floor. Nobody had pointed any of it at the fire service.

## What it does

An officer picks one of 3,288 indexed buildings in Houston or Los Angeles. About 30 seconds later FirstIn has written an NFPA 1660-structured pre-plan where every line cites its source: a CoStar record and field, a box on a Vexcel aerial tile, or a box on a Matterport 360° scan. Anything it can't source is marked **Verify on site** and becomes the officer's walk-through checklist. Nothing reaches a crew until an officer approves it, from the dashboard or by replying APPROVE to an iMessage. The approved plan lands on the engine's in-cab screen with a 20-second spoken brief.

## How we built it

- **Agent:** LangChain **deepagents**. A planner writes the NFPA 1660 sections as todos and sends three analysts out in parallel (CoStar, aerial, interior), followed by a hazard reasoner and a validator. Tools write their evidence to the agent's virtual filesystem, and the plan is assembled in code, so the model never retypes a fact. Publishing is gated by `interrupt_on={"publish_preplan": True}` with a LangGraph checkpointer, which gives a real human-in-the-loop pause that only an officer can resume.
- **Models:** Claude Sonnet 5.5 for planning and for vision on Vexcel orthos and obliques, and on Matterport panoramas we stitched from six-face skyboxes.
- **Data:** the CoStar hackathon kit (property, occupancy and company records), **Vexcel API v2** (ortho and oblique imagery, AI roof attributes, surface and terrain elevation), and **Matterport GraphQL** (floors, rooms, sweeps, skyboxes). CoStar's Matterport model IDs tie all three to the same building.
- **Access geometry:** ladder-access walls come straight from Vexcel's measured footprint. The model only decides which walls are reachable. Code proposes staging rectangles and rejects any that overlap the building. Doors found in oblique photos are projected back onto the footprint. A second vision pass checks every drawn element and drops what fails.
- **Cross-checks:** when two sources measure the same thing, we compare them. At 10940 Wilshire, CoStar gives 24 floors × 12 ft = 87.8 m and Vexcel's elevation model gives 87.2 m, about 99% agreement.
- **App:** FastAPI with Server-Sent Events for the live agent trace; a Next.js dashboard with MapLibre and photo-sphere-viewer; reportlab for the one-page PDF; a **Photon v2** iMessage bridge for approval and questions; and an in-cab view designed like a fire-truck terminal.

## Challenges we ran into

- **Teaching it to say "I don't know."** The validator and the Verify on site checklist took more work than the parts that find things. An empty field with an honest label is worth more to a crew than a confident guess.
- **Finding the right building.** Census geocoding put our pins 30 to 210 meters off; for one tower it landed on a one-story shop. We switched to Matterport and CoStar coordinates and cross-check heights to catch the rest.
- **Access that was actually right.** Our first version drew one loose box for both roof access and staging. We rebuilt it on the measured footprint with a verification pass, which rejected a "staging area" that turned out to be landscaping.
- **Speed.** The first real agent run took three minutes because the model was hand-editing JSON. Moving evidence writes into the tools and plan assembly into code brought it to about 30 seconds.
- **False hazards.** Tenant keyword rules flagged a coffee importer as a restaurant and a cleaning company called "Coconut" as food service. A 2021 renovation date made a 1930s concrete building look like lightweight truss construction. Every one of those taught us to make a rule cite real evidence, never the year or a word match alone.

## What we learned

- In safety work, trust comes from provenance and a human signature, not from model confidence. The most useful thing our model does is decline to answer when it has nothing to cite.
- The fire investigation reports were the best product spec we found. NIOSH's recommended pre-plan checklist after the Houston fire reads almost exactly like our schema.
- Real data is messy in useful ways. When CoStar and Vexcel disagree about a building's height, that disagreement is itself information an officer should see.

## What's next

Department pilots built around a ten-minute "confirm the draft" walk-through, an API into First Due, ImageTrend and Tablet Command so plans show up where crews already look, and change detection, so that a new tenant in CoStar or a new aerial capture refreshes the plan automatically.
