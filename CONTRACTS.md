# FirstIn — internal contracts (build against these; do not change without updating this file)

Repo root: `firstin/`. Secrets live in `firstin/.env` (git-ignored). NEVER print or commit key values.

## Ports
- FastAPI agent server: `http://localhost:8000`
- Next.js dashboard: `http://localhost:3000` (Matterport SDK key only works on localhost)

## Citation object (every leaf fact)
```json
{"src": "costar|vexcel|matterport|inference", "id": "<record/tile/sweep/model id>", "conf": 0.0-1.0,
 "bbox": [x0,y0,x1,y1] | null, "url": "<image/scan deep link or null>", "from": ["costar.year_built", ...] | null}
```
A field with no evidence = `{"value": "VERIFY ON SITE", "cite": null}`.

## Demo building registry: `agent/cache/buildings.json`
```json
[{"building_id": "hou-001", "address": "...", "city": "Houston", "lat": 29.7, "lng": -95.3,
  "costar_id": "..." | null, "matterport_model_ids": ["..."], "has": {"costar": true, "vexcel": true, "matterport": true}}]
```

## Python tool modules (`agent/tools/*.py`) — plain functions, return JSON-serializable dicts, never raise on missing data (return {"error": ...})
Each module reads from `agent/cache/<source>/...` first (offline-safe), then live API if `FIRSTIN_LIVE=1` or cache miss.

- `tools/costar.py`
  - `costar_property(building_id: str) -> dict`  → {costar_id, address, year_built, stories, rba_sqft, building_class, property_type, construction?, ...raw, "cite": {...}}
  - `costar_tenants(building_id: str) -> dict`   → {tenants: [{name, use, naics?, floor?, sqft?, cite}], cite}
- `tools/vexcel.py`
  - `vexcel_tile(building_id: str, view: str = "ortho") -> dict` → {tile_id, image_path (local png/jpg under agent/cache/vexcel/), image_url (served at /static/...), lat, lng, gsd_m?, captured_at?, cite}
  - `vexcel_oblique(building_id: str, direction: "N|E|S|W") -> dict` (if API supports obliques)
- `tools/matterport.py`
  - `matterport_model(building_id: str) -> dict` → {model_id, name, address, floors: [...], rooms: [{label, floor, bounds?, id}], mattertags: [...], sweep_count, cite}
  - `matterport_panoramas(building_id: str, room_filter: str | None = None, limit: int = 6) -> dict` → {panos: [{sweep_id, floor, room, image_path, image_url, position}], cite}
- `tools/vision.py`
  - `describe_image(image_path: str, question: str) -> dict` → VLM (Anthropic claude, model from env FIRSTIN_MODEL, default `claude-sonnet-5-5`) answer with detections [{label, bbox, conf}]. Falls back to cached answer in `agent/cache/vision/` keyed by sha1(image+question).
- `tools/render.py`: `render_html(plan) -> path`, `render_pdf(plan) -> path`, `tts_brief(text) -> mp3 path` (macOS `say` → aiff→mp3 via ffmpeg fallback ok)
- `tools/publish.py`: `publish_preplan(plan_id) -> dict` (HITL-gated in agent)

Static files: FastAPI mounts `agent/cache` at `/static/cache` and `agent/out` at `/static/out`.

## HTTP API (FastAPI)
- `GET  /buildings` → registry list
- `POST /preplan {building_id}` → `{run_id}` (starts agent run in background)
- `GET  /stream/{run_id}` → SSE. Event `data:` JSON: `{"type": "todo|subagent_start|subagent_end|tool_call|tool_result|evidence|plan|interrupt|published|log|error|done", "ts": ..., "payload": {...}}`
- `GET  /plan/{run_id}` → current plan JSON (schema = README §7) + `status`
- `POST /approve/{run_id} {approved_by, edits?: {...}, decision: "approve"|"reject"}` → resumes interrupt
- `GET  /incab/active` → latest APPROVED plan summary: `{plan_id, address, stories, year_built, construction, top_hazards[3], stairs, roof_access, voice_brief, audio_url, approved_at}`
- `POST /ask {plan_id, question}` → `{answer}` answered ONLY from approved plan (voice Q&A)

## Plan schema
See README.md §7. `status`: `DRAFT | PENDING_APPROVAL | APPROVED | REJECTED`.
