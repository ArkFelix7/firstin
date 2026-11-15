// Mock backend: replays a realistic agent run so the dashboard can be
// developed, screenshotted and demoed without the FastAPI server.
// Active automatically when the agent server is unreachable, or with NEXT_PUBLIC_MOCK=1 / ?mock=1.
//
// Buildings mirror agent/cache/buildings.json (real addresses, Matterport model ids, data-layer flags).
// Imagery is the real cached Vexcel ortho + Matterport panoramas, copied into web/public/mock/<id>/.

import type { AgentEvent, Building, Cite, IncabSummary, Plan } from "./types";

export const MOCK_MATTERPORT_MODEL = "SxQL3iGyoDo"; // Matterport's public SDK demo space (fallback only)

const reg = (
  building_id: string,
  name: string,
  address: string,
  city: string,
  lat: number,
  lng: number,
  matterport_model_ids: string[],
): Building => ({
  building_id,
  name,
  address,
  city,
  lat,
  lng,
  costar_id: null,
  matterport_model_ids,
  has: { costar: false, vexcel: true, matterport: true },
});

// la-002 first: hero demo building.
export const MOCK_BUILDINGS: Building[] = [
  reg("la-002", "1601 Perrino Pl (warehouse + 2-story office suite)", "1601 Perrino Pl, Los Angeles, CA 90023", "Los Angeles", 34.0208998, -118.2227643, ["zt8JiL9gipg", "wbFSqgjj6kK", "t6kFJUuRnGU", "4aDYC41y3wg"]),
  reg("la-001", "337 S Broadway Office/Retail (45,726 SF)", "337 S Broadway, Los Angeles, CA 90013", "Los Angeles", 34.0502181, -118.2492997, ["6FNMVoyPrL1"]),
  reg("la-003", "The Tower, 10940 Wilshire Blvd (high-rise office)", "10940 Wilshire Blvd, Los Angeles, CA 90024", "Los Angeles", 34.0583489, -118.4450914, ["vkbu4hAnvxS", "jeQCuU9hBDR", "jUPNX68GzPa", "U7AC7onUGpD", "TUxHMD27KtN", "GyixtiZLr6d", "6Z3p5m9AcFQ"]),
  reg("hou-001", "The Ion (Industrious Houston, 2nd floor)", "4201 Main St, Houston, TX 77002", "Houston", 29.7341912, -95.3821531, ["CHUheq99ibg"]),
  reg("hou-002", "Modera Washington (mixed-use: lobby, co-working, fitness, units)", "2520 Washington Ave, Houston, TX 77007", "Houston", 29.7686393, -95.3850394, ["vG2ERTj2ntX", "YTNRqVb6niN", "LqmZFqC5SxX", "KJNN6MbCAhG", "HJNafzX6s5S", "DrF8mt1Fhsz", "38ijQVAArLd"]),
];

type BBox = [number, number, number, number]; // normalized 0–1 (x0,y0,x1,y1)

interface Pano {
  model: string;
  sweep: string;
  file: string;
  room: string;
}
interface MpFact {
  value: string | number;
  pano?: number; // index into profile.panos
  model?: string;
  bbox?: BBox;
  conf: number;
}
interface VxFact {
  value: string | number;
  bbox?: BBox;
  conf: number;
}
interface Profile {
  stories: MpFact | null;
  sqft: VxFact;
  construction: { value: string; from: string[]; conf: number };
  spaces: Array<{ name: string; use: string; floor: number; model: string }>;
  load: string;
  roof: VxFact;
  staging: VxFact;
  roads: VxFact;
  stairs: Array<MpFact & { standpipe?: boolean }>;
  elevators: MpFact | null;
  electrical: MpFact | null;
  sprinklers: MpFact | null;
  alarm: MpFact | null;
  hazards: Array<{ type: string; location: string; reason: string; conf: number } & ({ src: "matterport"; pano: number; bbox?: BBox } | { src: "vexcel"; bbox?: BBox } | { src: "inference"; from: string[] })>;
  exposures: Array<{ side: string; desc: string; bbox: BBox }>;
  panos: Pano[];
  roofSummary: string;
  brief: string;
}

const P = (model: string, sweep: string, room: string): Pano => ({ model, sweep, room, file: `pano_${model}_${sweep}.jpg` });

