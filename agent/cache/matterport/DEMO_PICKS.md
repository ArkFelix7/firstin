# Matterport demo building picks

Source: the full account index (`agent/data/matterport_index.json`, 14,945 models: 6,031 Houston, 4,736 LA, 4,032 with no address). Most of the models are apartment units or amenity rooms.

## How candidates were chosen (`agent/scripts/mp_candidates.py` → `candidates.json`)
1. Models were grouped by street address and city.
2. Only groups with at least one model whose name looks commercial were kept (suite, office, warehouse, retail, lobby, floor, industrious, ...). Groups with ≥100 sweeps were scored.
3. Light GraphQL detail was pulled per model: floors, auto room tags, sweeps, mattertags and floorplans.
4. score = 10·max floors + sweeps/10 (capped at 60) + 0.5·mattertags + 6·(number of distinct fire-relevant room types) + 4·staircases + 3·utility rooms + 2·models.
   Fire-relevant room types: staircase, hallway, utility, basement, garage, lobby, entrance, kitchen, laundry, storage.
5. The score was then adjusted by hand for demo story value: hazards a firefighter cares about, a real street address, and a mix of Houston and LA.

## Picks

| id | building | why |
|---|---|---|
| **la-002** | 1601 Perrino Pl, LA 90023: warehouse plus a 2-story office suite (4 scans) | **Hero for the hazard story.** The warehouse pano shows an arched/bowstring **truss roof**, a mezzanine steel stair, roll-up doors and palletized storage (the Charleston pattern). 5 staircase rooms, utility, basement. 83 sweeps. |
| **la-001** | 337 S Broadway, LA 90013: "Office/Retail – 45,726 SF" (historic downtown) | 2 floors (~12.8k + 12.2k sf). Auto room tags include **staircase, utility, basement, hallway**. Panos show exposed **wood joists**, old brick and a gutted interior. 86 sweeps. 8 floorplan renders. |
| **la-003** | The Tower, 10940 Wilshire Blvd, LA 90024: high-rise office (7 suite scans) | **High-rise**: suite scans on floors 1, 10, 12, 14, 17, 19 and 20 (floor taken from the suite number). 367 sweeps. Lobby, basement and laundry tags. Good for standpipe and elevator questions. |
| **hou-001** | The Ion, 4201 Main St, Houston 77002 (Industrious, 2nd floor) | Iconic Houston innovation hub. **630 sweeps** on one floor, 49 rooms (offices, hallways, kitchen, entrance). 1 mattertag: "Elevators to 4th floor". It links to model `VMak8t57rzH`, which is **not** in our account. |
| **hou-002** | Modera Washington, 2520 Washington Ave, Houston 77007 (mixed-use) | Mixed-use residential with lots of amenity space: lobby & mail room, fitness, 2× co-working, golf simulator, 2 units. 7 scans, 219 sweeps, **99 mattertags** (including "Parking garage", "Mail room"). Some auto room tags look wrong; for example, the fitness center is tagged "lobby". |

Runners-up (in `candidates.json`):
- 5373 W Alabama (53 West, 4th/5th floor office, 620 sweeps)
- 2101 CityWest Blvd (Industrious, 2 floors, 535 sweeps)
- Westside Towers, 11835/11845 W Olympic
- 5340 Alla Rd (22.7k RSF, 2 floors, garage)
- 11302 Tanner Rd (2 × 22k SF floors)
- 1923 Kolfahl St (offices + warehouse; few sweeps)

## Caveats
- Commercial scans almost never have mattertags. Rich tags exist only on marketing scans of apartments.
- Room labels are Matterport **auto room tags** (`ModelRoom.tags`). They are often wrong for commercial space. Human `label` was null on every room checked.
- Each model only covers what was scanned (usually one suite). No pick is a full building-wide scan.
- lat/lng = Matterport `geolocation`. The Vexcel agent checked it and it lands inside the correct footprint for all 5. The Census geocoder results are kept as `census_lat`/`census_lng`; they were 30–210 m off (hou-001 resolved to a neighbouring one-story shop).
