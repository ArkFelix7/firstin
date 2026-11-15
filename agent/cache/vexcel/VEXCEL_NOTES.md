# Vexcel notes (FirstIn)

## API + auth
- Vexcel API 2.0, base `https://api.vexcelgroup.com/v2`. The full OpenAPI 3.1 spec is public at `GET /v2/api-docs`; the Swagger UI needs a login.
- Auth: send the `X-API-KEY: $VEXCEL_API_KEY` header. The key is the `vfa_...` value in `firstin/.env`. `?api_key=` also works (WMTS uses it). No login or token exchange is needed.
- Coverage confirmed in LA and Houston. The tested points are in LA collections `us-ca-losangeles_rf07-2026` (urban-r, Jul 2026) and `us-ca-losangeles-2025` (urban), and Houston collections `us-tx-houston-2026` and `us-tx-pearland-2026` (urban, Jan 2026).

## Endpoints we use
| Purpose | Endpoint | Key params |
|---|---|---|
| Ortho collections and dates | `GET ortho/collections` | `wkt=POINT(lng lat)`, `layer=urban,urban-r`, `include=layer,collection,first-capture-date,last-capture-date,max-zoom,product-type` |
| Ortho image | `GET ortho/extract` | `wkt=POINT`, `layer`, `collection`, `bbox-dimensions=W,H` (ground metres), `image-format=jpeg` |
| Oblique search | `GET oriented/query` | `wkt`, `layer=urban`, `product-type=oblique-{north,east,south,west}\|nadir`, `order-by=collection-last-capture-date-desc,image-center-distance-asc`, `total-records=1`, `include=image-name,capture-date,collection,product-type,layer` |
| Oblique image | `GET oriented/extract` | `image-name`, `wkt=POINT`, `bbox-dimensions=120,120`, **`crop=bbox`**, `image-format=jpeg` |
| AI property and structure elements | `GET property/extract` | `wkt=POINT`, `buffer-meter=60` |
| DSM / DTM elevation | `GET dsm/elevation`, `GET dtm/elevation` | `wkt` (POINT or LINESTRING), `layer=urban` (returns `POINT Z` / `LINESTRING Z`) |

Other endpoints that exist but are unused: `ortho/wmts`, `ortho/tile`, `oriented/transform-points` (world to pixel on the full oblique frame), `dsm/extract` (raster DSM), `structure/extract` (returned 404 at our test point; `property/extract` covers it), `property/report` (PDF report), `3d/tileset`, `elements/detect`, `damage/*` (graysky disaster events), and `ogc-api`.

## Derived layers available
`property/extract` returns these for each structure in the parcels within the buffer. The keys are flat and dotted, for example `roof-characteristics.material.class`.
- Footprint polygon (WKT) and footprint area in m².
- Roof:
  - material (shingle, tile, metal, membrane, shake, gravel) with a score
  - shape (flat, gable, ...)
  - condition on a 1-5 scale (1 = severe, 5 = excellent)
  - tree cover %
  - centroid
- Roof objects: AC-unit count, roof vents, skylights, chimneys, solar, satellite dishes.
- Roof defects: discoloration, water pooling, rust, structural damage, tarp, missing material, debris, patch.
- Building type class (commercial, condo_apartment, institutional_buildings, ...).
- Ground elevation and defensible-space zones.
- Parcel-level counts: vehicles, pools, hardscape.
- Metadata: GSD, `ortho-date-estimate`, collection.
- `eave-height`, `maximum-roof-height` and `number-of-stories` came back null at every point we tried. We compute height ourselves as DSM minus ground.

## Implemented in `agent/tools/vexcel.py`
All functions return a dict and never raise (errors come back as `{"error": ...}`). They read the cache first and go live when `FIRSTIN_LIVE=1` or on a cache miss. A cache entry is also invalidated when the building's coordinates change.
- `vexcel_tile(building_id, view="ortho")`. `view` can be:
  - `ortho`: 120 m square at native GSD (about 6.2 cm in LA, 6.5 cm in Houston)
  - `context`: 300 m square, for hydrants, staging and exposures
  - `N`, `E`, `S` or `W`: redirects to `vexcel_oblique`

  It returns:
  - `tile_id`, `image_path`, `image_url` (`/static/cache/vexcel/<id>/<view>.jpg`)
  - `preview_url` (1600 px, scaled by `preview_scale`)
  - `lat`, `lng`, `gsd_m`, `captured_at`, `collection`, `layer`
  - `georef`: `bounds` N/S/W/E, `center_px`, and the EPSG:3857 affine
  - `cite`
