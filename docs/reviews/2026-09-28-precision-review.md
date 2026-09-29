# S6 Pi precision review

**Adjudicated 2026-09-28 by the agent under owner delegation (checklist G.a).
On the unchanged 100-row sample, Phase 4 location quality fails both ROADMAP
bars: 4 wrong geocodes (bar < 1%) and 6 sampled venues with a confirmed
duplicate record (bar < 2%). Pi gate 1a (location quality) stays closed. The
URL-resolution gate is now separate (1b) and does not depend on these rates.**

Labels live in the [reviewed JSON](data/2026-09-28-precision-review/reviewed.json):
`label` (+ `label_by: "agent (owner-delegated 2026-09-28)"`) is separate from the
first reviewer's `agent_assessment`; `sample_hand_check` holds all 100 sampled
rows; `label_criteria` and `sample_rates` hold the rules and the numbers below. A
`null` label means unresolved and is never counted as correct. The denominator
stays 100.

## Adjudicated results

| Measure (100-row sample) | Confirmed | Unresolved | 95% interval (confirmed) | ROADMAP bar | Result |
|---|---:|---:|---|---|---|
| Wrong geocodes | **4** | 17 | 1.1% - 9.9% | < 1% | **Fails**, even at the lower bound |
| Sampled venues with a duplicate record | **6** | 11 | 2.2% - 12.6% | < 2% | **Fails** on the point estimate |
| Redundant rows (a row in a k-record cluster counts (k-1)/k) | 3.2% | | | < 2% | Fails on the point estimate; a 100-row sample cannot bound it below 2% either way |

If every unresolved row were wrong, the geocode rate would be 21%; no
assignment of the unresolved rows brings it under 1%. The corpus-wide detector
figure used before (23 confirmed pairs / 9,996 = 0.23%) is **not** a duplicate
rate: the sample check below found twins the detector cannot see.

Queue labels: duplicate candidates 23 duplicate / 4 distinct / 16 unresolved
(unchanged from the assessments after review); flagged geocodes 25 ok / 4 wrong /
16 unresolved (was 20 / 3 / 22).

### Criteria (set under the delegation)