const PROFILES: Record<string, Profile> = {
  "la-002": {
    panos: [
      P("4aDYC41y3wg", "9xmbq7bmy1p7fp7gk6xgbk9id", "Suite A Warehouse · staircase"),
      P("t6kFJUuRnGU", "cybtx8wte19ga4b7smk659sra", "First Floor Lobby · staircase"),
      P("zt8JiL9gipg", "trs5e98bi4wfcey4yzitst8da", "Suite A Second Floor · staircase"),
      P("wbFSqgjj6kK", "ryddgmk9bg5b2hp40e2wa64rb", "Suite A First Floor · basement"),
    ],
    stories: { value: 2, pano: 2, model: "zt8JiL9gipg", conf: 0.82 },
    sqft: { value: 64860, bbox: [0.1, 0.03, 0.97, 0.94], conf: 0.9 },
    construction: { value: "Bowstring/arched truss roof over warehouse; flat membrane deck", from: ["matterport.pano_warehouse", "vexcel.roof_shape"], conf: 0.74 },
    spaces: [
      { name: "Suite A Warehouse", use: "Warehouse · palletized storage", floor: 1, model: "4aDYC41y3wg" },
      { name: "First Floor Lobby and Kitchen", use: "Lobby · break kitchen", floor: 1, model: "t6kFJUuRnGU" },
      { name: "Suite A First Floor", use: "Office", floor: 1, model: "wbFSqgjj6kK" },
      { name: "Suite A Second Floor", use: "Office (8,697 SF)", floor: 2, model: "zt8JiL9gipg" },
    ],
    load: "20–45 daytime (warehouse + office)",
    roof: { value: "No fixed ladder seen, ground ladder at SE loading dock", bbox: [0.84, 0.69, 0.97, 0.81], conf: 0.68 },
    staging: { value: "SW lot along Perrino Pl frontage", bbox: [0.44, 0.78, 0.66, 0.99], conf: 0.74 },
    roads: { value: "Perrino Pl (SW); rail ROW blocks NE side", bbox: [0.06, 0.46, 0.4, 0.98], conf: 0.7 },
    stairs: [
      { value: "Steel mezzanine stair, warehouse west wall", pano: 0, bbox: [0.055, 0.37, 0.16, 0.58], conf: 0.9 },
      { value: "Interior stair, lobby to 2nd floor", pano: 1, bbox: [0.02, 0.3, 0.18, 0.56], conf: 0.88 },
    ],
    elevators: null,
    electrical: null,
    sprinklers: { value: "Wet-pipe mains visible (orange), office areas", pano: 3, bbox: [0.0, 0.12, 0.21, 0.34], conf: 0.78 },
    alarm: { value: "Red pull station by lobby corridor", pano: 1, bbox: [0.335, 0.41, 0.365, 0.48], conf: 0.62 },
    hazards: [
      { type: "Bowstring truss roof", location: "Warehouse, full clear span", reason: "Arched trusses visible in Matterport pano. Bowstring roofs fail suddenly under fire; no interior ops beneath.", conf: 0.86, src: "matterport", pano: 0, bbox: [0.12, 0.05, 0.88, 0.36] },
      { type: "High-piled palletized storage", location: "Warehouse floor, center-west", reason: "Stacked cartons on pallets in pano (Charleston fire-load pattern).", conf: 0.8, src: "matterport", pano: 0, bbox: [0.27, 0.45, 0.46, 0.56] },
      { type: "Energized rooftop PV, 66 panels", location: "Roof, full footprint", reason: "Vexcel roof AI: solar-panel-photovoltaic = 66. Shock hazard; restricts vertical ventilation.", conf: 0.93, src: "vexcel", bbox: [0.2, 0.22, 0.87, 0.87] },
      { type: "19 skylights, fall-through", location: "Roof deck", reason: "Vexcel roof AI skylight count; obscured by PV rows.", conf: 0.8, src: "inference", from: ["vexcel.roof_objects"] },
    ],
    exposures: [
      { side: "Northeast", desc: "Active rail ROW + open yard, ~15 m", bbox: [0.55, 0.0, 1.0, 0.5] },
      { side: "South", desc: "1-story industrial bldg, ~25 m", bbox: [0.14, 0.86, 0.38, 1.0] },
    ],
    roofSummary: "Flat membrane, 66 PV panels, 19 skylights, condition fair",
    brief:
      "Engine 12, two-story warehouse and office, about sixty-five thousand square feet. Bowstring truss roof over the warehouse: early collapse risk, no interior operations beneath it. Palletized storage on the warehouse floor. Sixty-six energized solar panels on the roof. Stairs: steel mezzanine stair on the warehouse west wall, interior stair from the lobby. Sprinkler mains visible. Hydrants not verified. Rail line exposure to the northeast.",
  },
  "la-001": {
    panos: [P("6FNMVoyPrL1", "cezdyb182iytinknshrredizb", "Office/Retail · staircase"), P("6FNMVoyPrL1", "aam2ur04586h25nq40qgca6ka", "Office/Retail · utility")],
    stories: { value: 2, pano: 0, model: "6FNMVoyPrL1", conf: 0.7 },
    sqft: { value: 45726, bbox: [0.25, 0.25, 0.75, 0.75], conf: 0.85 },
    construction: { value: "Masonry walls, exposed wood joists (pano-observed)", from: ["matterport.pano_staircase", "vexcel.roof_shape"], conf: 0.66 },
    spaces: [{ name: "Office/Retail, 45,726 SF", use: "Vacant office/retail (gutted)", floor: 1, model: "6FNMVoyPrL1" }],
    load: "<20 (vacant / under renovation)",
    roof: { value: "Flat membrane; 21 rooftop HVAC units, access via interior stair (unverified)", bbox: [0.35, 0.35, 0.65, 0.65], conf: 0.6 },
    staging: { value: "S Broadway curb lane (front)", bbox: [0.05, 0.6, 0.4, 0.95], conf: 0.7 },
    roads: { value: "S Broadway (front), rear alley", bbox: [0.0, 0.7, 1.0, 0.95], conf: 0.62 },
    stairs: [{ value: "Main stair, floor 1", pano: 0, conf: 0.82 }],
    elevators: null,
    electrical: { value: "Utility room, floor 1", pano: 1, conf: 0.74 },
    sprinklers: null,
    alarm: null,
    hazards: [
      { type: "Exposed wood joists, rapid collapse", location: "Floors 1–2", reason: "Unprotected wood floor joists visible in pano; old brick.", conf: 0.72, src: "matterport", pano: 0 },
      { type: "Basement, limited egress", location: "Below grade", reason: "Matterport auto room tags: basement (×3).", conf: 0.65, src: "inference", from: ["matterport.room_tags"] },
    ],
    exposures: [{ side: "North/South", desc: "Attached row buildings, common walls", bbox: [0.0, 0.0, 0.3, 1.0] }],
    roofSummary: "Flat membrane, 21 AC units, condition fair",
    brief: "Engine 12, two-story historic office and retail, forty-five thousand square feet, largely gutted. Exposed wood joists: collapse risk. Basement with limited egress. Attached buildings on both sides. Utility room on floor one.",
  },
  "la-003": {
    panos: [P("6Z3p5m9AcFQ", "ieiuq4czupx3mwdf9p7rq48ia", "Suite 1700 · lobby"), P("U7AC7onUGpD", "2xg7h902u9692nq86r0ik3m7c", "Suite 1950 · basement-tagged")],
    stories: { value: "20+ (suites on floors 1–20)", pano: 0, model: "6Z3p5m9AcFQ", conf: 0.75 },
    sqft: { value: 48400, bbox: [0.3, 0.3, 0.7, 0.7], conf: 0.85 },
    construction: { value: "High-rise steel/concrete frame (era-inferred)", from: ["vexcel.height", "matterport.floors"], conf: 0.6 },
    spaces: [
      { name: "Suite 1700, 13,243 SF", use: "Office", floor: 17, model: "6Z3p5m9AcFQ" },
      { name: "Suite 1950, 1,695 SF", use: "Office", floor: 19, model: "U7AC7onUGpD" },
      { name: "Suite 150, 2,113 SF", use: "Office", floor: 1, model: "GyixtiZLr6d" },
    ],
    load: "600–900 daytime (high-rise office)",
    roof: { value: "Flat roof, helipad/mech penthouse; access via stair to roof (unverified)", bbox: [0.35, 0.35, 0.65, 0.65], conf: 0.6 },
    staging: { value: "Wilshire Blvd frontage; garage entrance rear", bbox: [0.05, 0.7, 0.45, 0.97], conf: 0.66 },
    roads: { value: "Wilshire Blvd (S), side street (W)", bbox: [0.0, 0.75, 1.0, 1.0], conf: 0.6 },
    stairs: [{ value: "Core stair, floor 17 lobby", pano: 0, conf: 0.7, standpipe: true }],
    elevators: { value: "Passenger elevator bank (core)", pano: 0, conf: 0.72 },
    electrical: null,
    sprinklers: null,
    alarm: null,
    hazards: [
      { type: "High-rise, standpipe operations", location: "All floors above 75 ft", reason: "Suites to floor 20 → high-rise SOP; stairwell pressurization.", conf: 0.8, src: "inference", from: ["matterport.floors", "vexcel.height"] },
      { type: "Large daytime occupant load", location: "Floors 1–20", reason: "Office suites totaling >40k SF scanned.", conf: 0.6, src: "inference", from: ["matterport.area_sqft"] },
    ],
    exposures: [{ side: "East", desc: "Mid-rise office ~20 m", bbox: [0.7, 0.2, 1.0, 0.7] }],
    roofSummary: "Flat membrane, condition fair",
    brief: "Engine 12, high-rise office tower, suites to the twentieth floor. High-rise standpipe operations. Core stair and elevator bank. Large daytime occupant load. Staging on Wilshire.",
  },
  "hou-001": {
    panos: [P("CHUheq99ibg", "39ytbn150x6s1qiu5ksnpne8b", "Industrious · entrance"), P("CHUheq99ibg", "3r2sqq5pqa0t2k7trd4gysukc", "Industrious · kitchen")],
    stories: { value: "4+ (mattertag: “Elevators to 4th floor”)", pano: 0, model: "CHUheq99ibg", conf: 0.8 },
    sqft: { value: 58775, bbox: [0.25, 0.2, 0.8, 0.8], conf: 0.9 },
    construction: { value: "Renovated concrete frame, flat membrane roof (era-inferred)", from: ["vexcel.roof_shape"], conf: 0.55 },
    spaces: [{ name: "Industrious Houston, The Ion", use: "Co-working office (49 rooms)", floor: 2, model: "CHUheq99ibg" }],
    load: "250–400 daytime (co-working)",
    roof: { value: "Flat membrane, 92 roof vents, interior roof access (unverified)", bbox: [0.3, 0.3, 0.7, 0.7], conf: 0.62 },
    staging: { value: "Main St frontage (west)", bbox: [0.02, 0.3, 0.25, 0.9], conf: 0.7 },
    roads: { value: "Main St + Holman St", bbox: [0.0, 0.0, 1.0, 0.2], conf: 0.6 },
    stairs: [{ value: "Entrance stair, floor 2", pano: 0, conf: 0.7 }],
    elevators: { value: "Elevator bank (mattertag)", pano: 0, conf: 0.85 },
    electrical: null,
    sprinklers: null,
    alarm: null,
    hazards: [
      { type: "High occupant load", location: "Floor 2 co-working", reason: "630 sweeps, 49 offices, dense daytime occupancy.", conf: 0.65, src: "inference", from: ["matterport.rooms"] },
      { type: "Commercial kitchen", location: "Floor 2 kitchen", reason: "Kitchen room tag + pano.", conf: 0.7, src: "matterport", pano: 1 },
    ],
    exposures: [{ side: "South", desc: "Parking structure ~20 m", bbox: [0.2, 0.8, 0.8, 1.0] }],
    roofSummary: "Flat membrane, 92 vents, condition good",
    brief: "Engine 12, four-plus story innovation hub, co-working on floor two. High daytime occupant load. Elevator bank to floor four. Kitchen on floor two. Staging on Main Street.",
  },
  "hou-002": {
    panos: [P("YTNRqVb6niN", "qxp7ik0s9bra1qdh9g218tpmc", "Lobby & Mail · lobby"), P("KJNN6MbCAhG", "1cd2w31mbbtrx5efqdk5w9kac", "Co-Working · lobby")],
    stories: { value: "5 (Vexcel height p90 25.2 m)", pano: 0, model: "YTNRqVb6niN", conf: 0.6 },
    sqft: { value: 76650, bbox: [0.2, 0.25, 0.85, 0.75], conf: 0.9 },
    construction: { value: "Podium + wood-frame residential (era-inferred)", from: ["vexcel.building_type", "vexcel.height"], conf: 0.55 },
    spaces: [
      { name: "Lobby & Mail Room", use: "Residential lobby", floor: 1, model: "YTNRqVb6niN" },
      { name: "Co-Working", use: "Amenity / co-working", floor: 1, model: "KJNN6MbCAhG" },
      { name: "Fitness Center", use: "Amenity", floor: 1, model: "LqmZFqC5SxX" },
      { name: "Units A11, B06", use: "Residential units", floor: 2, model: "vG2ERTj2ntX" },
    ],
    load: "Residential, sleeping occupants 24 h",
    roof: { value: "Flat membrane; 229 rooftop AC units, interior roof hatch (unverified)", bbox: [0.25, 0.3, 0.8, 0.7], conf: 0.62 },
    staging: { value: "Washington Ave frontage (north)", bbox: [0.1, 0.0, 0.9, 0.2], conf: 0.7 },
    roads: { value: "Washington Ave (N), side streets E/W", bbox: [0.0, 0.0, 1.0, 0.15], conf: 0.62 },
    stairs: [{ value: "Lobby stair, floor 1", pano: 0, conf: 0.66 }],
    elevators: null,
    electrical: null,
    sprinklers: null,
    alarm: null,
    hazards: [
      { type: "Sleeping occupants", location: "Residential floors", reason: "Vexcel building_type = condo_apartment; unit scans.", conf: 0.85, src: "inference", from: ["vexcel.building_type"] },
      { type: "Wood-frame over podium", location: "Upper floors", reason: "Era + type → rapid vertical fire spread in voids.", conf: 0.5, src: "inference", from: ["vexcel.building_type", "vexcel.height"] },
      { type: "Parking garage", location: "Ground level (mattertag)", reason: "Mattertag “Parking garage”, EV/vehicle fire load.", conf: 0.7, src: "matterport", pano: 0 },
    ],
    exposures: [{ side: "West", desc: "Townhomes ~12 m", bbox: [0.0, 0.25, 0.2, 0.8] }],
    roofSummary: "Flat membrane, 229 AC units, condition good",
    brief: "Engine 12, five-story mixed-use residential with amenity floor. Sleeping occupants. Wood frame over podium. Parking garage at ground level. Stage on Washington Avenue.",
  },
};

