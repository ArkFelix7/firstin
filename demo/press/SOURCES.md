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
