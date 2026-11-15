# FirstIn web UI: design rationale

## 1. Critique of the previous UI (screens-v2)

An honest read of `demo/screens-v2/*`: it looked like a generated "fire command" concept, not a tool someone uses on shift.

- **Costume over function.** Near-black charcoal, neon red, amber, cyan, purple and green on every surface. Everything glowed, so nothing stood out. Hazards, the one thing that should alarm, were the same red as the logo and the main button.
- **Monospace everywhere.** About 97 `font-mono` uses for labels, ids and body copy, plus about 60 letterspaced all-caps micro-labels ("LIVE AGENT TRACE", "NFPA 1660 · PRE-INCIDENT PLAN · TACTICAL SHEET"). The type said "terminal aesthetic", not "readable document".
- **Decoration standing in for hierarchy.** A rotated rubber stamp for status. Diagonal hatched stripes on unsourced fields. Glow shadows, pulse rings, gradient sweeps, shimmer skeletons. A pulsing marker on the map. A full-screen red flash on the in-cab unit.
- **Boxes in boxes.** Every field had its own bordered cell inside a bordered section inside a bordered sheet, so the plan read as a grid of tiles instead of a document.
- **Neon pills for provenance.** Each field carried a colored dot, colored border and colored all-caps source name. Provenance mattered, but this styling made it louder than the value it described.
- **Marketing inside the product.** The evidence panel opened with a hero ("Every claim has a source.") and three icon tiles.
- **Copy.** 67 em dashes (for example "No citable evidence, dash, not guessed"), "AGENT ASSEMBLING PRE-PLAN", "DISPATCHING AGENT…". Sentences were ornaments, not instructions.

## 2. What we borrowed, and why