export function mockBuilding(id: string): Building {
  return MOCK_BUILDINGS.find((b) => b.building_id === id) ?? MOCK_BUILDINGS[0];
}

const profileOf = (b: Building) => PROFILES[b.building_id] ?? PROFILES["la-002"];

/** Esri World Imagery export centred on a point, fallback aerial for unknown buildings. */
export function mockAerialUrl(b: Building, size = 1024): string {
  if (PROFILES[b.building_id]) return `/mock/${b.building_id}/ortho.jpg`;
  const dLng = 0.0011;
  const dLat = dLng * Math.cos((b.lat * Math.PI) / 180);
  const bbox = [b.lng - dLng, b.lat - dLat, b.lng + dLng, b.lat + dLat].join(",");
  return `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox=${bbox}&bboxSR=4326&imageSR=3857&size=${size},${size}&format=jpg&f=image`;
}

export function mockCostarRecord(b: Building): Record<string, unknown> {
  return { building_id: b.building_id, address: b.address, error: "No CoStar record in cache for this building (replay)." };
}

const tileId = (b: Building) => `vexcel/urban-r/ortho@${b.lat.toFixed(6)},${b.lng.toFixed(6)}`;

export function mockPlan(b: Building): Plan {
  const p = profileOf(b);
  const vx = (f: { bbox?: BBox; conf: number }): Cite => ({ src: "vexcel", id: tileId(b), conf: f.conf, bbox: f.bbox ?? null, url: mockAerialUrl(b) });
  const mp = (f: { pano?: number; bbox?: BBox; conf: number; model?: string }): Cite => {
    const pano = f.pano !== undefined ? p.panos[f.pano] : undefined;
    return {
      src: "matterport",
      id: pano?.sweep ?? f.model ?? b.matterport_model_ids?.[0] ?? "",
      model_id: pano?.model ?? f.model ?? b.matterport_model_ids?.[0],
      conf: f.conf,
      bbox: f.bbox ?? null,
      url: pano ? `/mock/${b.building_id}/${pano.file}` : null,
      room: pano?.room,
    };
  };
  const V = { value: "VERIFY ON SITE", cite: null };
  const mf = (f: MpFact | null) => (f ? { value: f.value, cite: mp(f) } : V);

  return {
    plan_id: `pp-${b.building_id}`,
    building_id: b.building_id,
    building: {
      address: b.address,
      stories: mf(p.stories),
      year_built: V,
      sq_ft: { value: p.sqft.value, cite: { ...vx(p.sqft), from: ["vexcel.footprint_area_m2"] } },
      roof: { value: p.roofSummary, cite: vx({ conf: 0.9 }) },
      construction: { value: p.construction.value, cite: { src: "inference", conf: p.construction.conf, from: p.construction.from } },
    },
    occupancy: {
      tenants: p.spaces.map((s) => ({ name: s.name, use: s.use, floor: s.floor, cite: { src: "matterport", id: s.model, model_id: s.model, conf: 0.9 } })),
      occupant_load_estimate: { value: p.load, cite: { src: "inference", conf: 0.5, from: ["matterport.area_sqft", "vexcel.footprint_area_m2"] } },
    },
    access: {
      roof_access: { value: p.roof.value, cite: vx(p.roof) },
      staging: { value: p.staging.value, cite: vx(p.staging) },
      hydrants: V,
      access_roads: { value: p.roads.value, cite: vx(p.roads) },
    },
    interior: {
      stairwells: p.stairs.map((s) => ({ loc: s.value, standpipe: s.standpipe ?? false, cite: mp(s) })),
      elevators: mf(p.elevators),
      utilities: { electrical_room: mf(p.electrical), gas_shutoff: V },
      fire_protection: { sprinklers: mf(p.sprinklers), alarm_panel: mf(p.alarm), standpipe: V, fdc: "VERIFY ON SITE" },
    },
    hazards: p.hazards.map((h) => ({
      type: h.type,
      location: h.location,
      reason: h.reason,
      conf: h.conf,
      cite:
        h.src === "matterport"
          ? mp({ pano: h.pano, bbox: h.bbox, conf: h.conf })
          : h.src === "vexcel"
            ? { ...vx({ bbox: h.bbox, conf: h.conf }), from: ["vexcel.roof_objects"] }
            : { src: "inference", conf: h.conf, from: h.from },
    })),
    exposures: p.exposures.map((e) => ({ side: e.side, desc: e.desc, cite: vx({ bbox: e.bbox, conf: 0.7 }) })),
    media: {
      aerial_url: mockAerialUrl(b),
      pano_urls: p.panos.map((x) => `/mock/${b.building_id}/${x.file}`),
      matterport_model_id: b.matterport_model_ids?.[0],
    },
    voice_brief: p.brief,
    status: "DRAFT",
    approved_by: null,
  };
}