- **Geocode ok:** address corroborated by business/municipal/marketplace evidence,
  and an official pin or independent geocoder match of that address within 150 m
  of the saved point (the audit's own tolerance).
- **Geocode wrong:** address corroborated, no evidence of a move, and the saved
  point > 1,000 m from an official pin or geocoder match. 1,000 m is beyond the
  largest Census error this packet measured against an official pin (575 m,
  Dutch Bros).
- **Unresolved:** everything else (150-1,000 m on interpolating geocoders only,
  no geocode, uncorroborated venue, address conflict).
- **Duplicate:** another current record for the same outlet at the same time
  (legal/trading/location-label names included). Rename-versus-succession pairs
  stay unresolved: under ADR-0012 a succession is a new business, so its defect is
  lifecycle, not duplication. Virtual-brand granularity stays unresolved (as D16).

### What changed from the first-pass assessments

- **Five borderline geocodes → ok** (Wayback 142.6 m, Grove 147.4 m, Express
  Teriyaki 146.0 m, Wingstop 139.0 m, Jasper's 149.5 m): each has a corroborated
  address and a Census match inside the audit's 150 m tolerance, the same rule
  that let the 55 unflagged rows pass the automated check.
- **Lali Son (15606) → wrong:** the official ordering site's pin and address
  (1500 S Bagdad Rd) are 2,595.5 m from the saved point; the record's partial
  address "1500 S" matches the official house number.
- **P. Terry's MLK (9336) wrong is now doubly supported:** records 14829
  ("P. Terry's Burger Stand") and 14832 ("MLK (24 Hours)", the official page
  title) sit at 517 W MLK, 1,638 m from 9336, next to the Census match.

### Sample hand-check (all 100 rows)

- **55 unflagged rows:** the cached Nominatim response from the original audit
  was re-measured (all 0.4-145.8 m) and the business at each address was looked
  up. 54 addresses are corroborated (`ok`); El Pollo Regio at 500 E Ben White
  (5469) is not (no branch there on the chain's list), so it stays unresolved.
- **Duplicates, searched for every sampled row** in `venues.json` (same
  house-number street line or name similarity ≥ 0.6 within 300 m, same
  fingerprint within 1 km, same address at any distance). Six confirmed:

| Sampled row | Twin(s) | Evidence |
|---|---|---|
| 9336 P. Terry's (MLK) | 14829, 14832 "MLK (24 Hours)" | [official page](https://pterrys.com/locations/mlk-517-w-mlk-jr-blvd-austin-texas-78701/) |
| 2109 El Sol y La Luna | 7497 "El Sol Y La Luna Restaurant", same address | [City vendor record](https://services.austintexas.gov/edims/document.cfm?id=142912) |
| 27480 Pinthouse Pizza | 27456, same address, 739.5 m apart | [one Round Rock location](https://pinthouse.com/pizza-round-rock) |
| 3585 "Main St & I-35" | 3588 Whataburger, 1.0 m | [Whataburger #1000 page title](https://locations.whataburger.com/tx/buda/670-old-san-antonio-rd.html) |
| 4965 Whataburger | 4968 "Spirit of Texas Dr & Presidential Blvd" | [Whataburger #1181 page title](https://locations.whataburger.com/tx/austin/2901-spirit-of-texas-dr-100.html) |
| 21183 Jefes | 21189 "Taqueria Jefes", 7.9 m | [official site: one outlet](http://www.jefesmex.com/location) |

  Eleven stay unresolved (probable Shake Shack label record, Dutch Bros vs
  "Palm Valley", a food truck at two addresses, an announced-name LLC for Il
  Brutto, three rename/succession pairs, two Denny's virtual brands, Torchy's HQ
  entity records); each has a note in `sample_hand_check`.

### Why the detector missed them

The audit detector (`apps/discovery/audit.py`) needs co-location **and** similar
names. It cannot see (a) twins separated by a bad coordinate (P. Terry's MLK,
El Sol, Pinthouse; also P. Terry's #14 and Taco Bell at 13770 N Hwy 183 outside
the sample) or (b) chain **location-label records** named after the store's
locator label rather than the brand (Whataburger intersections, P. Terry's
"MLK (24 Hours)", "Congress (Downtown)", "Lake Creek"). A side finding for the
correction plan: `street_key` strips five-digit house numbers as ZIP codes
(`_ZIP`), so "13785 Research Blvd" equals "14028 Research Blvd"; this only adds
false candidates, but it should be fixed with the detector.

### Stale and non-venue records (not a ROADMAP bar, but they matter for Phase 5)

In the 55 unflagged rows alone: 7 reported closed (Snack Bar, Eats on 8th, Tutto
Gusto, Olamaie — closed 2026-07-19, before the 2026-08-19 release — Doc's
Motorworks 2016, Goldis, Short Stop) and 5 non-venues (the Quesoff III event,
Torchy's corporate HQ, an elementary-school cafeteria, a Denny's franchisee LLC,
a convenience store). Overture presence is not operation (ADR-0012 §3).

### Limits

Web evidence was gathered 2026-09-28 from official pages (fetched where noted)
and search-result listings; current pages may postdate the release. No business
was contacted and no imagery was inspected. Labels are the agent's under the
owner's delegation and can be revised in the JSON; the 100-row sample cannot
establish a tight population bound, which is why gate 1a asks for a fresh
sample after corrections.

## Gate consequence

The Pi gate is split (checklist, "Pi gate" rows):

- **1a Phase 4 location quality — closed.** Needs a correction plan, a durable
  coordinate-override mechanism ([proposed ADR-0014](../adr/0014-location-overrides.md):
  the lifecycle pass would otherwise undo a hand fix as a "relocation"), and a
  fresh-sample re-audit that passes both bars.
- **1b URL-resolution readiness — closed, independent of 1a.** URL records are
  GERS-keyed and never read coordinates, so these rates do not gate
  `resolve_urls`. Its real risk is menu-URL precision (S4 verifier 0.605 at venue
  level; unchecked platform pages; saved URLs never re-verified). See
  [proposed ADR-0015](../adr/0015-menu-url-reverification.md).

---

## First-pass research (2026-09-28, agent assessments)

The sections below are the first reviewer's research, unchanged except for
heading levels. Their "pending owner confirmation" status is superseded by the
adjudication above.

**All 43 duplicate candidates and 45 geocode flags reviewed. Pi gate remains
closed: the research supports three wrong geocodes, with other cases unresolved.**
These are agent assessments for owner confirmation, not live data corrections
or final acceptance labels. Review date: 2026-09-28.

| Queue | Supported assessment | Unresolved |
|---|---|---:|
| 43 duplicate pairs | 23 duplicate; 4 distinct | 16 |
| 45 flagged sample geocodes | 20 corroborated; 3 wrong | 22 |

Read the [complete 88-row review](data/2026-09-28-precision-review/rows.md) for
names, Subject IDs, evidence links, map links, and the remaining question for
each unresolved case. The [reviewed JSON](data/2026-09-28-precision-review/reviewed.json)
separates `agent_assessment` from `label`; all owner labels remain null.

### Findings that affect the gate

The following three saved points conflict with their recorded addresses.
Distances below are to independently geocoded addresses, **not approved
replacement points**. Address evidence and geocoder agreement support the
wrong-coordinate assessments; historical business status still needs care.

| Subject | Venue | Recorded address | Census discrepancy | Evidence |
|---|---|---|---:|---|
| 9336 | P. Terry's | 517 W MLK Jr Blvd | 1,658 m | [Official MLK location](https://pterrys.com/locations/mlk-517-w-mlk-jr-blvd-austin-texas-78701/) confirms the address. Saved point is near Congress. |
| 15861 | La Parrilla | 209 Farley, Hutto | 21,219 m | [Hutto planning agenda](https://swagit-attachments.granicus.com/uploads/video/agenda_file/230381/5-16_HuttoPZ.pdf) and [merchant ordering page](https://www.toasttab.com/local/order/laparrilla/item-burrito_89efd551-23c2-456f-9f2b-525ce755d7bc) corroborate the address; both geocoders disagree with the saved point by about 21 km. |
| 2109 | El Sol y La Luna | 1224 S Congress | 5,471 m | [Historical City vendor record](https://services.austintexas.gov/edims/document.cfm?id=142912) corroborates the recorded address; both geocoders disagree by about 5.4 km. Historical relocation/closure must be resolved separately. |

If the owner confirms these assessments, the unchanged 100-row sample has
**at least 3% wrong geocodes**, exceeding the strict `<1%` criterion. This is
not a final error estimate: 22 flagged rows remain unresolved, and the 55
unflagged rows have automated corroboration only. Even one confirmed error in
this sample fails the strict threshold. The sample does not establish a tight
population confidence bound.

A fourth priority case is **Lali Son (15606)**. Its supplied address is only
`1500 S`; the [business ordering site](https://lalisonfastfoods.com/) gives
1500 S Bagdad Road and a point 2,595.5 m away. This remains unresolved until
release-time location versus later relocation is established.

Do not replace every distant point with a street geocoder result. **Dutch Bros
(26817)** has an [official location pin](https://www.dutchbros.com/locations/tx/round-rock/1700-e-palm-valley-blvd-850)
6.1 m from the saved point, while Census is 575.0 m away. **Buenos Sabores
(17301)** has an [official site pin](https://buenossabores.co/) 5.2 m away,
while Nominatim is 2.73 km away. These are supported geocoder mismatches.

### Duplicate and lifecycle findings

The 23 supported duplicate pairs are disjoint: 46 Subject IDs representing
23 redundant venue rows if all assessments are confirmed. That is **23 / 9,996
= 0.230% detected redundancy**, not a population duplicate-rate estimate or
proof of meeting `<2%`. The detector can miss duplicates. Likewise, the
original 43 / 9,996 candidate fraction is not an upper bound on actual duplicates.

Preserve distinct identities for the MLK and Congress P. Terry's locations;
bad coordinates caused this false candidate. The other distinct assessments
cover different hotel locations, a kitchen operator versus tenant, and separate
kitchen brands. Their current operating status is a separate question.

The 16 unresolved pairs include possible rebrands/successions, corporate
entities at shared mailing addresses, and a virtual sub-brand whose
Establishment granularity is unclear. Name or address similarity is not enough
to merge them. In particular, Fortune/Ruby Garden, Fig/Aroma, and Anderson
Mill Tavern/Pub require the conservative identity treatment in accepted
[ADR-0012](../adr/0012-venue-lifecycle.md).

Stale venues also surfaced: the duplicate NXNW listings refer to a brewery
[reported permanently closed in 2020](https://austin.eater.com/2020/4/17/21225052/north-by-northwest-closed-austin-brewery-restaurant-coronavirus).
Qdoba's [franchise disclosure](https://keycommercialcapital.com/wp-content/uploads/2022/05/Qdoba-FDD.pdf)
identifies the reviewed Guadalupe outlet as closed in 2020. These are lifecycle
issues even when the historical duplicate identity is clear. Other rows need
venue-type checks: a headquarters or mailing address is not necessarily a
customer-facing restaurant. Do not silently classify those as valid venues
because the street address geocodes.

### Method and reproducibility

Reviewed the rebuilt Subject IDs, exported Bronze source keys/websites, and
business/municipal evidence against the untouched audit. Deployment:
`3faae15e1cd452bcc00abfcd53b951ba3f46ae89`; Overture release: `2026-08-19.0`.
Full rebuild details are in the [execution record](2026-09-28-pi-rebuild-results.md).

A second pass submitted the 128 distinct public addresses in the review set
to Census batch geocoding with benchmark `4` (`Public_AR_Current`). Unit
suffixes were removed and common road spellings expanded; submitted addresses
are preserved in [input CSV](data/2026-09-28-precision-review/census-input.csv),
with the [response CSV](data/2026-09-28-precision-review/census-output.csv).
The [Census documentation](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/census-geocoder.html)
explains that its points interpolate street address ranges. They do not establish
rooftop accuracy, business occupancy, or current operations. Borderline distances
and contradictory business evidence remain unresolved. `ok` means supported
coordinate/address compatibility, not certified rooftop placement.

Official business pin coordinates and their calculated distances are retained
in the reviewed JSON for Dutch Bros, Buenos Sabores, and Lali Son. Other
assessments combine address evidence with Census cross-checks. Directory-only
evidence is weaker, may share upstream data with Overture, and is identified
in row notes. Current web pages may postdate the release; they do not establish
release-time operations. No business was contacted and no field visit or
satellite-image verification was performed.

The [100-row sample](data/2026-09-28-precision-review/sample.json) preserves the
denominator, including the 55 unflagged rows. Input hashes in the reviewed
JSON identify the raw export, automated worksheet, original pending review,
and source-record export. Raw artifacts and geocoder cache remain in
`var/audits/s6-20260928/`; the original `SHA256SUMS`, `review.json`, `review.md`,
and `worksheet.json` are unchanged. Research outputs use separate filenames.
The committed packet has its own `SHA256SUMS`; text line endings and the
sample file final newline are normalized, while original bytes remain in the
raw local packet.

### Next steps

1. Confirm or revise the three wrong-coordinate assessments, starting with
   P. Terry's and La Parrilla, then resolve El Sol's historical location and
   Lali Son's incomplete address. Use a dated business/parcel point before
   proposing any coordinate replacement.
2. Resolve the 22 outstanding geocode flags using storefront/tenant plans or
   business history. The row notes identify the specific missing evidence.
   Review the other 55 sampled venues before calling the sample hand-labeled;
   a successful geocoder match alone does not verify a business.
3. Confirm the 23 duplicate pairs and adjudicate the 16 ambiguous pairs.
   Keep rebrands, shared kitchens, and corporate addresses out of automatic
   merges. Use existing evented Identity commands with Evidence for any
   subsequently authorized correction; this packet performs no merges.
4. Prepare a reproducible correction plan that distinguishes source errors,
   address errors, lifecycle transitions, and non-venue records. Preserve raw
   Bronze observations and original audit outcomes. Rebuilding the same release
   unchanged would reproduce the defects. After corrections, re-audit the fixed
   cohort for regression and use a fresh representative sample for acceptance;
   do not remove difficult rows or change the denominator to manufacture a pass.
5. Open the Pi URL-resolution gate only after a passing confirmed audit.
   S2/S3/S4/S6 are merged and the rebuild is complete; **S6b is not Pi-gating**.
   S13 can proceed separately under accepted ADR-0012; **Phase 5 still requires
   S13 and its lifecycle acceptance tests**.

### Verification

Documentation/data review only; no runtime code, database values, or resolver
state changed. `make ci` passed locally: 378 tests passed, 580 skipped, 65%
coverage. Database tests skipped because no test database was configured for
this run; this is not new database acceptance. The previously deployed commit's
strict database acceptance is documented in the rebuild record/runbook.
Packet validation checks all 88 rows, source-ID coverage, counts, preserved null
owner labels, and checksums. Pre-commit is also run on the completed packet.