| Reference | What we took |
| --- | --- |
| **Palantir Blueprint / Gotham object views** | Property lists as label, value and provenance rows separated by hairlines. Dense 13 px body. Intent colors limited to status. Small, quiet tags for metadata. |
| **Esri Calcite, ArcGIS Dashboards, Field Maps** | A single restrained brand blue used sparingly for the primary action and selection, never as a background (Calcite's own rule). Four status colors used only for state. Light gray canvas basemap. A real Layers panel with basemap switch, layer toggles and a legend. A feature detail panel beside the map. |
| **First Due pre-incident planning, Mark43 RMS** | Light desk theme for the officer's workstation. The plan is a form-like document with NFPA sections. Hazards up front. A walk-through list for what still has to be checked in person. |
| **CI pipelines, Datadog APM** | The agent trace is a run log: steps with status icons, subagents as rows with elapsed time and call counts, and a collapsible event log in small monospace with a time column. |
| **GitHub PR review, document sign-off tools** | A docked review bar at the foot of the document: reviewer, Approve, Edit, Reject. After approval it states who approved it, when, and where it was published. |
| **Linear, Vercel, Stripe dashboards** | Polish: one sans at a strict type scale, hairline borders, flat buttons, `tabular-nums` for data, no gradients, almost no shadow. |
| **CAD mobile data terminals** | The in-cab screen is dark, high-contrast and glanceable, with a few large facts and one large flat touch target. |

## 3. Theme decision

- **Light for `/` and `/plan`.** These are desk tools for an officer reviewing a document. Light reads as enterprise, matches First Due and Mark43, prints well, and survives judge projectors, which wash out dark UIs.
- **Dark for `/incab`.** It runs in a cab at night, where a white screen ruins night vision. Same tokens, swapped by `data-theme="dark"` on the page root.

## 4. Tokens (`app/globals.css`)

- **Neutrals carry the UI:** `canvas`, `surface`, `subtle`, `muted`, `line`, `line-strong`, and `fg`, `fg-2`, `fg-3`, `fg-4` for text.
- **One accent, ink blue (`accent`).** It marks the primary action, selection, focus and links. We chose blue over the suggested muted red on purpose: in a fire product, red has to mean hazard. If the brand is red, red stops meaning danger. The logo keeps one small red stroke as its only brand red.
- **Status, desaturated, status only:** `ok`, `warn` and `danger`, each with a `-subtle` background. `danger` is used for hazards and Reject. `warn` is used only for "Verify on site".
- **Source attribution:** muted tints `src-costar`, `src-vexcel`, `src-matterport`, `src-inference` and `src-officer`. They appear only as an 8 px glyph whose shape also encodes the source: CoStar a square, Vexcel a diamond, Matterport a circle, inference a hollow ring, officer a triangle. Attribution therefore still works in grayscale and for color-blind readers.
- **Type:** Inter for UI, IBM Plex Mono only for machine values (run ids, record ids, coordinates, JSON, the event log) at 11 px. The scale is 11, 12, 13, 14, 16, 20, 24 and 32 px, with 13 px body. The only uppercase is the source of the data itself.
- **Spacing and shape:** a 4 px grid, 3 to 6 px radii, and two elevation tokens, used only on floating map panels and the document sheet.
- **Motion:** only functional spinners (`animate-spin`) and a progress bar while the agent runs. No pulses, sweeps, shimmer or entrance animations.

## 5. Primitives (`components/ui.tsx`)

`Button` (primary, secondary, danger, ghost), `StatusBadge`, `SourceGlyph`, `SourceTag`, `VerifyValue`, `PanelHeader`, `KV` (definition list with hairlines), `Th`/`Td` (data table), `Mono` and `Spinner`. All three pages are built from these.

## 6. Page notes

- **Map (`/`).** A white sidebar holds a search field, a segmented city control and a building table with data-layer availability columns, which use glyph headers with tooltips. Below it is the selected building's detail panel: an aerial thumbnail with its capture date, CoStar facts, scan counts, and the data layers with capture or scan dates. Then a recent-runs list from `GET /runs` and a docked primary "Generate pre-plan" action. The hero building is selected by default. The map shows the full registry (about 3,300 buildings) as a clustered MapLibre GeoJSON layer: quiet tinted clusters with counts and slate points. Featured, prepared buildings are drawn on top as labeled accent markers, and the selection is ink with an accent ring. The sidebar lists Featured first, then all buildings 50 at a time, and search uses `GET /buildings/search` when the server has it. The building details panel sits on the map, ArcGIS style.
- **Plan (`/plan/[runId]`).** Three panes: agent run, document, evidence.
  - The document opens with a summary strip: coverage, cited facts, verify-on-site count, and counts by source.
  - Hazards come next, as a ranked table with tactics and basis, collapsed to the top 5.
  - Then the NFPA sections as label, value and source rows, with tenants and exposures as tables.
  - The CoStar and Vexcel height cross-check is a quiet "Verified across 2 sources, 89% agreement" note.
  - Unsourced fields show a small warning label in the value position and are gathered into a walk-through checklist that can be ticked.
  - For inferred facts, the evidence pane resolves the whole evidence chain up front. It shows the primary visual inline (the annotated aerial tile for roof hazards, the scan panorama, or the CoStar record) and lists the other chain items with thumbnails that swap into the viewer.
  - The evidence pane works like a document viewer side panel: the fact, then the source (an aerial tile with a thin bbox, a 360° panorama with an outlined region, or a CoStar record with the matching line highlighted), then a citation table with source, record id, confidence, captured date, source field and region.
- **In-cab (`/incab`).** Status bar, address, key figures, ranked top hazards with a red rule, stairs, roof access, a large flat "Brief me" button and an "Ask" button. A new plan raises a calm banner instead of a full-screen flash.

## 7. Backend strings

The UI never shows an em dash. `lib/text.ts` splits dash-joined backend values into a value and a secondary detail ("Utility room" plus "Floor 1"), and `clean()` replaces dashes in prose. `/incab` prefers `top_hazards_detail` and falls back to parsing `top_hazards` strings.
