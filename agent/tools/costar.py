"""CoStar tool: building attributes + tenant roster from the CoStar data kit.

Data: the proprietary CoStar kit unzipped at agent/data/costar/kit/ (git-ignored; never commit it).
  kit/data/commercial-property.jsonl  one record per PropertyId (`id`)
  kit/data/location-occupancy.jsonl   one tenancy per record (`propertyId`, `tenantLocationId`)
  kit/data/company-detail.jsonl       one tenant company location per record (`id` = tenantLocationId)
  kit/commercial-properties.csv       PropertyId <-> MatterportModelId

Load order (offline-safe, fast):
  1. agent/cache/costar/<building_id>.json  (raw records pre-extracted by `build_cache`; git-ignored)
  2. lazy byte-offset indexes over the jsonl files (built once per process, only on a cache miss)

Every returned fact carries a CONTRACTS citation:
  {"src": "costar", "id": "<PropertyId or occupancy id>", "conf": 0..1, "bbox": None, "url": None,
   "from": None, "field": "<CoStar field path>"}
Never raises on missing data: returns {"error": ...}.

CLI:  python -m agent.tools.costar build   # (re)extract cache for every registry building with a costar_id
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import CACHE_DIR, costar_data_dir
from . import registry

CACHE_VERSION = 2
COSTAR_CACHE = CACHE_DIR / "costar"
TODAY = date.today()


# ------------------------------------------------------------------ paths
def kit_dir() -> Path:
    base = costar_data_dir()
    for cand in (base / "kit", base):
        if (cand / "data" / "commercial-property.jsonl").exists():
            return cand
    return base / "kit"


def _data(name: str) -> Path:
    return kit_dir() / "data" / f"{name}.jsonl"


# ------------------------------------------------------------------ enums (subset of kit/schemas/enums.json)
PROPERTY_TYPE = {0: None, 1: "Hospitality", 2: "Industrial", 3: "Land", 5: "Office", 6: "Retail", 7: "Flex",
                 8: "Sports & Entertainment", 9: "Mixed Use", 10: "Specialty", 11: "Multifamily", 13: "Healthcare",
                 14: None, 15: "Residential", 16: "Homes"}
BUILDING_CLASS = {1: "A", 2: "B", 3: "C", 4: "F"}
MATERIAL = {1: "Masonry", 2: "Metal", 3: "Reinforced Concrete", 4: "Steel", 5: "Wood Frame", 6: "Brownstone",
            7: "Limestone"}
SPRINKLER = {1: "Wet", 2: "Dry", 3: "ESFR"}
CONSTRUCTION_STATUS = {1: "Existing", 2: "Demolished", 3: "Proposed", 4: "Under Construction",
                       5: "Under Renovation", 6: "Converted", 11: "Under Redevelopment", 12: "Redeveloped"}
ELEVATOR = {1: "passenger", 2: "freight", 3: "escalator", 4: "parking"}
PARKING = {1: "Surface", 2: "Surface tandem", 3: "Covered", 4: "Covered tandem", 5: "Industrial trailer",
           6: "One-car garage", 7: "Two-car garage", 8: "Reserved", 9: "Attached garage"}
TENANCY = {1: "Single-tenant", 2: "Multi-tenant"}
UTILITY = {1: "Lighting", 3: "Gas", 4: "Water", 5: "Sewer", 6: "Heating"}
APT_STYLE = {1: "Garden", 2: "Mid-Rise", 3: "High-Rise", 4: "Low-Rise", 5: "Single-Family", 6: "Townhome"}
INDUSTRY = {1: "Accountants", 2: "Transportation", 3: "Engineers/Architects", 4: "Real Estate", 5: "Manufacturing",
            6: "Retailers/Wholesalers", 7: "Financial Institutions", 8: "Computers/Data Processing",
            9: "Public Administration", 10: "Agriculture/Mining/Utilities/Construction", 11: "Information",
            12: "Professional, Scientific & Technical Services", 13: "Personal Services", 14: "Insurance",
            15: "Health Care & Social Assistance", 16: "Law Firms", 17: "Accommodation & Food Services",
            18: "Administrative & Support Services", 19: "Agriculture/Forestry/Fishing",
            20: "Arts, Entertainment & Recreation", 21: "Educational Services", 22: "Management of Companies",
            23: "Mining, Quarrying, Oil & Gas Extraction", 24: "Rental & Leasing Services", 25: "Utilities",
            26: "Waste Management & Remediation", 27: "Wholesaler"}
OFFICE_TYPE = {1: "Main HQ", 2: "Divisional HQ", 3: "Corporate office", 4: "Franchise", 5: "Single location",
               6: "Retail store/branch", 7: "Industrial", 8: "On-site property management", 9: "No physical location"}
BUSINESS_STATUS = {1: "Active", 2: "Out of business", 3: "Shell company", 4: "Moved/merged", 5: "Individual owner",
                   6: "Undetermined", 7: "Pending delete", 8: "Active paper company"}
LEASE_TYPE = {1: "Direct", 2: "Sublease", 3: "Month-to-month", 4: "Owned", 5: "Assignment", 6: "Coworking"}
EXPIRATION = {1: "Moved to another property", 2: "Unable to confirm", 4: "Closed/bankrupt", 7: "Renewal",
              8: "Shed space", 10: "Moved out", 12: "Moved within building", 14: "Occupancy split"}
CONTACT_ROLE = {1: "developer", 2: "architect", 3: "recorded_owner", 4: "property_manager", 7: "true_owner"}
# DataSourceType of a floor size -> confidence
FLOOR_SRC_CONF = {1: 0.9, 2: 0.9, 4: 0.85, 8: 0.6, 11: 0.85, 18: 0.7}
SUBTYPE_PREFIX = re.compile(r"^(Flex|GeneralRetail|Specialty|Industrial|HealthCare|Hospitality|MultiFamily|Office|"
                            r"SportsAndEntertainment|Residential)_")


@lru_cache(maxsize=1)
def _enums() -> dict:
    p = kit_dir() / "schemas" / "enums.json"
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _humanize(s: str | None) -> str | None:
    if not s or s in ("Unknown", "None"):
        return None
    s = SUBTYPE_PREFIX.sub("", s).replace("_", " ").replace("Or", "/")
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    return s.replace(" / ", "/").strip()


def _enum(name: str, v) -> str | None:
    if v in (None, 0):
        return None
    return _humanize((_enums().get(name) or {}).get(str(v)))


def floor_label(code) -> str | None:
    """FloorName enum -> '1', '2', ..., 'Mezzanine', 'Basement', 'Lower Level'."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    if c == 24:
        return "1"
    if c == 25:
        return "2"
    if 27 <= c <= 149:
        return str(c - 24)
    if c in (0, 1):
        return None  # Unknown / UnknownFloor
    return _humanize((_enums().get("FloorName") or {}).get(str(c)))