/* ------------------------------------------------------------------ */
/* Timeline                                                            */
/* ------------------------------------------------------------------ */

const TODOS = [
  "Resolve building & parcel",
  "§4 Building, construction, era, size",
  "§5 Occupancy, tenants & occupant load",
  "§6 Access, roof, staging, hydrants",
  "§7 Interior, stairs, elevators, utilities",
  "§8 Fire protection, standpipe, FDC, alarm",
  "§9 Hazards, occupancy, construction, roof",
  "§10 Exposures, adjacent structures",
  "Validate citations (cite-or-flag)",
  "Publish pre-plan (officer approval)",
];

type Step = [number, string, Record<string, unknown>];

function todos(statuses: string): Record<string, unknown> {
  const map: Record<string, string> = { p: "pending", r: "in_progress", c: "completed" };
  return { todos: TODOS.map((content, i) => ({ content, status: map[statuses[i] ?? "p"] })) };
}

function timeline(b: Building): Step[] {
  const plan = mockPlan(b);
  const p = profileOf(b);
  const s: Step[] = [];
  const at = (t: number, type: string, payload: Record<string, unknown>) => s.push([t, type, payload]);
  const nModels = b.matterport_model_ids?.length ?? 0;
  const pan = (i: number) => p.panos[i] ?? p.panos[0];

  at(0, "log", { agent: "planner", message: `Run started · ${b.address}` });
  at(250, "todo", todos("rppppppppp"));
  at(500, "tool_call", { agent: "planner", tool: "resolve_building", args: { query: b.address } });
  at(1100, "tool_result", { agent: "planner", tool: "resolve_building", summary: `${b.building_id} · ${b.lat.toFixed(5)}, ${b.lng.toFixed(5)} · ${nModels} Matterport model(s)` });
  at(1300, "todo", todos("crrrrrrrpp"));
  at(1400, "log", { agent: "planner", message: "Fan-out: costar-analyst ∥ aerial-analyst ∥ interior-analyst" });

  at(1600, "subagent_start", { name: "costar-analyst", description: "Building attributes, tenants, occupancy" });
  at(1750, "subagent_start", { name: "aerial-analyst", description: "Roof, staging, hydrants, exposures from Vexcel" });
  at(1900, "subagent_start", { name: "interior-analyst", description: "Stairs, egress, utilities, FP equipment from Matterport" });

  at(2100, "tool_call", { agent: "costar-analyst", tool: "costar_property", args: { building_id: b.building_id } });
  at(2300, "tool_call", { agent: "aerial-analyst", tool: "vexcel_tile", args: { building_id: b.building_id, view: "ortho" } });
  at(2500, "tool_call", { agent: "interior-analyst", tool: "matterport_model", args: { building_id: b.building_id } });
  at(2900, "tool_result", { agent: "costar-analyst", tool: "costar_property", ok: false, summary: "no CoStar record for building → year/class fields VERIFY ON SITE" });
  at(3100, "log", { agent: "costar-analyst", message: "CoStar cache miss, falling back to Matterport scan names for occupancy", level: "warn" });
  at(3400, "tool_result", { agent: "aerial-analyst", tool: "vexcel_tile", summary: `${tileId(b)} · GSD 6.2 cm · 2026-07` });
  at(3600, "tool_call", { agent: "aerial-analyst", tool: "vexcel_roof", args: { building_id: b.building_id } });
  at(3800, "tool_result", { agent: "interior-analyst", tool: "matterport_model", summary: `${nModels} scan(s) · ${p.spaces.length} spaces · floors ${p.spaces.map((x) => x.floor).join("/")}` });
  at(4100, "tool_call", { agent: "interior-analyst", tool: "matterport_panoramas", args: { room_filter: "staircase|utility|basement", limit: 6 } });
  at(4500, "tool_result", { agent: "aerial-analyst", tool: "vexcel_roof", summary: p.roofSummary });
  at(4700, "evidence", { agent: "costar-analyst", source: "costar", path: "/evidence/costar.json", content: mockCostarRecord(b) });
  at(5000, "subagent_end", { name: "costar-analyst", summary: "no record, occupancy from Matterport spaces" });
  at(5050, "plan", { status: "DRAFT", plan: { building: plan.building, occupancy: plan.occupancy, status: "DRAFT" } });
  at(5100, "todo", todos("cccrrrrrpp"));
  at(5200, "tool_call", { agent: "aerial-analyst", tool: "describe_image", args: { question: "Roof access points, staging, hydrants, exposures?" } });
  at(5400, "tool_result", { agent: "interior-analyst", tool: "matterport_panoramas", summary: `${p.panos.length} panos · ${p.panos.map((x) => x.room.split(" · ")[1]).join(", ")}` });
  at(5600, "tool_call", { agent: "interior-analyst", tool: "describe_image", args: { image: pan(0).file, question: "Stairs, standpipes, structural hazards, storage?" } });
  at(6400, "tool_result", { agent: "aerial-analyst", tool: "describe_image", summary: `Staging: ${p.staging.value}. Hydrants: not resolvable → flag` });
  at(6600, "tool_call", { agent: "aerial-analyst", tool: "vexcel_oblique", args: { direction: "N" } });
  at(7000, "tool_result", { agent: "interior-analyst", tool: "describe_image", summary: `${p.stairs[0]?.value ?? "stair"} (conf ${(p.stairs[0]?.conf ?? 0.7).toFixed(2)})` });
  at(7200, "tool_call", { agent: "interior-analyst", tool: "describe_image", args: { image: pan(1).file, question: "Fire alarm, sprinklers, electrical?" } });
  at(7600, "tool_result", { agent: "aerial-analyst", tool: "vexcel_oblique", summary: `Exposure ${p.exposures[0].side}: ${p.exposures[0].desc}` });
  at(7900, "evidence", { agent: "aerial-analyst", source: "vexcel", path: "/evidence/vexcel.json", url: mockAerialUrl(b) });
  at(8100, "subagent_end", { name: "aerial-analyst", summary: `roof, staging, ${p.exposures.length} exposure(s); hydrants unresolved` });
  at(8150, "plan", { status: "DRAFT", plan: { building: plan.building, occupancy: plan.occupancy, access: plan.access, exposures: plan.exposures, status: "DRAFT" } });
  at(8200, "todo", todos("ccccrrrcpp"));
  at(8800, "tool_result", { agent: "interior-analyst", tool: "describe_image", summary: p.sprinklers ? `${p.sprinklers.value}` : "No FP equipment visible → flag" });
  at(9300, "evidence", { agent: "interior-analyst", source: "matterport", path: "/evidence/matterport.json", model_id: b.matterport_model_ids?.[0] });
  at(9500, "subagent_end", { name: "interior-analyst", summary: `${p.stairs.length} stair(s), ${[p.sprinklers, p.alarm, p.electrical].filter(Boolean).length} FP/utility finds` });
  const tInt = 9550;
  at(tInt, "plan", { status: "DRAFT", plan: { ...plan, hazards: undefined, voice_brief: undefined, status: "DRAFT" } });
  at(tInt + 50, "todo", todos("ccccccrcpp"));

  at(tInt + 300, "subagent_start", { name: "hazard-reasoner", description: "Occupancy + construction + roof → hazards" });
  p.hazards.forEach((h, i) => {
    at(tInt + 900 + i * 650, "log", { agent: "hazard-reasoner", message: `${h.src === "inference" ? "rule" : h.src} → ${h.type} (conf ${h.conf.toFixed(2)})` });
  });
  const tHz = tInt + 900 + p.hazards.length * 650;
  at(tHz, "evidence", { agent: "hazard-reasoner", source: "hazards", path: "/evidence/hazards.json" });
  at(tHz + 150, "subagent_end", { name: "hazard-reasoner", summary: `${p.hazards.length} hazards flagged` });
  at(tHz + 200, "plan", { status: "DRAFT", plan: { ...plan, voice_brief: undefined, status: "DRAFT" } });
  at(tHz + 250, "todo", todos("ccccccccrp"));

  at(tHz + 500, "subagent_start", { name: "validator", description: "Reject any field without a citation" });
  const flagged = ["building.year_built", "access.hydrants", "interior.fire_protection.fdc", "interior.fire_protection.standpipe", "interior.utilities.gas_shutoff"];
  flagged.forEach((f, i) => at(tHz + 900 + i * 300, "log", { agent: "validator", message: `${f}, no evidence → VERIFY ON SITE`, level: "warn" }));
  const tV = tHz + 900 + flagged.length * 300;
  at(tV, "log", { agent: "validator", message: "All remaining leaf fields cited ✓" });
  at(tV + 200, "subagent_end", { name: "validator", summary: `${flagged.length}+ fields flagged VERIFY ON SITE` });
  at(tV + 300, "plan", { status: "PENDING_APPROVAL", plan: { ...plan, status: "PENDING_APPROVAL" } });
  at(tV + 400, "todo", todos("cccccccccr"));
  at(tV + 600, "tool_call", { agent: "planner", tool: "render_pdf", args: { plan_id: plan.plan_id } });
  at(tV + 1100, "tool_result", { agent: "planner", tool: "render_pdf", summary: "preplan.pdf · 1 page" });
  at(tV + 1200, "tool_call", { agent: "planner", tool: "tts_brief", args: { chars: p.brief.length } });
  at(tV + 1700, "tool_result", { agent: "planner", tool: "tts_brief", summary: "brief.mp3 · ~22 s" });
  at(tV + 1900, "tool_call", { agent: "planner", tool: "publish_preplan", args: { plan_id: plan.plan_id } });
  at(tV + 2100, "interrupt", {
    action: "publish_preplan",
    plan_id: plan.plan_id,
    message: "Officer approval required before publishing to Engine 12.",
  });
  return s;
}

