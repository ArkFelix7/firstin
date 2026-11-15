# FirstIn: the story

This is the long version, for the presenters. The 2-minute cut is in `SCRIPT.md`. Every number has a source at the bottom. Research notes are in `research/fires.md` and `research/market.md`, and the clippings are in `press/`.

---

## 1. Houston, May 31, 2013

Just after noon, a fire started in the attic over the kitchen of Bhojan, an Indian restaurant attached to the Southwest Inn at 6855 Southwest Freeway. It burned in the space above the ceiling for a long time before anyone called 911 [F1].

Houston firefighters went inside to find it. Twelve minutes after the first engine arrived, the roof came down [F2]. Captain Matthew Renaud, Engineer Operator Robert Bebee, Firefighter Robert Garner and Probationary Firefighter Anne Sullivan were killed. Captain Bill Dowling was critically injured and died of complications in 2017 [F2][F5]. At least 14 more firefighters were hurt; the reports put the count between 14 and 16 [F2][F3][F4]. The mayor called it the worst day in the history of the Houston Fire Department [F4].

The building was a 1966 wood-frame structure with no sprinklers. It had been re-roofed and extended over the years, and its roof carried concrete tile [F2][F3]. The crews had no record of any of that.

The Texas State Fire Marshal's first finding:

> "There were no pre-fire plans of this structure. The Houston Fire Department had responded to this location in the past but there is no indication of a record of a site diagram, fire protection systems, or construction methods." [F3]

NIOSH's investigation said the same thing in its own words:

> "At this incident, there was no information available for first due or first alarm companies due to the fact this occupancy was not considered a high-risk occupancy." [F2]

> "Pre-incident information, pre-fire plans and building knowledge are mission critical." [F2]

Two things we never say, because the investigations don't support them:
- **That the crew made a mistake.** The fire marshal found they did not fail to perform as trained.
- **That the tiles caused the collapse.** The city's engineers attributed the failure to fire exposure. What we say is that the crew had no record of how the roof was built.

## 2. It keeps happening

**Charleston, 2007.** Nine firefighters died at the Sofa Super Store. NIOSH reproduced the department's handwritten pre-plan for the building: one page, roof type "Comp.", sprinklers "N/A". NIOSH wrote that the form "did not mention the large volume of furniture and flammable materials (fuel load) contained in the structure" [F6]. The clipping of that form is in `press/clips/niosh-f2007-18-preplan-form.png`.

**South Carolina, 2025.** A 25-year-old firefighter died in a lightweight-construction collapse. NIOSH: "many fire departments are unable to pre-plan for all the structures within their jurisdiction," and "the use of technology and programs can assist fire departments in conducting pre-incident planning" [M34].

**Georgia, 2025.** A firefighter became disoriented and died in a commercial warehouse. NIOSH: "no pre-incident plan was available for crews to view enroute or on arrival." The plans the department did have were kept "in three-ring binders" on the trucks [M40].

**Los Angeles, 2023.** The I-10 freeway closed for eight days after a fire in a pallet storage yard underneath it, fed by "pallets, cars, construction materials, hand sanitizer" [F7]. State inspectors had flagged the site for years. No one died, but it shows what palletized storage does, and that the hazard was on record somewhere except where it counts.

## 3. How it's done today

A pre-plan is the document that tells a crew, before they arrive, how a building is built, where the stairs and standpipes are, what the tenants store, how to reach the roof and what's next door. NFPA 1660 (2024) sets out what goes in one.

To make one, an officer walks the building with a form, or a tablet. That's the bottleneck.
- **Coverage is partial.** Plano Fire-Rescue documented plans for 1,087 of 2,345 target buildings, and North Charleston for 1,200 of 6,000 [M1][M2].
- **Plans don't reach the crew.** In one survey, 60.7% of plans lived in binders on the apparatus and 7.8% weren't available in the field at all [M1].
- **Software helps, but only partly.** First Due, the largest platform, raised $355M in 2025 and pre-fills parcel fields from assessor records [M9]. Assessor records don't say where the mezzanine stair is, that the roof is covered in live solar panels, or that the tenant is a wholesaler with a floor full of pallets. Someone still has to go and look.