# ------------------------------------------------------------------ lazy jsonl indexes
_ID_RE = re.compile(rb'^\{"id":(\d+)[,}]')
_PID_RE = re.compile(rb'"propertyId":(\d+)')


def _scan_index(path: Path, rx: re.Pattern, multi: bool) -> dict[int, Any]:
    idx: dict[int, Any] = {}
    if not path.exists():
        return idx
    off = 0
    with open(path, "rb") as fh:
        for line in fh:
            m = rx.search(line)
            if m:
                k = int(m.group(1))
                if multi:
                    idx.setdefault(k, []).append(off)
                else:
                    idx.setdefault(k, off)
            off += len(line)
    return idx


@lru_cache(maxsize=1)
def _property_index() -> dict[int, int]:
    return _scan_index(_data("commercial-property"), _ID_RE, False)


@lru_cache(maxsize=1)
def _occupancy_index() -> dict[int, list[int]]:
    return _scan_index(_data("location-occupancy"), _PID_RE, True)


@lru_cache(maxsize=1)
def _company_index() -> dict[int, int]:
    return _scan_index(_data("company-detail"), _ID_RE, False)


def _read_at(path: Path, offsets: list[int]) -> list[dict]:
    out = []
    with open(path, "rb") as fh:
        for o in offsets:
            fh.seek(o)
            try:
                out.append(json.loads(fh.readline()))
            except Exception:  # noqa: BLE001
                pass
    return out