/* ------------------------------------------------------------------ */
/* Runtime                                                             */
/* ------------------------------------------------------------------ */

type Listener = (e: AgentEvent) => void;

interface MockRun {
  building: Building;
  t0: number;
  timers: ReturnType<typeof setTimeout>[];
  listeners: Set<Listener>;
  history: AgentEvent[];
  started: boolean;
  plan: Plan;
}

const runs = new Map<string, MockRun>();

export function mockRunId(buildingId: string) {
  return `mock-${buildingId}-${Date.now().toString(36)}`;
}

function buildingFromRunId(runId: string): Building {
  const m = runId.match(/^mock-([a-z]+-\d+)/i);
  return mockBuilding(m?.[1] ?? "la-002");
}

function getRun(runId: string): MockRun {
  let r = runs.get(runId);
  if (!r) {
    const building = buildingFromRunId(runId);
    r = { building, t0: 0, timers: [], listeners: new Set(), history: [], started: false, plan: { status: "DRAFT" } };
    runs.set(runId, r);
  }
  return r;
}

function emit(r: MockRun, type: string, payload: Record<string, unknown>) {
  const e: AgentEvent = { type, ts: Date.now() / 1000, payload };
  if (type === "plan") r.plan = (payload.plan as Plan) ?? r.plan;
  r.history.push(e);
  r.listeners.forEach((l) => l(e));
}