- `latlng_to_px(georef, lat, lng)` and `px_to_latlng(georef, x, y)` convert between map coordinates and pixels for drawing citation bboxes on ortho and context images.
- `vexcel_oblique(building_id, direction)` takes N, E, S or W and returns:
  - the image (roughly 1700-2000 px, building at the centre)
  - `tile_id`, which is the Vexcel image-name
  - `captured_at`, `camera_looking`, `shows_facade`
- `vexcel_roof(building_id)` returns:
  - `target`: footprint, roof material/shape/condition, roof objects, defects, building type, `height_est_m`, `stories_est`, `height_basis`
  - `exposures`: neighbouring structures within 30 m, each with side (N..NW), gap in m, type and roof
  - `cite` (the raw JSON is saved in `property_raw.json`)
- `vexcel_footprint(building_id)` returns the footprint in lat/lng plus `polygon_px` and `bbox_px` on the cached ortho and context images.
- The `*_at(lat, lng, ..., building_id=None)` variants work without the registry.

## Cache (`agent/scripts/vx_cache_all.py`)
For each building in `buildings.json` the script writes to `agent/cache/vexcel/<id>/`:
- `ortho.jpg`, `context.jpg` (plus `_1600` previews and `.json` metadata)
- `oblique_{N,E,S,W}.jpg` (plus `.json`)
- `roof.json`, `property_raw.json`, `footprint.json`
- `ortho_annotated.jpg`: footprint outlined in red, exposures marked in orange

It also writes a summary to `agent/cache/vexcel/index.json`.

Run it from `firstin/` with `uv run --python 3.12 --with httpx --with python-dotenv --with pillow python agent/scripts/vx_cache_all.py [--force] [--only id] [--watch MIN]`. Each building takes about 8 s.

Cached so far:
- hou-001 (The Ion): about 28 m tall, ~7 stories estimated
- hou-002 (Modera Washington): about 25 m
- la-001 (337 S Broadway): ~10 m; merged block footprint, so treat as low confidence
- la-002 (1601 Perrino Pl warehouse): ~9 m
- la-003 (10940 Wilshire): about 87 m, ~23 stories
- test-la-7083-hollywood
- test-hou-4010-bellfort

## Gotchas
1. **Coordinates.** Census geocodes in `buildings.json` were 30-210 m off and sometimes landed on the wrong building. For example, hou-001 resolved to a one-storey shop instead of The Ion. `_resolve` therefore uses coordinates in this order:
   1. `vexcel_lat`/`vexcel_lng`, if set (manual override)
   2. `matterport_geolocation`, if within 400 m; it landed inside the correct footprint for all 5 buildings
   3. the census lat/lng

   The coordinate used is reported as `coord_source`.
2. **`oriented/extract` with `image-name` ignores `bbox-dimensions` unless you also pass `crop=bbox`.** Without it you get the full frame of about 150 MP.
3. **Oblique naming.** `oblique-north` means the camera is looking north: the top of the image is roughly north and the building's **south** facade is visible. The S oblique shows the north facade, and so on. This was verified visually and is stored in each oblique's JSON as `shows_facade`.
4. Oblique pixels are not georectified. Cite the whole image, or a bbox the VLM finds. `oriented/transform-points` works on full-frame pixel coordinates, not on our crop.
5. **Ortho georef.** Output is EPSG:3857. The requested point sits exactly at pixel (w/2, h/2), and the pixel size is the native zoom-21 Web-Mercator size of 0.0746455 m. This was verified against the GeoTIFF version of the same request. Pillow cannot load Vexcel's GeoTIFF (XMP tag bug), so we use JPEG with analytic georef. Footprint overlays align to within about a pixel.
6. The ortho is not a true ortho. Tall buildings lean, so the roof polygon is offset from the base; see la-003. DSM heights are sampled on a grid inside the footprint (p90). For footprints over 5000 m², which are often several downtown row buildings merged into one block, we use p75 of samples within 25 m of the address point instead.
7. `stories_est = height / 3.8 m` is an inference and should be cited as `{src: inference}` together with the Vexcel cite. It is rough for warehouses and lobbies with tall floors.
8. Images carry a "Vexcel Imaging US, Inc. ©" attribution in the bottom-right corner. Keep it there.
9. The context JPEG is about 4900 px and 7 MB. Give the VLM `preview_path` and scale coordinates by `preview_scale`.
10. `ortho/collections` with `layer=urban,urban-r` picks the newest capture. In LA that is the urban-r refresh from Jul 2026; obliques there come from the Nov/Dec 2025 urban collection.
