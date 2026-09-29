# Location correction plan and Pi runbook (Pi gate 1a)

**Date:** 2026-09-28 (session S6c; corrections applier added 2026-09-29, S6e) ·
**Status:** plan committed; nothing applied on the Pi · **Inputs:** the adjudicated precision review,
[`reviewed.json` at b2bba73](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/data/2026-09-28-precision-review/reviewed.json)
(Subject ids are from the 2026-09-28 Pi rebuild), and
[ADR-0014](../adr/0014-location-overrides.md) (accepted 2026-09-28).

This is the first gate 1a item in the [README](../../README.md#gates): every confirmed
defect classified and mapped to a fix. Part 2 is the owner's runbook for the Pi
corrections and the fresh-sample re-audit (the remaining gate 1a items). The agent
wrote it but did not run it.

## Part 1: classification

Fix types:

- **Override:** an entry in `config/location_overrides.yaml` (ADR-0014). Durable
  across releases and rebuilds; applied by the next discovery run.
- **Merge:** `create_adjudication` + `remap_source_record` +
  `record_subject_change(operation="merge")`, one evented Identity change per cluster
  (ADR-0004 §5), applied from `config/identity_corrections.yaml` by the
  [corrections applier](#corrections-applier-s6e).
- **Retire:** `unassign_source_record` + `record_subject_change(operation="retire")`
  with an adjudication, from the same file.
- **None / watch:** no data change; recorded so the re-audit does not re-count it.

### 1. Source coordinate errors (4, all in the 100-row sample)

| Subject | Venue | GERS id | Overture point | Fix | Status |
|---|---|---|---|---|---|
| 15606 | Lali Son Fast Food | `663fbd55-4131-4da8-8e13-0228a1b6b0d0` | 30.575928, -97.872322 | Override to the official pin 30.555901, -97.858398, plus address "1500 S Bagdad Rd, Leander, TX, 78641" (basis `official_pin`) | **In the file** |
| 9336 | P. Terry's Burger Stand (MLK) | `63274178-3ab7-4bee-a1f8-26c3d27389ea` | 30.267153, -97.743073 | Merge into 14829 (see §2), **and** an override so a rebuild dedupes it | Override pending a qualifying basis |
| 2109 | El Sol y La Luna | `45273d1d-cb18-4e67-9ce4-cbe451bc93ae` | 30.224819, -97.796432 | Merge into 7497 (§2) and an override; first resolve whether 1224 S Congress was still operating at the release (lifecycle, §4) | Override pending basis + status |
| 15861 | La Parrilla LAC | `7fa18f65-78ed-4a78-ac99-0b3e0ba0d09a` | 30.630341, -97.745056 | Override to 209 Farley St, Hutto | Override pending a qualifying basis |

Only Lali Son has a qualifying basis on record. The other three have a Census match
(interpolating, so not enough alone) plus a Nominatim distance, but the Nominatim
*point* was never saved to the repo; the P. Terry's official page has no embedded pin
(checked 2026-09-28). To add each entry, the owner (or a later session with the audit
cache) takes the cached Nominatim result for the address from
`var/audits/s6-20260928/geocode` on the Pi and adds the entry only if it is within 50 m
of the Census point below (basis `two_geocoders`), or finds an official pin or parcel
record:

| Subject | Census point (2026-09-28) | Address to geocode |
|---|---|---|
| 9336 | 30.282065, -97.743318 | 517 W Martin Luther King Jr Blvd, Austin, TX 78701 |
| 2109 | 30.251897, -97.748878 | 1224 S Congress Ave, Austin, TX 78704 |
| 15861 | 30.543905, -97.547431 | 209 Farley St, Hutto, TX 78634 |

`corrects` is the Overture point in the first table, to 6 decimals. If it no longer
matches the current release, the run reports the entry stale
(`stale_override_ids`) and ignores it.

### 2. Duplicates

**Sampled rows with a confirmed twin (6).** Four are the kinds the co-location detector
cannot see (a bad coordinate or a location-label name):

| Sampled | Twin(s) | Kind | Fix |
|---|---|---|---|
| 9336 P. Terry's | 14829 P. Terry's Burger Stand, 14832 "MLK (24 Hours)" | misplaced twin + location label | Merge 9336 and 14832 into 14829; override 9336 (§1) |
| 2109 El Sol y La Luna | 7497 El Sol Y La Luna Restaurant | misplaced twin (same address) | Merge 2109 into 7497 (on-street point); override 2109 |
| 27480 Pinthouse Pizza | 27456 Pinthouse Pizza (739.5 m, Trail/Trl) | misplaced twin | Merge into whichever point matches the official Round Rock location; override the other if its point is > 1,000 m off, otherwise merge only |
| 3585 "Main St & I-35" | 3588 Whataburger (1.0 m) | location label | Merge 3585 into 3588 |
| 4965 Whataburger | 4968 "Spirit of Texas Dr & Presidential Blvd" | location label | Merge 4968 into 4965 |
| 21183 Jefes | 21189 Taqueria Jefes (7.9 m) | name variant | Merge 21189 into 21183 |

**Detector pairs labeled duplicate (23).** All are co-located name, legal-name or
address variants of one outlet; fix = merge, keeping the record whose point and
address match the official locator (review notes in `reviewed.json`):
D01 16548/16554 Taco Bell · D02 22923/22926 El Chilango · D03 1104/1113 SLAB BBQ ·
D04 16194/16218 Baskin-Robbins · D05 23184/23187 Baguette House · D06 25812/25815
Austin(s) Pizza · D07 3444/3447 IHOP · D09 12015/12018 The League · D12 17190/17211
Gatti's · D14 11523/11673 Austin Tea Exchange · D15 27579/27609 Salt Lick · D17
11772/11775 Lefty's · D20 14760/14763 House Park · D21 21243/21246 Stiles Switch · D27
14406/14424 Pluckers · D28 29625/29628 Papa Johns · D29 19185/19188 NXNW · D30
23424/23445 Yucatán Tacos · D31 13437/13440 Tiny's · D33 14322/14325 Qdoba · D35
2190/2193 El Marisquero · D38 10617/10632 Better Half · D40 16509/16521 Hunan Ranch.

**Unresolved (not corrected):** 16 detector pairs (including D08, 9336 vs the Congress
store 10167, which the §1 correction answers) and 11 sampled rows (probable Shake Shack
label record 7635, Dutch Bros vs "Palm Valley", a two-address food truck, Gatto Nero /
Il Brutto 8595, three rename/succession pairs, two Denny's virtual brands, Torchy's HQ
entity records). The re-audit labels any that reappear under the same criteria.

**Corpus-wide search (new).** `python -m apps.discovery.audit` now also writes
`twin_candidates` from `find_twins`: same house-number street line at any distance
(`misplaced` when > 150 m apart), name similarity ≥ 0.6 within 300 m, same fingerprint
within 1 km, and a location-label record ("Main St & I-35", "MLK (24 Hours)") within
50 m of a branded one. `street_key` no longer strips five-digit house numbers as ZIP
codes and folds common spellings (Trail/Trl, Martin Luther King/MLK). Known gap: a bare
place-name label with no street word or parenthetical ("Lake Creek") is found only by
the same-address rule.

### 3. Address errors (1)

Lali Son's Overture address is "1500 S"; the override supplies the full address (§1).

### 4. Lifecycle: closed or renamed (7 in the sample, not a ROADMAP bar)

Snack Bar 7491, Eats on 8th 28698, Tutto Gusto 12222, Olamaie 14823 (closed
2026-07-19), Doc's 7503, Goldis 5940, Short Stop 19449. Overture presence is not
operation (ADR-0012 §3); the absence rule closes them once two completed releases omit
them. Fix: **none / watch**; a manual closure is an evented change and is optional. El
Sol y La Luna (2109/7497) needs a status check before its merge.

### 5. Non-venues (5 in the sample, not a ROADMAP bar)

Quesoff III 10986 (event), Torchy's HQ 19398, Cool Cafe school cafeteria 26472, Rrh Den
LLC 23064 (franchisee entity), Short Stop 19449 (convenience store). Fix: **retire**,
optional before Phase 5, because they would otherwise get menu work.

## Corrections applier (S6e)

`python -m apps.discovery.corrections --actor <reviewer>` applies
`config/identity_corrections.yaml` (merge clusters with a survivor, retirements; each
with a rationale and evidence URL, keyed by GERS id so the file survives a rebuild)
through `assign_source_record`, `remap_source_record`, `unassign_source_record` and
`record_subject_change`, one human Adjudication per entry plus the records' Overture
Version Evidence. It is idempotent: an entry already in effect writes nothing, so a
re-run after a rebuild re-applies exactly what is missing. `--dry-run` reports and
rolls back; `--show-gers <subject id>...` prints Subjects' GERS ids and applies nothing.

Design decisions (owner, 2026-09-29):

- **Merged-away parents:** the duplicate's Organization and Place merge into the
  survivor's (their records, e.g. website and menu URLs, remapped first) when no current
  Establishment still uses them; otherwise they stay and are reported (`parents_kept`).
- **Retirements** keep the Place and Organization (the address and the operator still
  exist); the records go to `needs_review`, so discovery never re-mints them.
- **Survivor rule** (the agent's, in the file header): the record whose address and
  point match the official location page; on a tie, the trading name as that page shows
  it; then the lower Subject id.

A merged venue owns several Overture records, so the lifecycle leaves it alone
(ADR-0012's shared-source rule): the merged-away record's point never relocates the
survivor, and the venue closes only when every record is absent.

**In the file:** the 23 detector-pair merges (§2), GERS ids and notes from
`reviewed.json` at b2bba73, each checked against the pair's records.

**Pending entries.** The review data holds no GERS id for these Subjects (only the Pi
database does), so they are not in the file yet. Fill them with
`python -m apps.discovery.corrections --show-gers <ids>` on the Pi (read-only), add the
entries, review the diff and merge:

| Entry | Kind | Survivor (Subject) | Merge / retire (Subject) | Note |
|---|---|---|---|---|
| S9336 | merge | 14829 P. Terry's | 9336 (GERS `63274178-3ab7-4bee-a1f8-26c3d27389ea`), 14832 "MLK (24 Hours)" | plus the §1 override for 9336 |
| S2109 | merge | 7497 El Sol Y La Luna Restaurant | 2109 (GERS `45273d1d-cb18-4e67-9ce4-cbe451bc93ae`) | on-street point survives; operating status is a separate lifecycle question (§4) |
| S27480 | merge | 27480 Pinthouse Pizza (15.5 m from Nominatim at 2800 Hoppe Trail) | 27456 (739.5 m off, < 1,000 m: merge only, no override) | |
| S3585 | merge | 3588 Whataburger | 3585 "Main St & I-35" | location label |
| S4965 | merge | 4965 Whataburger | 4968 "Spirit of Texas Dr & Presidential Blvd" | location label |
| S21183 | merge | 21183 Jefes | 21189 Taqueria Jefes | official site lists one outlet |
| N10986 | retire | | 10986 Quesoff III | an event |
| N19398 | retire | | 19398 Torchy's HQ | an office |
| N26472 | retire | | 26472 Cool Cafe | a school cafeteria |
| N23064 | retire | | 23064 Rrh Den LLC | a franchisee entity |
| N19449 | retire | | 19449 Short Stop | a convenience store |

Evidence URLs for these rows are in `reviewed.json` (`duplicate_evidence_urls` or
`evidence_urls` of each sampled row).

## Part 2: runbook for the owner (not run)

Prerequisites: the corrections applier (S6e) merged; the Pi at the merged commit. Every step below is a command, never SQL.

1. **Back up** the Pi database, as in the 2026-09-28 rebuild (see the Staging section of
   the README).
2. **Fill in pending overrides.** For 9336, 2109 and 15861, check the cached Nominatim
   points against the Census points above; add an entry only on a qualifying basis.
   Review the diff; merge it.
3. **Apply overrides:** re-run discovery on the release already loaded, so no new
   Overture data arrives:

   ```bash
   python -m apps.discovery --release <the 2026-08-19 release path> \
     --expected-predecessor <same value as the last run, if any>
   ```

   Check the output: `overrides_applied` equals the number of entries,
   `override_stale=0`, `override_unmatched=0`, and the lifecycle report shows
   `relocated: 0` (overrides are in-place corrections). A stale id means the entry's
   `corrects` does not match the loaded release: fix the entry, do not force it.
4. **Merges and retirements:** fill the pending entries (above) with
   `--show-gers`, merge that diff, pull it on the Pi, then

   ```bash
   python -m apps.discovery.corrections --actor <your name> --dry-run
   python -m apps.discovery.corrections --actor <your name>
   ```

   Check the output: `merged` + `retired` + `satisfied` equals the number of entries,
   `unmatched=[]`, `skipped=[]`; read every `parents_kept` line. A re-run must report
   every entry `satisfied`. After any future rebuild, run it again after discovery.
5. **Verify:** `GET /v1/venues/<id>` for 15606 shows the override point and address;
   merged-away ids are no longer current.
6. **Re-audit on a fresh sample:** export current venues as for the 2026-09-28 audit,
   then

   ```bash
   python -m apps.discovery.audit --export <export.json> --worksheet <out.json> \
     --geocode-check --sample-size 100 --seed <new seed, e.g. gate-1a-reaudit-1>
   ```

   Hand-label all 100 rows under the README gate 1a
   criteria (geocode check and a twin search per row; `twin_candidates` is the
   corpus-wide starting list, not a substitute for the per-row search). Also re-check
   the corrected cohort: the four §1 venues and every §2 pair.
7. **Record the result** in the README gate 1a entry: pass = 0 confirmed wrong
   geocodes, at most 1 sampled venue with a confirmed duplicate, at most 5 unresolved
   per measure, with the worst case (unresolved counted as failures) beside it. Never
   drop rows or change the denominator.