export function mockSubscribe(runId: string, listener: Listener): () => void {
  const r = getRun(runId);
  // replay what already happened (e.g. after a remount)
  r.history.forEach((e) => listener(e));
  r.listeners.add(listener);
  if (!r.started) {
    r.started = true;
    r.t0 = Date.now();
    r.timers = timeline(r.building).map(([t, type, payload]) => setTimeout(() => emit(r, type, payload), t));
  }
  return () => {
    r.listeners.delete(listener);
  };
}

export function mockGetPlan(runId: string): Plan {
  return getRun(runId).plan;
}

const INCAB_KEY = "firstin.mock.incab";

function applyEdits(plan: Plan, edits: Record<string, unknown> | undefined): Plan {
  if (!edits) return plan;
  const next = structuredClone(plan) as Record<string, unknown>;
  for (const [path, value] of Object.entries(edits)) {
    const keys = path.split(".");
    let cur: Record<string, unknown> = next;
    for (let i = 0; i < keys.length - 1; i++) {
      const k = keys[i];
      if (typeof cur[k] !== "object" || cur[k] === null) cur[k] = {};
      cur = cur[k] as Record<string, unknown>;
    }
    const last = keys[keys.length - 1];
    const existing = cur[last];
    const cite = { src: "officer", id: "manual-edit", conf: 1 };
    if (existing && typeof existing === "object" && "value" in (existing as object)) {
      cur[last] = { value, cite };
    } else if (typeof existing === "string" || existing === undefined || existing === null) {
      cur[last] = { value, cite };
    } else {
      cur[last] = value;
    }
  }
  return next as Plan;
}

