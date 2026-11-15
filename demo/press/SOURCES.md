# Press clippings: sources

Clips are in `clips/<slug>.png`, and the composite (1920×1080) is `collage.png`. Raw page captures go in `raw/`, which is git-ignored.
To regenerate from `firstin/`, run `node demo/press/capture.mjs` (headline crops) and then `node demo/press/make_clips.mjs` (cards + collage).

**Capture policy:** captures show only the headline, deck and byline/date region, never article body text. Nothing paywalled was bypassed. Government report crops (NIOSH, Texas SFMO) were rendered from the public PDFs. KPRC crops stop at the headline so the victims' photos are excluded.

**Fair-use decision:** `clips/` and `collage.png` are committed as small, attributed excerpts (headline-level) used for commentary in a pitch. `raw/` is excluded via `.gitignore`.

| Clip slug | Outlet | Exact headline | Date | URL | Method |
|---|---|---|---|---|---|
| southwest-inn-nbc-2013 | NBC News (Frank Heinz; Becky Bratu, Daniel Arkin) | Cause of blaze that killed four Houston firefighters under investigation | May 31, 2013 | https://www.nbcnews.com/news/us-news/cause-blaze-killed-four-houston-firefighters-under-investigation-flna6C10149696 | captured (headline + deck) |
| southwest-inn-kprc-niosh-2015 | KPRC 2 Click2Houston (Aaron Wische) | Final report on Southwest Inn fire finds eight contributing factors | July 20, 2015 | https://www.click2houston.com/news/2015/07/21/final-report-on-southwest-inn-fire-finds-eight-contributing-factors | captured (headline only; photo cropped out) |
| southwest-inn-kprc-dowling-2017 | KPRC 2 Click2Houston (Cory McCord) | Capt. Bill Dowling, firefighter injured in 2013 Southwest Inn fire, dies at 43 | March 8, 2017 | https://www.click2houston.com/news/2017/03/08/capt-bill-dowling-firefighter-injured-in-2013-southwest-inn-fire-dies-at-43 | captured (headline only) |
| niosh-f2013-16-cover | NIOSH FFFIPP, Report F2013-16 | 4 Career Fire Fighters Killed and 16 Fire Fighters Injured at Commercial Structure Fire – Texas | July 8, 2015 (rev. 2017, 2021) | https://stacks.cdc.gov/view/cdc/163331 | rendered from PDF p.1 header |
| sfmo-fy13-08-finding1 | Texas State Fire Marshal's Office, FFF FY 13-08 | "Finding 1: There were no pre-fire plans of this structure…" | 2014 | https://www.tdi.texas.gov/reports/fire/documents/fmloddhouston2013.pdf | rendered from PDF (printed p.38) |
| charleston-nbc-2007 | NBC News / Associated Press | Charleston mourns 9 firefighters lost in blaze | June 20, 2007 | https://www.nbcnews.com/id/wbna19331229 | captured (headline + deck) |
| niosh-f2007-18-cover | NIOSH FFFIPP, Report F2007-18 | Nine Career Fire Fighters Die in Rapid Fire Progression at Commercial Furniture Showroom – South Carolina | February 11, 2009 | https://stacks.cdc.gov/view/cdc/163618 | rendered from PDF p.1 header (AP photo excluded) |
| niosh-f2007-18-preplan-form | Charleston FD pre-plan form dated 04/26/06, reproduced in NIOSH F2007-18 Appendix III | (document, no headline) | 2009 | https://stacks.cdc.gov/view/cdc/163618 | rendered from PDF p.89 |
| i10-abc7-2023 | ABC7 Los Angeles (Amy Powell) | 10 Freeway closed in DTLA after massive fire at storage yard; state of emergency declared | November 12, 2023 | https://abc7.com/post/downtown-la-fire-10-freeway-closed/14044563/ | captured |
| i10-latimes-2023 | Los Angeles Times (Ruben Vives) | 10 Freeway in downtown L.A. shut down after fire; Newsom declares state of emergency | November 12, 2023 | latimes.com original paywalled; headline/byline/date verified via republication https://www.everand.com/article/683928155/10-Freeway-In-Downtown-L-A-Shut-Down-After-Fire-Newsom-Declares-State-Of-Emergency | **typeset** (labeled on the card) |
| i10-ap-hazards-2023 | Associated Press (Stefanie Dazio), via Fire Engineering | Investigators Found Fire, Safety Hazards on Land Under I-10 in Los Angeles Before Arson Fire | November 19, 2023 | https://www.fireengineering.com/fire-safety/investigators-found-fire-safety-hazards-freeway-arson/ | captured |
| i10-ap-repairs-2023 | Associated Press (Christopher Weber), via KOMO News | Speedy repairs to arson-damaged LA freeway promise early reopening, governor says | November 17, 2023 | https://komonews.com/news/nation-world/speedy-repairs-to-arson-fire-damaged-la-los-angeles-freeway-promise-early-reopening-governor-gavin-newsom-interstate-10-pallets-cars-construction-materials-sanitizer-arrests | captured |
| watson-abc13-2023 | ABC13 Houston (Chaz Miller) | Warehouse that exploded in Spring Branch 3 years ago unprepped employees for situation, report says | June 30, 2023 | https://abc13.com/13446456 | captured |