@lru_cache(maxsize=1)
def _model_to_property() -> dict[str, int]:
    out: dict[str, int] = {}
    p = kit_dir() / "commercial-properties.csv"
    if p.exists():
        with open(p, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("MatterportModelId") and row.get("PropertyId"):
                    out[row["MatterportModelId"]] = int(row["PropertyId"])
    return out


def _models_for_property(pid: int) -> list[str]:
    return sorted(m for m, p in _model_to_property().items() if p == pid)


# ------------------------------------------------------------------ raw extraction (kit -> cache)
def _trim_property(r: dict) -> dict:
    r = dict(r)
    atts = r.pop("attachments", None) or []
    r["matterportModelIds"] = sorted({a.get("videoKey") for a in atts
                                      if a.get("videoExternalReferenceType") in (36, 234) and a.get("videoKey")})
    r["numAttachments"] = len(atts)
    apt = r.get("propertyApartment")
    if isinstance(apt, dict):  # floor-plan/unit lists are huge and irrelevant to a pre-plan
        apt = dict(apt)
        models = apt.pop("models", None) or []
        apt.pop("units", None)
        apt["numFloorPlans"] = len(models)
        r["propertyApartment"] = apt
    return r


def extract_raw(pid: int) -> dict | None:
    """Pull every record we need for one PropertyId out of the kit jsonl files."""
    off = _property_index().get(int(pid))
    if off is None:
        return None
    prop = _read_at(_data("commercial-property"), [off])
    if not prop:
        return None
    prop = _trim_property(prop[0])
    occs = [o for o in _read_at(_data("location-occupancy"), _occupancy_index().get(int(pid), []))
            if o.get("propertyId") == int(pid)]
    loc_ids = {o.get("tenantLocationId") for o in occs if o.get("tenantLocationId")}
    loc_ids |= {c.get("locationId") for c in prop.get("contacts") or [] if c.get("locationId")}
    cidx = _company_index()
    comps = _read_at(_data("company-detail"), [cidx[i] for i in loc_ids if i in cidx])
    return {"version": CACHE_VERSION, "property_id": int(pid), "extracted_at": datetime.now().isoformat(timespec="seconds"),
            "property": prop, "occupancies": occs, "companies": {str(c["id"]): c for c in comps}}


def build_cache(building_ids: list[str] | None = None) -> dict:
    COSTAR_CACHE.mkdir(parents=True, exist_ok=True)
    gi = COSTAR_CACHE / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n!.gitignore\n")
    done = {}
    for b in registry.list_buildings():
        bid = b.get("building_id")
        if building_ids and bid not in building_ids:
            continue
        pid = _resolve_pid(b)
        if not pid:
            done[bid] = "no PropertyId"
            continue
        raw = extract_raw(pid)
        if not raw:
            done[bid] = f"PropertyId {pid} not in kit"
            continue
        raw["building_id"] = bid
        (COSTAR_CACHE / f"{bid}.json").write_text(json.dumps(raw, ensure_ascii=False))
        done[bid] = f"PropertyId {pid}: {len(raw['occupancies'])} occupancies, {len(raw['companies'])} companies"
    _raw_for.cache_clear()
    return done


def _resolve_pid(b: dict) -> int | None:
    cid = b.get("costar_id")
    if cid and str(cid).strip().isdigit():
        return int(cid)
    m2p = _model_to_property() if kit_dir().exists() else {}
    for m in b.get("matterport_model_ids") or []:
        if m in m2p:
            return m2p[m]
    return None


@lru_cache(maxsize=32)
def _raw_for(building_id: str) -> dict:
    b = registry.get_building(building_id)
    if not b:
        return {"error": f"unknown building_id {building_id}"}
    f = COSTAR_CACHE / f"{building_id}.json"
    if f.exists():
        try:
            raw = json.loads(f.read_text())
            if raw.get("version") == CACHE_VERSION and raw.get("property"):
                raw["_source"] = f"cache/costar/{building_id}.json"
                return raw
        except Exception:  # noqa: BLE001
            pass
    if not _data("commercial-property").exists():
        return {"error": "costar data not available (no cache file and kit not unzipped)",
                "data_dir": str(kit_dir())}
    pid = _resolve_pid(b)
    if not pid:
        return {"error": "no CoStar PropertyId for this building (no costar_id and no Matterport model match)"}
    raw = extract_raw(pid)
    if not raw:
        return {"error": f"PropertyId {pid} not found in CoStar kit"}
    raw["_source"] = "kit/data/*.jsonl"
    return raw


# ------------------------------------------------------------------ helpers
def _cite(rec_id, conf: float, field: str | None) -> dict:
    return {"src": "costar", "id": str(rec_id), "conf": round(float(conf), 2), "bbox": None, "url": None,
            "from": None, "field": field}


def _date(s) -> str | None:
    return str(s)[:10] if s else None


def _parse_date(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _num(v):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _company_name(comps: dict, loc_id) -> str | None:
    c = comps.get(str(loc_id)) if loc_id else None
    return (c or {}).get("name")


NOTE_FLAGS = {  # fire-relevant phrases in CoStar's free-text property description
    "solar_pv": r"solar(?!ium)|photovoltaic",
    "tilt_up_concrete": r"tilt[- ]?up",
    "heavy_power": r"heavy power|\d{3,4}[- ]amp",
    "rail_adjacent": r"rail(way|road)? (tracks|spur|served)|adjacent to the \w+ railway|rail spur",
    "outdoor_storage_yard": r"outdoor storage|storage yard",
    "cold_storage": r"cold storage|freezer|refrigerat",
    "high_pile_storage": r"high[- ]pile|racking|clear height",
    "generator": r"generator",
    "fuel_storage": r"fuel tank|underground storage tank|\bust\b|diesel",
    "pool": r"\bpool\b",
    "parking_garage": r"parking garage|structured parking",
    "energy_management": r"energy management system",
}


# ------------------------------------------------------------------ property
def _shape_property(raw: dict, building: dict) -> dict:
    r = raw["property"]
    pid = r["id"]
    fields: dict[str, dict] = {}

    def put(key, value, field, conf):
        if value in (None, "", [], {}):
            return None
        fields[key] = {"value": value, "cite": _cite(pid, conf, field)}
        return value

    a = r.get("primaryAddress") or {}
    street = " ".join(str(x) for x in (a.get("streetNumber"), a.get("streetDirection"),
                                        str(a.get("streetName") or "").title() or None, a.get("streetType")) if x)
    address = f"{street}, {a.get('city')}, {a.get('state')} {str(a.get('postcode') or '')[:5]}".strip()
    rated = r.get("buildingRatingType") == 1
    put("address", address, "primaryAddress", 0.98)
    put("building_name", r.get("buildingName") or r.get("buildingPark"), "buildingName", 0.95)

    ptype = PROPERTY_TYPE.get(r.get("propertyType"))
    put("property_type", ptype, "propertyType", 0.95)
    subtype = _enum("PropertySubtype", r.get("propertySubtype"))
    put("property_subtype", subtype, "propertySubtype", 0.9)
    put("building_class", BUILDING_CLASS.get(r.get("buildingClass")), "buildingClass", 0.9 if rated else 0.85)
    put("building_rating_stars", r.get("buildingRating") or None, "buildingRating", 0.9 if rated else 0.8)
    put("construction_status", CONSTRUCTION_STATUS.get(r.get("constructionStatus")), "constructionStatus", 0.95)

    ev = r.get("constructionEvents") or []
    built = [e for e in ev if e.get("eventType") == 2 and e.get("year")]
    yb = min((e["year"] for e in built), default=None)
    put("year_built", yb, "constructionEvents[eventType=ConstructionComplete].year",
        0.97 if any(e.get("month") for e in built) else 0.93)
    ren_years = [e["year"] for e in ev if e.get("eventType") in (4, 5, 16, 17) and e.get("year")]
    ren_years += [int(str(x.get("endDate"))[:4]) for x in r.get("renovations") or [] if x.get("endDate")]
    put("year_renovated", max(ren_years) if ren_years else None,
        "constructionEvents[RenovationFinished].year|renovations[].endDate", 0.85)

    stories = r.get("numStoriesAboveGrade")
    put("stories", stories, "numStoriesAboveGrade", 0.95)
    put("height_ft", _num(r.get("buildingHeightInFeet")), "buildingHeightInFeet", 0.85)
    gba = _num(r.get("grossBuildingAreaSquareFeet"))
    rba = _num(r.get("rentableBuildingAreaSquareFeet"))
    put("gba_sqft", gba, "grossBuildingAreaSquareFeet", 0.93)
    put("rba_sqft", rba or gba, "rentableBuildingAreaSquareFeet" if rba else "grossBuildingAreaSquareFeet",
        0.93 if (rba and (not gba or rba <= gba)) else 0.85)
    put("typical_floor_sqft", _num(r.get("grossTypicalFloorSquareFeet")), "grossTypicalFloorSquareFeet", 0.85)

    # construction: CoStar material enum, refined by the description text (e.g. "concrete tilt-up")
    notes = " ".join(n.get("value") or "" for n in r.get("notes") or [] if n.get("value"))
    flags = sorted(k for k, rx in NOTE_FLAGS.items() if re.search(rx, notes, re.I))
    mat = MATERIAL.get(r.get("buildingConstructionMaterial"))
    construction = mat
    if mat and "tilt_up_concrete" in flags:
        construction = f"{mat} (concrete tilt-up per CoStar description)"
    put("construction_material", mat, "buildingConstructionMaterial", 0.85)
    put("construction", construction, "buildingConstructionMaterial", 0.85)

    # fire protection. hasSprinklers null = UNKNOWN (not "no") per kit docs.
    hs = r.get("hasSprinklers")
    put("sprinklers", {True: "Yes", False: "No"}.get(hs), "hasSprinklers", 0.85)
    put("sprinkler_type", SPRINKLER.get(r.get("sprinklerType")), "sprinklerType", 0.85)

    block_name = next((k for k in ("propertyIndustrial", "propertyFlex", "propertyOffice", "propertyRetail",
                                   "propertyApartment", "propertyHospitality") if isinstance(r.get(k), dict)), None)
    blk = r.get(block_name) or {}
    st = blk.get("structural") or {}
    elev: dict[str, Any] = {}
    for e in (st.get("elevators") or []) + (blk.get("elevators") or []):
        kind = ELEVATOR.get(e.get("elevatorType"))
        if not kind:
            continue
        if e.get("elevatorState") == 1:
            elev[kind] = e.get("numElevators") or "yes (count unknown)"
        elif e.get("elevatorState") == 2:
            elev.setdefault(kind, 0)
    put("elevators", elev or None, f"{block_name}.structural.elevators", 0.85)
    if block_name == "propertyApartment" and blk.get("isWalkup") is not None:
        put("walkup", bool(blk.get("isWalkup")), "propertyApartment.isWalkup", 0.8)
    ch = st.get("ceilingHeightFeet")
    put("ceiling_height_ft", _num(ch), f"{block_name}.structural.ceilingHeightFeet", 0.85)
    put("slab_to_slab_ft", _num(st.get("slabToSlabHeightFeet")), f"{block_name}.structural.slabToSlabHeightFeet", 0.85)
    put("floor_load_psf", _num(st.get("floorLoadPoundsPerSquareFoot")),
        f"{block_name}.structural.floorLoadPoundsPerSquareFoot", 0.8)
    docks = sum(blk.get(k) or 0 for k in ("numExternalLoadingDocks", "numInternalLoadingDocks"))
    put("loading_docks", docks or ("yes (count unknown)" if blk.get("hasLoadingDocks") is True else None),
        f"{block_name}.numExternalLoadingDocks", 0.85)
    dib = blk.get("driveInBays") or {}
    if blk.get("hasDriveInBays") or dib.get("count"):
        put("drive_in_bays", dib.get("count") or "yes", f"{block_name}.driveInBays", 0.8)
    if blk.get("hasCranes"):
        put("cranes", blk.get("cranes") or "yes", f"{block_name}.cranes", 0.8)
    if blk.get("railAccess"):
        put("rail_access", True, f"{block_name}.railAccess", 0.8)
    el = blk.get("electric") or {}
    if el.get("ampsHigh") or el.get("voltsHigh") or el.get("hasHeavyPower"):
        pw = " ".join(x for x in (f"{el['ampsHigh']}A" if el.get("ampsHigh") else None,
                                  f"{el['voltsHigh']}V" if el.get("voltsHigh") else None,
                                  f"{el['numElectricCurrentPhases']}-phase" if el.get("numElectricCurrentPhases") else None,
                                  f"{el['numWiresCarryingElectric']}-wire" if el.get("numWiresCarryingElectric") else None) if x)
        put("power", (pw + (" (heavy power)" if el.get("hasHeavyPower") else "")).strip(), f"{block_name}.electric", 0.85)
    utils = sorted({UTILITY[u["utilityType"]] for u in blk.get("utilities") or [] if u.get("utilityType") in UTILITY})
    put("utilities", utils or None, f"{block_name}.utilities", 0.7)
    put("tenancy", TENANCY.get(blk.get("tenancyType")), f"{block_name}.tenancyType", 0.85)
    if blk.get("isOwnerOccupied") is not None:
        put("owner_occupied", bool(blk["isOwnerOccupied"]), f"{block_name}.isOwnerOccupied", 0.8)
    if block_name == "propertyApartment":
        put("apartment_units", blk.get("totalNumUnits"), "propertyApartment.totalNumUnits", 0.9)
        put("apartment_style", APT_STYLE.get(blk.get("apartmentStyleType")), "propertyApartment.apartmentStyleType", 0.85)

    # site
    spaces = sum((p.get("totalSpaces") or 0) for p in r.get("parking") or [])
    ptypes = sorted({PARKING[p["parkingType"]] for p in r.get("parking") or [] if p.get("parkingType") in PARKING})
    if spaces or ptypes:
        put("parking", {"spaces": spaces or None, "types": ptypes, "ratio_per_1000sf": r.get("parkingRatio") or None},
            "parking[]", 0.8)
    lot = _num(r.get("lotSize"))
    unit = r.get("lotSizeMeasurementType")
    acres = lot if unit == 2 else (round(lot / 43560, 2) if lot and unit == 1 else None)
    put("land_acres", acres, "lotSize", 0.9)
    if r.get("lotLengthInFeet") or r.get("lotWidthInFeet"):
        put("lot_dimensions_ft", f"{_num(r.get('lotWidthInFeet'))} x {_num(r.get('lotLengthInFeet'))}",
            "lotWidthInFeet,lotLengthInFeet", 0.8)
    zd = r.get("zoningDescription")
    if zd and zd != "None":
        put("zoning", f"{zd}" + (f" ({r['zoningLongDescription']})" if r.get("zoningLongDescription") else ""),
            "zoningDescription", 0.85)
    put("parcel_numbers", r.get("parcelNumbers") or None, "parcelNumbers", 0.95)

    # contacts: owner / manager / developer (names resolvable only when the location is in company-detail)
    comps = raw.get("companies") or {}
    people: dict[str, list] = {}
    for c in r.get("contacts") or []:
        role = CONTACT_ROLE.get(c.get("contactRole"))
        if role:
            people.setdefault(role, []).append(c)
    for role in ("true_owner", "recorded_owner", "property_manager", "developer"):
        for c in people.get(role, []):
            nm = _company_name(comps, c.get("locationId"))
            if nm:
                key = "owner" if role in ("true_owner", "recorded_owner") else role
                if key not in fields:
                    put(key, nm, f"contacts[contactRole={role}].locationId->company-detail.name", 0.8)
    owner_ids = list(dict.fromkeys(c.get("locationId") for c in people.get("true_owner", []) + people.get("recorded_owner", [])
                                   if c.get("locationId")))
    if "owner" not in fields and owner_ids:
        fields["owner_location_ids"] = {"value": owner_ids, "cite": _cite(pid, 0.8, "contacts[contactRole=TrueOwner].locationId")}

    # floors
    floors = []
    for f in r.get("floors") or []:
        fs = (f.get("floorSize") or {})
        floors.append({"floor": floor_label(f.get("floorName")), "property_floor_id": f.get("propertyFloorId"),
                       "sqft": _num(fs.get("squareFeet")) or None,
                       "cite": _cite(pid, FLOOR_SRC_CONF.get(fs.get("source"), 0.75), "floors[].floorSize.squareFeet")})
    floors.sort(key=lambda x: (not str(x["floor"] or "").isdigit(), int(x["floor"]) if str(x["floor"] or "").isdigit() else 0))

    if notes:
        put("description", notes.strip(), "notes[].value", 0.75)
    put("description_flags", flags or None, "notes[].value", 0.7)
    put("matterport_model_ids", r.get("matterportModelIds") or _models_for_property(pid) or None,
        "attachments[videoExternalReferenceType=36|234].videoKey", 0.99)
    photo = (r.get("primaryPhoto") or {}).get("attachmentUri")
    put("photo_url", photo, "primaryPhoto.attachmentUri", 0.95)
    put("website", r.get("propertyWebsiteUrl"), "propertyWebsiteUrl", 0.9)

    dq = ["CoStar values are as of CoStar's last research touch, not real time."]
    if hs is None:
        dq.append("hasSprinklers is null = UNKNOWN (not 'no sprinklers'); verify on site.")
    if not mat:
        dq.append("buildingConstructionMaterial is Unknown; construction must be inferred or verified.")
    if rba and gba and rba > gba:
        dq.append(f"RBA ({rba}) exceeds GBA ({gba}); fails kit consistency check.")
    if not r.get("rentableBuildingAreaSquareFeet"):
        dq.append("No RBA recorded; rba_sqft falls back to GBA.")

    out = {k: v["value"] for k, v in fields.items()}
    out.update({
        "costar_id": str(pid), "property_id": pid,
        "address": out.get("address") or building.get("address"),
        "city": a.get("city"), "state": a.get("state"), "lat": a.get("latitude"), "lng": a.get("longitude"),
        "floors": floors,
        "fields": fields,
        "data_quality": dq,
        "match": "costar_id" if building.get("costar_id") else "matterport_model_id",
        "source": raw.get("_source"),
        "cite": {"src": "costar", "id": str(pid), "conf": 0.95, "bbox": None, "url": photo, "from": None,
                 "field": "commercial-property"},
    })
    for k in ("year_built", "stories", "rba_sqft", "building_class", "property_type", "construction"):
        out.setdefault(k, None)
    return out


def costar_property(building_id: str) -> dict:
    """CoStar building attributes (year built, stories, area, class, type, construction, sprinklers,
    elevators, docks, power, parking, lot, zoning, owner, floors), every field cited to the PropertyId."""
    try:
        raw = _raw_for(building_id)
        if raw.get("error"):
            return {"error": raw["error"]}
        b = registry.get_building(building_id) or {}
        return _shape_property(raw, b)
    except Exception as e:  # noqa: BLE001 - tools never raise
        return {"error": f"costar_property failed: {type(e).__name__}: {e}"}


# ------------------------------------------------------------------ tenants
# Strong, fire-relevant terms looked for in a tenant's name + CoStar company bio. They are appended to `use`
# so the deterministic hazard rules (agent/hazards.yaml) can match on them.
USE_TERMS = [
    "restaurant", "taproom", "brewery", "brewpub", "craft beer", "bar & grill", "cocktail", "coffee", "cafe", "café",
    "bakery", "kitchen", "catering", "pizza",
    "pool supply", "pool chemical", "chemical", "chlorine", "janitorial supply", "propane", "welding",
    "battery", "batteries", "e-bike", "scooter", "solar", "robotics", "robot", "electric vehicle",
    "auto repair", "body shop", "collision", "tire", "automotive",
    "furniture", "mattress", "upholster", "apparel", "garment", "textile", "soap", "plastics", "foam", "paint",
    "printing", "warehouse", "logistics", "freight", "trucking", "moving", "storage", "cold storage", "distribution",
    "data center", "colocation", "laboratory", "biotech", "pharmaceutical", "dry clean", "cannabis",
    "synagogue", "church", "congregation", "worship", "daycare", "child care", "preschool", "kids",
    "fitness", "gym", "medical", "clinic", "surgery", "dental", "oxygen",
]
FOOD_TERMS = {"restaurant", "taproom", "brewery", "brewpub", "craft beer", "bar & grill", "cocktail", "coffee", "cafe",
              "café", "bakery", "kitchen", "catering", "pizza"}
OFFICE_SAFE_TERMS = {"synagogue", "church", "congregation", "worship", "daycare", "child care", "preschool", "robotics",
                     "surgery center"}
SPACE_CTX = {"Industrial": "industrial space", "Flex": "industrial space", "Retail": "retail space",
             "Office": "office space", "Multifamily": "residential building"}


def _use_terms(text: str) -> list[str]:
    t = f" {text.lower()} "
    hits = []
    for k in USE_TERMS:
        if re.search(rf"(?<![a-z]){re.escape(k)}", t) and not any(k in h for h in hits):
            hits.append(k)
    return hits


def _tenant_load(t: dict) -> tuple[int | None, str]:
    """Per-tenant occupant estimate + basis (daytime peak)."""
    sqft, emp, use = t.get("sqft"), t.get("employees"), (t.get("use") or "").lower()
    food = any(k in use for k in ("restaurant", "taproom", "brewery", "bar & grill", "coffee", "cafe", "bakery",
                                  "accommodation & food"))
    cowork = t.get("lease_type") == "Coworking" or "executive suites" in (t.get("business_type") or "").lower() \
        or any(k in (t.get("name") or "").lower() for k in ("industrious", "regus", "wework", "workspaces", "commondesk"))
    assembly = any(k in use for k in ("synagogue", "church", "congregation", "worship"))
    if food and sqft:
        return int(sqft / 15) + int(emp or 0), "IBC unconcentrated assembly 15 sf/person + staff"
    if assembly and sqft:
        return int(sqft / 15), "IBC assembly 15 sf/person (services)"
    if cowork and sqft:
        return int(sqft / 150), "coworking: IBC business 150 sf/person (employee count excludes members)"
    if emp:
        return int(emp), "CoStar numEmployees at this location"
    if sqft:
        f = 500 if "industrial" in use else 150
        return int(sqft / f), f"IBC {'storage 500' if f == 500 else 'business 150'} sf/person (no employee count)"
    return None, "no sqft or employee count"


def _shape_tenants(raw: dict, building: dict) -> dict:
    prop = raw["property"]
    pid = prop["id"]
    comps = raw.get("companies") or {}
    ptype = PROPERTY_TYPE.get(prop.get("propertyType"))
    ctx = SPACE_CTX.get(ptype or "", "space")
    floor_of = {f.get("propertyFloorId"): floor_label(f.get("floorName")) for f in prop.get("floors") or []}

    def one(o: dict) -> dict:
        c = comps.get(str(o.get("tenantLocationId"))) if o.get("tenantLocationId") else None
        pr = (c or {}).get("profile") or {}
        sp = o.get("spaces") or []
        sqft = sum(s.get("squareFeetOccupied") or 0 for s in sp) or None
        fls = [floor_of.get(s.get("propertyFloorId")) for s in sp]
        fls = list(dict.fromkeys(f for f in fls if f))
        suites = list(dict.fromkeys(str(s.get("suite")).strip() for s in sp if s.get("suite")))
        ind_code = pr.get("industryType") or o.get("industryType") or None
        industry = INDUSTRY.get(ind_code)
        bio = (pr.get("locationBio") or "").strip()
        name = (c or {}).get("name")
        btype = _enum("BusinessSubtype", pr.get("businessSubtype")) or _enum("BusinessType", pr.get("businessType"))
        terms = _use_terms(name or "")
        for k in _use_terms(bio):  # company bios are noisy; in offices only trust food/assembly/robotics terms
            if k not in terms and (ctx != "office space" or k in OFFICE_SAFE_TERMS
                                   or (ind_code == 17 and k in FOOD_TERMS)):
                terms.append(k)
        use = f"{industry} ({ctx})" if industry else None
        if terms:
            use = f"{use or ctx}; {', '.join(terms)}"
        move_in = _parse_date(o.get("moveInDate") or o.get("fromDate"))
        status = BUSINESS_STATUS.get((c or {}).get("businessStatus"))
        conf = 0.85 if c else 0.6
        if move_in and move_in < date(TODAY.year - 5, TODAY.month, 1):
            conf -= 0.1  # long-standing record; may be stale
        if status and status != "Active":
            conf = min(conf, 0.45)
        t = {
            "name": name or ("Unidentified tenant" + (f" (suite {suites[0]})" if suites else "")),
            "company": pr.get("companyName"),
            "use": use, "industry": industry, "industry_code": ind_code,
            "business_type": btype, "description": (bio[:280] + ("..." if len(bio) > 280 else "")) or None,
            "naics": None, "sic": None,  # not present in the CoStar kit
            "floor": fls[0] if len(fls) == 1 else (", ".join(fls) if fls else None),
            "suite": ", ".join(suites) or None, "sqft": _num(sqft),
            "move_in": _date(o.get("moveInDate")), "from_date": _date(o.get("fromDate")), "to_date": _date(o.get("toDate")),
            "future_move_in": bool(move_in and move_in > TODAY),
            "lease_type": LEASE_TYPE.get(o.get("leaseType")),
            "employees": (c or {}).get("numEmployees"),
            "office_type": OFFICE_TYPE.get((c or {}).get("officeType")),
            "business_status": status,
            "website": pr.get("websiteUrl"),
            "occupancy_id": o.get("id"), "tenant_location_id": o.get("tenantLocationId"),
            "cite": _cite(o.get("id"), conf, "location-occupancy" + ("+company-detail" if c else "")),
        }
        t["cite"]["property_id"] = str(pid)
        if o.get("toDate"):
            t["end_reason"] = EXPIRATION.get(o.get("expirationReason"))
        return t

    occs = raw.get("occupancies") or []
    cur = [one(o) for o in occs if not o.get("toDate")]
    cur.sort(key=lambda t: (-(t["sqft"] or 0), t["name"]))
    past = [one(o) for o in occs if o.get("toDate")]
    past.sort(key=lambda t: t["to_date"] or "", reverse=True)

    # occupant load (daytime peak) from employee counts / occupied sqft
    total, basis_n = 0, {"employees": 0, "sqft_factor": 0}
    for t in cur:
        n, basis = _tenant_load(t)
        t["occupant_load_est"], t["occupant_load_basis"] = n, basis
        if n:
            total += n
            basis_n["employees" if basis.startswith("CoStar") else "sqft_factor"] += 1
    apt_units = (prop.get("propertyApartment") or {}).get("totalNumUnits")
    frm = [f"costar:{t['occupancy_id']}" for t in cur if t.get("occupant_load_est")]
    load_val, low, high, est = None, None, None, total
    if apt_units:
        low, high = int(apt_units * 1.5) + total, int(apt_units * 2.2) + total
        est = int(apt_units * 1.85) + total
        load_val = (f"~{low:,}-{high:,} ({apt_units} apartment units x 1.5-2.2 residents"
                    + (f" + {total:,} commercial occupants)" if total else ")"))
        frm = [f"costar:{pid}.propertyApartment.totalNumUnits"] + frm
    elif total:
        low, high = int(total * 0.8), int(total * 1.25)
        load_val = (f"~{total:,} daytime ({basis_n['employees']} tenants by employee count, "
                    f"{basis_n['sqft_factor']} by occupied sf)")
    occ_load = ({"value": load_val, "estimate": est, "low": low, "high": high,
                 "cite": {"src": "inference", "id": "costar-occupant-load", "conf": 0.5 if basis_n["employees"] else 0.4,
                          "bbox": None, "url": None, "from": frm}}
                if load_val else {"value": "VERIFY ON SITE", "cite": None})

    dq = []
    if not cur:
        dq.append("No current tenancies recorded (all CoStar occupancies have ended or none exist).")
    unk = sum(1 for t in cur if not t["tenant_location_id"])
    if unk:
        dq.append(f"{unk} current tenancies have no identified tenant (null tenantLocationId).")
    fut = sum(1 for t in cur if t["future_move_in"])
    if fut:
        dq.append(f"{fut} tenancies have a move-in date in the future (leased, not yet occupied).")
    dq.append("Current = CoStar occupancy with no toDate; a tenant may have left since CoStar last researched it.")
    dq.append("CoStar company records carry no NAICS/SIC codes; `use` is CoStar industryType + terms from the company profile.")

    return {
        "costar_id": str(pid), "property_id": pid,
        "tenants": cur,
        "tenant_count": len(cur),
        "identified_count": len(cur) - unk,
        "total_sqft_occupied": int(sum(t["sqft"] or 0 for t in cur)) or None,
        "former_tenants": past[:15],
        "former_tenant_count": len(past),
        "occupant_load_estimate": occ_load,
        "data_quality": dq,
        "source": raw.get("_source"),
        "cite": {"src": "costar", "id": str(pid), "conf": 0.85, "bbox": None, "url": None, "from": None,
                 "field": "location-occupancy[propertyId]"},
    }


def costar_tenants(building_id: str) -> dict:
    """CoStar tenant roster (current occupancies joined to company detail): name, use/industry, floor, suite,
    sqft, move-in, employees, plus an inferred occupant-load estimate."""
    try:
        raw = _raw_for(building_id)
        if raw.get("error"):
            return {"error": raw["error"], "tenants": []}
        b = registry.get_building(building_id) or {}
        return _shape_tenants(raw, b)
    except Exception as e:  # noqa: BLE001
        return {"error": f"costar_tenants failed: {type(e).__name__}: {e}", "tenants": []}


if __name__ == "__main__":  # python -m agent.tools.costar build [building_id ...]
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        print(json.dumps(build_cache(sys.argv[2:] or None), indent=1))
    else:
        print(__doc__)