export function summarize(plan: Plan, approvedAt: string): IncabSummary {
  const v = (x: unknown): string | number | null => {
    if (x && typeof x === "object" && "value" in (x as object)) return (x as { value: string | number }).value;
    return (x as string | number) ?? null;
  };
  const stairs = (plan.interior?.stairwells as Array<{ loc: string; standpipe?: boolean }> | undefined)?.map(
    (s) => `${s.loc}${s.standpipe ? ", standpipe" : ""}`,
  );
  return {
    plan_id: plan.plan_id ?? "pp",
    address: (plan.building?.address as string) ?? "",
    stories: v(plan.building?.stories),
    year_built: v(plan.building?.year_built),
    construction: v(plan.building?.construction) as string,
    top_hazards: (plan.hazards ?? []).slice(0, 3).map((h) => ({ type: h.type as string, location: h.location as string })),
    stairs: stairs ?? null,
    roof_access: v(plan.access?.roof_access) as string,
    voice_brief: plan.voice_brief ?? null,
    audio_url: null,
    approved_at: approvedAt,
  };
}

export async function mockApprove(
  runId: string,
  body: { approved_by: string; decision: "approve" | "reject"; edits?: Record<string, unknown> },
) {
  const r = getRun(runId);
  await new Promise((res) => setTimeout(res, 500));
  if (body.decision === "reject") {
    emit(r, "plan", { plan: { ...r.plan, status: "REJECTED" } });
    emit(r, "log", { agent: "planner", msg: `Rejected by ${body.approved_by}` , level: "warn"});
    setTimeout(() => emit(r, "done", {}), 300);
    return { ok: true };
  }
  const approved: Plan = { ...applyEdits(r.plan, body.edits), status: "APPROVED", approved_by: body.approved_by };
  emit(r, "log", { agent: "planner", msg: `Approved by ${body.approved_by}${body.edits ? ` with ${Object.keys(body.edits).length} edit(s)` : ""}` });
  emit(r, "plan", { plan: approved });
  setTimeout(() => {
    const now = new Date().toISOString();
    emit(r, "tool_result", { agent: "planner", name: "publish_preplan", summary: "Published → Engine 12 in-cab unit" });
    emit(r, "published", { plan_id: approved.plan_id, pdf_url: null, audio_url: null, approved_at: now });
    try {
      localStorage.setItem(INCAB_KEY, JSON.stringify(summarize(approved, now)));
    } catch {
      /* ignore */
    }
    const todo = todos("cccccccccc");
    emit(r, "todo", todo);
    setTimeout(() => emit(r, "done", {}), 200);
  }, 900);
  return { ok: true };
}