## 4. What FirstIn does

The facts a pre-plan needs already exist. They're spread across three datasets that have never been pointed at the fire service:
- **CoStar:** what the building is and who's in it. Year built, construction, stories, area, sprinklers, loading docks, electrical service, every tenant with their industry and headcount.
- **Vexcel aerial imagery:** the roof, solar, height, footprint, neighboring buildings, and where apparatus can actually get to.
- **Matterport 3D scans:** the inside. Stairs, mezzanines, utility rooms, storage.

FirstIn's agent reads all three for the same address and writes an NFPA 1660-structured plan in about 30 seconds:
- **Every line has a source:** a CoStar record and field, a box on an aerial tile, or a box on a 360° scan.
- **Inferred hazards show their working.** Each one lists the facts it came from.
- **Cross-checks.** Where two sources measure the same thing, FirstIn compares them. At 10940 Wilshire, CoStar's 24 floors at 12 feet give 87.8 m and Vexcel's elevation model gives 87.2 m.
- **No guessing.** Anything it can't source is marked VERIFY ON SITE, and those items become the officer's walk-through checklist.
- **An officer signs off.** Nothing reaches a crew until an officer approves it, from the dashboard or by replying to a text.
- **The crew hears it.** The approved plan goes to the engine's in-cab screen as a one-page sheet and a 20-second spoken brief.

**The demo building, 1601 Perrino Pl, Los Angeles:**
- **From CoStar:** a 1969 concrete tilt-up warehouse with eleven dock doors and 480-volt three-phase service. Tenants include a logistics company and a grocery and health-and-beauty wholesaler.
- **From Vexcel:** solar across most of the roof, roof ponding, and one long side where a ladder truck can reach.
- **From Matterport:** pallets of boxed product and an open steel mezzanine stair.
- **For the officer to verify:** hydrants, the FDC and sprinklers. FirstIn flags them because nothing it can see proves them.

The brief the crew hears:

> "Engine 12, one-story industrial, built 1969, concrete tilt-up. Tenant MDB Transportation: possible high fire load, floor 1. Hazards: rooftop solar array, asbestos-containing materials, concrete tilt-up walls. Two stairs in the scan. Roof access: southwest long side; solar PV on roof. Exposure south: commercial building, 64 feet."

**Scale today:** 3,288 buildings indexed across Houston and Los Angeles, every CoStar commercial property with a Matterport scan. About 30 seconds for a prepared building and about 50 seconds live for any of the rest.

## 5. Who pays, and why

**Fire departments, through software they already buy.**
- **Who:** the 431 US departments protecting more than 100,000 people are the first market. Career and mostly-career departments protect 70% of the population [M15].
- **What they pay today:** Reno paid First Due $42,329.91 and Sparks $27,562.50 for a year of the suite, both from E911 surcharge funds [M5][M6].
- **Grant money:** FEMA's Fire Prevention and Safety grants name pre-planning software as eligible [M27]. The Assistance to Firefighters Grant does not, so we don't claim it.
- **How we sell:** an API into First Due, ImageTrend and FlowMSP, and Tablet Command, priced at about $10 to $15 per commercial building per year, capped per department.

**Cities, through their insurance grade.**
- **What ISO rewards:** ISO's Public Protection Classification sets fire insurance pricing for whole communities. Its training section gives 12 of 100 points to pre-fire planning inspections of every commercial building, made annually, with notes and sketches [M29].
- **Why it matters:** ISO says insurance in a community with a good grade is "substantially lower" [M29].
- **Where FirstIn fits:** no department can walk every commercial building every year. FirstIn makes that pass realistic, because the plan is already drafted and the officer confirms the VERIFY ON SITE items. The credit is earned by the walk; we make the walk possible.

**CoStar, as a new product line.**
- **The data comes together:** CoStar closed Matterport in February 2025 [M10] and agreed to buy Vexcel in October 2026, with closing expected in Q1 2027 [M12]. Once it closes, one company will hold the inside, the outside and the occupants of the same building.
- **Insurers are already customers:** Vexcel already sells to insurance underwriting [M12]. The cited construction and hazard fields FirstIn produces are what underwriters and risk engineers want.