Not used: KHOU's Watson Grinding article (https://www.khou.com/article/news/local/watson-grinding-final-report/285-b3ccd69c-d649-4256-8336-6279ef1940fa) returned HTTP 403 to automated browsers, so ABC13 was used instead. KHOU's Texas SFMO story on Southwest Inn also returned 403. The Houston Chronicle and Post and Courier weren't captured (paywall/no stable article URL found).

**Collage (`collage.png`):** NIOSH F2013-16 header, NBC News 2013, Texas SFMO Finding 1, Charleston 2006 pre-plan form, NBC/AP Charleston 2007, ABC7 I-10 2023.

## Recent (2025 to 2026)

Added 2026-11-15. The same capture policy applies: headline, deck, and byline/date only, with crops stopping above any lead photo, so no victim photos appear. Nothing was paywalled, so nothing is typeset. NIOSH crops were rendered from the public PDFs (300 dpi, `pdftoppm`) and cropped with PIL, then put through the same card pipeline. The NIOSH banner photo is NIOSH's generic stock image, not an incident photo.

Regenerate with `node demo/press/capture.mjs recent-...` (the news slugs), then `node demo/press/make_clips.mjs`. That command now also writes `collage-recent.png` and `collage-timeline.png`. Three raws were trimmed after capture to remove ad/photo strips (Brooklyn, LAFD, WIS), and the `below:` values in `capture.mjs` were tightened to match.