export function mockIncab(): IncabSummary | null {
  try {
    const raw = localStorage.getItem(INCAB_KEY);
    if (raw) return JSON.parse(raw) as IncabSummary;
  } catch {
    /* ignore */
  }
  // Standby unless ?seed=1 (used for screenshots / rehearsals).
  if (typeof window === "undefined" || new URLSearchParams(window.location.search).get("seed") !== "1") return null;
  return { ...summarize(mockPlan(MOCK_BUILDINGS[0]), "2026-11-15T06:12:00Z"), plan_id: "pp-la-002-seed" };
}

export function mockAsk(question: string, summary: IncabSummary | null): string {
  const q = question.toLowerCase();
  const s = summary;
  if (!s) return "No approved pre-plan is active.";
  const stairs = Array.isArray(s.stairs) ? s.stairs.join("; ") : s.stairs;
  if (q.includes("standpipe")) {
    const sp = Array.isArray(s.stairs) ? s.stairs.find((x) => /standpipe/i.test(x)) : null;
    return sp ? `Standpipe is in the ${sp.replace(/, standpipe/i, "")}.` : "Standpipe location is not confirmed. Verify on site.";
  }
  if (q.includes("stair")) return `Stairs: ${stairs ?? "verify on site"}.`;
  if (q.includes("roof")) return `Roof access: ${s.roof_access ?? "verify on site"}.`;
  if (q.includes("hazard") || q.includes("chem") || q.includes("danger")) {
    const hz = (s.top_hazards ?? []).map((h) => (typeof h === "string" ? h : `${h.type} at ${h.location}`)).join("; ");
    return `Hazards: ${hz}.`;
  }
  if (q.includes("hydrant") || q.includes("fdc")) return "Not in the approved plan. Verify on site.";
  if (q.includes("stor") || q.includes("floor")) return `${s.stories} stories, built ${s.year_built}.`;
  return "I can only answer from the approved pre-plan. Try asking about stairs, standpipe, roof access, or hazards.";
}