**How big.**
- **US fire service:** about 5.9M commercial buildings at $10 a year is about $59M a year. A per-department cross-check gives about $42M. So the market is about $40 to 60M a year: real, and honest about being a niche [M42][M15].
- **The larger prize:** insurance and owner products on CoStar's own data, which we present as upside, not as market size.

## 6. What changes

- **For the crew:** they arrive knowing the roof is tilt-up concrete with solar on it, that the warehouse floor is stacked with pallets, and that the stair to the mezzanine is open steel. That's the information the Houston crews didn't have.
- **For the officer:** a blank-page survey becomes a ten-minute confirmation pass. Covering every building stops being impossible.
- **For the city:** pre-plan coverage that matches what ISO already asks for, and that stays current when tenants change.
- **Why collapse risk matters:** UL tested floor assemblies in a furnace. An unprotected engineered-wood floor collapsed in about 6 minutes; legacy lumber lasted about 19 [M39]. Knowing the construction before you go in is not a detail.
- **What we don't claim:** no controlled study shows that pre-plans reduce deaths, and we won't say one does. What exists is a long run of investigations, in Houston, Charleston, South Carolina and Georgia, naming missing building information as part of what went wrong.

## 7. Honest limits

- **It's decision support.** An officer approves everything.
- **Scans rarely cover a whole building.** Matterport usually covers one suite, so interior sections are partial, and the plan says which scan each fact came from.
- **Unprepared towers can go wrong.** For tall buildings that haven't been prepared, the aerial height can land on the wrong structure. We cross-check against CoStar and say so when they disagree.
- **The cited coverage figures** come from individual departments' Executive Fire Officer papers, not a national census.

---

## Sources

**Fires (`research/fires.md`)**
- [F1] NIOSH F2013-16 and Texas SFMO FFF FY 13-08, origin and timeline.
- [F2] NIOSH F2013-16, "4 Career Fire Fighters Killed and 16 Fire Fighters Injured at Commercial Structure Fire – Texas," July 8, 2015, rev. 2017 and 2021. https://stacks.cdc.gov/view/cdc/163331/cdc_163331_DS1.pdf
- [F3] Texas State Fire Marshal's Office, Investigation FFF FY 13-08, Finding 1. https://www.tdi.texas.gov/reports/fire/documents/fmloddhouston2013.pdf
- [F4] NBC News, May 31, 2013. https://www.nbcnews.com/news/us-news/cause-blaze-killed-four-houston-firefighters-under-investigation-flna6C10149696
- [F5] KPRC Click2Houston, March 8, 2017, Capt. Bill Dowling.
- [F6] NIOSH F2007-18, Charleston Sofa Super Store, Feb 2009. https://stacks.cdc.gov/view/cdc/163618
- [F7] Associated Press and ABC7 Los Angeles, I-10 fire coverage, November 2023 (see `press/SOURCES.md`).

**Market and impact (`research/market.md`, numbering follows that file)**
- [M1] Moberley, Plano Fire-Rescue EFO paper. https://apps.usfa.fema.gov/pdf/efop/efo247962.pdf
- [M2] FEMA EFO paper attributing 1,200 of 6,000 to North Charleston FD (see market.md §0).
- [M5] Sparks FD, Washoe County E911 committee, FY25 First Due, $27,562.50.
- [M6] Reno FD, First Due invoice, $42,329.91, Sept 2025.
- [M9] GovTech, First Due raises $355M, Aug 5, 2025.
- [M10] CoStar 8-K, Matterport completion, Feb 28, 2025.
- [M12] CoStar 8-K Ex. 99.2, Vexcel agreement, Oct 27, 2026.
- [M15] NFPA US Fire Department Profile 2020, supporting tables.
- [M27] FEMA FY2024 Fire Prevention and Safety NOFO.
- [M29] ISO PPC Summary Report text (Little Lake FD, CA, 2022).
- [M34] NIOSH F2023-07, April 2025.
- [M39] UL NC9140, Structural Stability of Engineered Lumber in Fire Conditions, 2008, rev. 2009.
- [M40] NIOSH F2025-09, March 2026.
- [M42] EIA CBECS 2018, Table B2.