| Clip (`clips/`) | Outlet | Exact headline | Date | URL | Method |
|---|---|---|---|---|---|
| recent-brooklyn-sunsetpark-2026 | Associated Press, via Spectrum News NY1 | Row house fire in Brooklyn kills 6 people and injures 9 | Nov. 5, 2026 | https://ny1.com/nyc/all-boroughs/ap-top-news/2026/11/05/house-fire-in-brooklyn-kills-6-people-and-injures-7-more-than-200-firefighters-respond1 | captured |
| recent-niosh-f2026-04-cover-2026 | NIOSH FFFIPP, Report F2026-04 | Truck Company Firefighter Dies after Floor Collapse at Basement Fire in a Multi-Family Residential Structure – Illinois | November 2026 | https://www.cdc.gov/niosh/firefighters/programs/pdfs/f202604.pdf | rendered from PDF p.i header |
| recent-durham-collapse-2026 | ABC11 Raleigh-Durham / WTVD (Cindy Bae) | Durham firefighter killed in the line of duty after roof collapse during building fire | Oct. 8, 2026 | https://abc11.com/post/firefighter-dies-durham-working-massive-fire-2-other-firefighters-injured/19921200/ | captured (headline only; video player cut) |
| recent-la-hope-st-2026 | Los Angeles Fire Department news release (spokesperson Jamie Stewart) | Major Emergency Structure Fire - Downtown Los Angeles - One Firefighter Injured | May 11, 2026 (fire May 10) | https://lafd.org/news/major-emergency-structure-fire-downtown-los-angeles-one-firefighter-injured | captured |
| recent-niosh-f2025-09-cover-2026 | NIOSH FFFIPP, Report F2025-09 | Career Firefighter Dies during Warehouse Fire at Unpermitted Film Studio – Georgia | March 2026 | https://www.cdc.gov/niosh/firefighters/programs/pdfs/f202509.pdf | rendered from PDF p.i header |
| recent-niosh-f2025-09-preplan-2026 | NIOSH F2025-09, Recommendation #8 | "At this incident, no pre-incident plan was available for crews to view enroute or on arrival…" | March 2026 | same PDF, printed p.28 | rendered from PDF |
| recent-chicago-altman-2026 | FOX 32 Chicago (Fox Chicago Digital Staff) | Chicago firefighter dies from injuries suffered battling North Side fire | Mar. 17, 2026 | https://www.fox32chicago.com/news/chicago-firefighter-dies-north-side | captured (crop stops above the scene photo) |
| recent-houston-braesridge-2025 | KPRC 2 Click2Houston (Christian Terry) | Woman found dead in collapsed apartment after large fire burns at SW Houston complex | Dec. 19, 2025 | https://www.click2houston.com/news/local/2025/12/19/apartment-fire-draws-emergency-response-in-sw-houston/ | captured (headline only) |
| recent-la-highrise-2025 | CBS Los Angeles (Chelsea Hylton) | Person dead after fire engulfs unit in downtown Los Angeles residential high-rise | Sept. 16, 2025 | https://www.cbsnews.com/losangeles/news/downtown-los-angeles-high-rise-fire/ | captured |
| recent-dekalb-warehouse-2025 | Atlanta News First (staff) | DeKalb County firefighter dies after battling blaze at Lithonia warehouse | Sept. 8, 2025 (upd. Sept. 9) | https://www.atlantanewsfirst.com/2025/09/09/dekalb-county-firefighter-dies-after-battling-blaze-lithonia-warehouse/ | captured (headline only; aerial photo cut) |
| recent-niosh-f2023-07-cover-2025 | NIOSH FFFIPP, Report F2023-07 | Career Firefighter Dies in Collapse involving Lightweight Construction with Two separate Maydays – South Carolina | April 2025 | https://www.cdc.gov/niosh/firefighters/programs/pdfs/face202307.pdf (also https://stacks.cdc.gov/view/cdc/232200) | rendered from PDF p.i header |
| recent-columbia-sc-collapse-2023 | WIS News 10, Columbia S.C. (Tiffany Sarvis) | Irmo firefighter dies after fighting Columbia apartment fire, 6 other firefighters injured | May 26, 2023 | https://www.wistv.com/2023/05/26/columbia-richland-fire-department-multiple-people-rescued-apartment-fire/ | captured (headline only) |

Notes:
- **Brooklyn:** the page's URL slug and banner still read "injures 7, more than 200 firefighters respond". The H1 captured is the updated AP headline, "injures 9".
- **Not used:** Insurance Journal's AP copy of the SC story (https://www.insurancejournal.com/news/southeast/2023/05/30/722576.htm) timed out in headless Chrome, so WIS was used instead. Post and Courier coverage of the NIOSH SC report is paywalled and wasn't typeset.

**`collage-recent.png`** contains Durham (ABC11), Brooklyn (AP), Chicago (FOX 32), NIOSH F2025-09 Rec. #8, Houston Braesridge (KPRC) and DeKalb (ANF), titled "2025 to 2026".
**`collage-timeline.png`** runs Charleston 2007 (NBC/AP), Houston 2013 (NBC), LA I-10 2023 (ABC7), then DeKalb Sept 2025, Houston Dec 2025, Chicago Mar 2026, LA May 2026 (LAFD), Durham Oct 2026 and Brooklyn Nov 2026. Grey dots mark 2007–2023 and red dots mark 2025–2026.
