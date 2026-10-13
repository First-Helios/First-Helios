# Documentation drift review (2026-10-12)

**Branch:** `docs/drift-review-2026-10-12`, from `origin/main` at `efe229e` (#80 merged).
**Rule:** the code is ground truth (CLAUDE.md). A doc that disagrees with the code is
fixed or flagged here; no code changes.
**Scope:** README.md, ROADMAP.md, `docs/adr/`, `docs/reviews/`; CLAUDE.md and
`docs/spikes/` flag-only. No open PRs at review time, so nothing is "pending #NN".
**Blindness:** nothing under any `var/` directory, P5-12 outputs or label/page data
was read.

Classes: **A** factual drift, unambiguous fix; **B** wording/structure, no change of
meaning; **C** needs the owner. Line numbers are as of `efe229e`.

## Method

Five read-only sweeps, each finding re-checked by hand at the cited lines:

| Sweep | Checked | Raw candidates | Accepted |
|---|---|---|---|
| Relative links and `#anchors` (38 files) | 414 links, 135 anchors | 0 | 0 |
| Paths, modules, CLIs, flags, make targets in README/ROADMAP/CONTRIBUTING | 313 | 3 | 1 (D-08, widened to D-09) |
| Paths, modules, CLIs in ADR-0009..0016 and `docs/reviews/` | ~150 | 7 | 0 |
| Quoted numbers/versions in README/ROADMAP vs records and code | ~140 | 2 | 2 (D-01, D-02) |
| ADR index, Status lines, amendment cross-links, review reachability | 16 ADRs, 13 records | 13 | 4 (D-06, D-07, D-12, C-02) |

Main-session reads added D-03, D-04, D-05, D-10, D-11, B-01, C-01, C-03.

Current pipeline component versions in code: `prompt-v2.4`
(`packages/helios_parsing/prompt.py:68`), `chunk-v2.3` (`chunking.py:43`), `repairs-v6`
(`output.py:59`), `validator-v6` (`validator.py:78`), `segment-v2` (`segment.py:43`),
`jsonld-v1` (`jsonld.py:31`), classifier `classifier-v2`
(`apps/menu_pipeline/classifier.py:30-32`).

## A findings

### D-01 · README.md:95 · A · validator version

Evidence: `packages/helios_parsing/validator.py:78` `VALIDATOR_VERSION = "validator-v6"`.
Present-tense "validator v3" is stale (v4, v5, v6 since; ADR-0013 Amendments 9, 11, 13).

- Replace `JSON-LD menu reader (`jsonld.py`), and validator v3 (`validator.py`: per-row`
- With `JSON-LD menu reader (`jsonld.py`), and the validator (`validator.py`, now `validator-v6`: per-row`

### D-02 · README.md:98 · A · prompt version

Evidence: `packages/helios_parsing/prompt.py:68` `PROMPT_VERSION = "prompt-v2.4"`
(ADR-0013 Amendment 11).

- Replace `chunking (`chunking.py`), prompt v2.3 with its GBNF grammar, token cap and`
- With `chunking (`chunking.py`), the prompt (now `prompt-v2.4`) with its GBNF grammar, token cap and`

### D-03 · README.md:103-104 · A · spike parity stated as current

Evidence: the parity was shown at slice 2b (PR #58, `5f433cc`;
`docs/reviews/2026-10-03-p5-pipeline-v4-tuning.md:23` "PR #58 showed the ported repairs
and validator reproduce it"). v4–v6 changed rows and scores on the spike's own pages
(same record, lines 52 and 105: spike-33 numbers move between candidates).

- Replace `reading the gitignored labels and outputs. Chunks, rows, decisions and harness`
  `numbers match the spike's on its saved Pi output and gold rows.`
- With `reading the gitignored labels and outputs. At slice 2 (validator v3, prompt v2.3)`
  `chunks, rows, decisions and harness numbers matched the spike's on its saved Pi output`
  `and gold rows (#58); pipeline versions v4–v6 (below) changed them.`

### D-04 · README.md:93 · A · "nothing calls them in production yet"

Evidence: `packages.helios_parsing` is imported by `apps/menu_pipeline/classifier.py`
(the discovery verifier), `page_bronze.py`, `bundle.py`, `extraction.py`,
`menu_writes.py` and `apps/discovery/web_client.py`.

- Replace `Pure functions, nothing calls them in production yet: the segmented-text hash`
- With `Pure functions, called by the page classifier, `menu-page` Bronze and extraction (below): the segmented-text hash`

### D-05 · ROADMAP.md:520 · A · amendment range

Evidence: `docs/adr/0013-phase5-menu-pipeline.md:3` "as amended by Amendments 1–13";
Amendment 13 at line 996.

- Replace `> 2026-09-29 (Amendments 1–12). It replaces this`
- With `> 2026-09-29 (Amendments 1–13). It replaces this`

### D-06 · README.md:502, 507, 509, 510 · A · ADR index Status short forms

README:491 says "Status is the short form of each ADR's Status line". Four rows drop
what the Status line itself says (rows whose amendments sit on separate `Amended:` lines,
0009 and 0010, are left as is).

| ADR | Status line | Row now | Row after |
|---|---|---|---|
| 0008 | `0008:3-4` "Accepted — Unit A …; Unit B (staging deploy) not built" | `Accepted` | `Accepted (Unit A; Unit B, the staging deploy, not built)` |
| 0013 | `0013:3` "Accepted 2026-09-29 …, as amended by Amendments 1–13" | `Accepted` | `Accepted (Amendments 1–13)` |
| 0015 | `0015:3-4` "Accepted 2026-09-29 … as amended by Amendment 1" | `Accepted` | `Accepted (Amendment 1)` |
| 0016 | `0016:3-4` "Accepted 2026-09-30 …, as amended by Amendment 1" | `Accepted` | `Accepted (Amendment 1)` |

Exact rows (replace the trailing `| Accepted |` cell only):

- `| [0008](./docs/adr/0008-read-api-conventions.md) | Read-API framework and conventions (First Light) | Accepted |`
  → `| [0008](./docs/adr/0008-read-api-conventions.md) | Read-API framework and conventions (First Light) | Accepted (Unit A; Unit B, the staging deploy, not built) |`
- `| [0013](./docs/adr/0013-phase5-menu-pipeline.md) | Phase 5 menu pipeline: page classifier, on-device LLM extraction, validator | Accepted |`
  → `| [0013](./docs/adr/0013-phase5-menu-pipeline.md) | Phase 5 menu pipeline: page classifier, on-device LLM extraction, validator | Accepted (Amendments 1–13) |`
- `| [0015](./docs/adr/0015-menu-url-reverification.md) | Menu-URL precision before the first Pi run: re-verify saved menu URLs | Accepted |`
  → `| [0015](./docs/adr/0015-menu-url-reverification.md) | Menu-URL precision before the first Pi run: re-verify saved menu URLs | Accepted (Amendment 1) |`
- `| [0016](./docs/adr/0016-course-labels-for-the-price-index.md) | Course labels for the price index | Accepted |`
  → `| [0016](./docs/adr/0016-course-labels-for-the-price-index.md) | Course labels for the price index | Accepted (Amendment 1) |`

### D-07 · docs/adr/0015-menu-url-reverification.md:5 · A · Status line names the superseded verifier

Evidence: the ADR's own Amendment 1 text, `0015:192-195`: "the verifier bumped to
`classifier-v2`" (S6f); code `apps/menu_pipeline/classifier.py:30-32` loads
`config/page_classifier_v2.json`. Status-line drift only; amendment text untouched.

- Replace `verifier is ADR-0013's page classifier (`classifier-v1`) from the first Pi run`
- With `verifier is ADR-0013's page classifier (`classifier-v1`; `classifier-v2` since S6f, see Amendment 1) from the first Pi run`

### D-08 · README.md:351, 354 · A · Compose commands without the compose file or `.env`

Evidence: there is no compose file at the repo root; it is `infra/docker-compose.yml`.
`makefile:1-3`: "docker compose otherwise looks for .env next to the compose file
(infra/), never the repo-root .env … (R85)", hence
`COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env`. README:423 (the
Pi section) already uses that form; README:317-320 says `.env` is read only with
`--env-file .env`.

- Replace `(`docker compose exec api ...`), except `resolve_urls`: its page verifier is the`
- With `(`docker compose -f infra/docker-compose.yml --env-file .env exec api ...`), except `resolve_urls`: its page verifier is the`
- Replace `(`docker compose --profile menu run --rm worker python -m ...`).`
- With `(`docker compose -f infra/docker-compose.yml --env-file .env --profile menu run --rm worker python -m ...`).`

### D-09 · README.md:404, 405, 407 · A · extraction commands ignore `.env`

Evidence: as D-08. Without `--env-file .env`, `HELIOS_COMPOSE_DATABASE_URL` and
`POSTGRES_*` fall back to the compose defaults (`infra/docker-compose.yml:16-18, 41, 52,
95`), so a non-default `.env` (the Pi's) is silently ignored by the worker.

- Replace every `docker compose -f infra/docker-compose.yml --profile menu` (three
  occurrences, lines 404, 405, 407; no others in the file)
- With `docker compose -f infra/docker-compose.yml --env-file .env --profile menu`

### D-10 · README.md:458-473 · A · repository layout omits existing paths

Evidence: `apps/gold/refresh.py` (cited at README:35 as `python -m apps.gold.refresh`);
`config/location_overrides.yaml`, `config/identity_corrections.yaml` (README:78, 83);
`infra/docker-compose.pi.yml` (README:122, 415).

- After the line `  discovery/            Overture discovery, URL resolution, lifecycle, audit`
  insert `  gold/                 Gold refresh CLI (current_menu + price_index)`
- After the line `config/models.yaml      pinned model files (sha256, size, licence)`
  insert `config/location_overrides.yaml    reviewed coordinate/address corrections (ADR-0014)`
  and `config/identity_corrections.yaml  reviewed duplicate merges and retirements (S6e)`
- Replace `infra/                  Dockerfile and docker-compose.yml`
- With `infra/                  Dockerfile, docker-compose.yml, docker-compose.pi.yml (Pi core pinning)`

### D-11 · ROADMAP.md:168-179 (§4.1) · A · module inventory omits existing paths

Evidence: as D-10 (`apps/gold/`, `config/*`, `infra/docker-compose.pi.yml`).
`apps/menu_pipeline/` and `packages/helios_parsing/` are covered by ROADMAP:186 and are
left as is.

- After `  discovery/           # Overture seeding, website/menu-URL resolution, lifecycle, audit CLIs`
  insert `  gold/                # Gold refresh CLI (python -m apps.gold.refresh)`
- Replace `config/sources.yaml    # manual website / menu-URL registry`
- With `config/                # sources.yaml registry, models.yaml manifest, classifier weights, location overrides, identity corrections`
- Replace `infra/                 # Dockerfile, docker-compose.yml`
- With `infra/                 # Dockerfile, docker-compose.yml, docker-compose.pi.yml`

### D-12 · ROADMAP.md:613-614, 774 · A · promo summary omits ADR-0013 Amendment 5

Evidence: `docs/adr/0013-phase5-menu-pipeline.md:650-660` (Amendment 5): promotions get
their own label grain and "The promo classifier (Phase 10) trains on these entries";
the format exists in `packages/helios_parsing/evaluation.py:20-32` ("Promo entries
(Amendment 5 …)"). ROADMAP cites only Amendment 3's row mark.

- Replace `mark promo rows, and the harness reports promo rows stored as prices. Until the`
- With `mark promo rows and can list each promotion as its own entry ([ADR-0013 Amendment 5](./docs/adr/0013-phase5-menu-pipeline.md#amendment-5-2026-09-29-promo-label-grain)), and the harness reports promo rows stored as prices. Until the`
- Replace `trained and evaluated on the `promo` marks that Phase 5's gold labels carry.`
- With `trained and evaluated on the promo entries ([ADR-0013 Amendment 5](./docs/adr/0013-phase5-menu-pipeline.md#amendment-5-2026-09-29-promo-label-grain)) and `promo` row marks that Phase 5's gold labels carry.`

## B findings

### B-01 · README.md:470 · B · `docs/reviews/` description

The trackers were retired (README:298, `docs/HISTORY.md`); the directory now holds
review and evaluation records plus migration SQL.

- Replace `  reviews/              review trackers and migration SQL artifacts`
- With `  reviews/              review and evaluation records, migration SQL artifacts`

## C findings (owner)

### C-01 · CLAUDE.md "Stop and ask" + `.github/CODEOWNERS` · C · discovery ORM models outside the guarded paths

`apps/discovery/models.py:22, 51` defines ORM tables `DiscoveryReleaseCompletion` and
`DiscoveryLifecycleState` on `Base`, registered in
`packages/helios_core/db/model_registry.py:8`. CLAUDE.md's stop-and-ask list names
`packages/helios_core/**/models.py`, `…/models/**` and legacy `packages/**/db/models/**`;
CODEOWNERS covers `/packages/helios_core/**/models.py` only. Question: should both name
`apps/**/models.py` (or this file)? CLAUDE.md and CODEOWNERS are the owner's to change.

### C-02 · docs/adr/0010-website-and-menu-url-resolution.md · C · no pointer to ADR-0015

ADR-0015 replaces ADR-0010 Amendment 3's own-site verifier with the ADR-0013 classifier
(`0015:31-32`, `0015:125`, Amendment 1); ADR-0010 has no mention of ADR-0015 (`grep 0015` empty).
ADR-0011 set the precedent of a short dated pointer section in each ADR it amends
(`0004:437`, `0009:327`, `0010:370`). Adding one to an accepted ADR is new text, so it
waits for the owner. Question: add an "Amendment — ADR-0015" pointer to ADR-0010?

### C-03 · docs/adr/0013-phase5-menu-pipeline.md:660-662 · C · Amendment 5 says nothing is built

Amendment 5: "Nothing is built by this amendment … the promo-entry label format is added
when the first set is labelled with it." The format is now built
(`packages/helios_parsing/evaluation.py:20-32`; README:101 "promo entries"). True when
written; amendment content is not edited here. Question: record a dated note (or leave
as historical)?

### Owner decisions (2026-10-12)

- **C-01: apply.** CLAUDE.md's stop-and-ask list and `.github/CODEOWNERS` name
  `apps/discovery/models.py`, the only ORM module outside the guarded globs (a
  `grep '(Base)'` over `apps/` and `packages/`). Named exactly rather than as
  `apps/**/models.py`, which would also catch `apps/menu_pipeline/models.py` (the
  model-file downloader, no ORM). CLAUDE.md also covers "any other module that
  defines ORM models on `Base`".
- **C-02: apply.** ADR-0010 gains an "Amendment — ADR-0015" pointer section, in the
  form of its existing ADR-0011 one; facts from ADR-0015 Amendment 1 (`0015:116-163`)
  and `apps/discovery/url_pipeline.py:101` (`REVERIFY_WINDOW = timedelta(days=90)`).
- **C-03: leave as is.** Amendment 5's text stays as the historical record.

## Checked, not drift

- `python -m apps.menu_pipeline.label_courses` (ADR-0016:144): an explicitly "working
  name" for the unbuilt slice-1b CLI; README:193-196 says slice 1b waits.
- `infra/llama/Dockerfile` (ADR-0013:172, 682; `2026-09-29-llama-server-pi-check.md:12`):
  the conditional fallback if the upstream image fails the Pi check.
- `identity/commands.py` 478 (ADR-0015:74): `unassign_source_record` is at
  `packages/helios_core/identity/commands.py:478`.
- README:203 "Phase 5 gate: passed 2026-09-28": the last gate PR, #45 (`ddb5579`), merged
  2026-09-28.
- README:264-266 "slice-5 version, 2026-10-03" vs the record dated 2026-09-30: the
  record's session spans 2026-09-30 to 2026-10-03.
- `DEPLOYED_COMMIT` (README:425), `reviewed.json` (README:245): a Pi deploy-dir file and a
  documented removal (`docs/HISTORY.md`).
- V1 port-hint paths in ROADMAP (26): all exist on `V1-Graveyard`.
- ADR-0008 Amendment 2 settles in ADR-0004's favour (no back-link needed); ADR-0015 only
  mentions ADR-0014.
- ADR-0007 Amendment 1's promised own-site scoping amendment to ADR-0013 is unwritten
  and listed as pending at ROADMAP:690: consistent.
- `docs/reviews/sql/` and `docs/reviews/templates/` are referenced as directories
  (ADR-0005:242, ADR-0011:335, ADR-0016:442) and linked from
  `docs/course-labelling-guide.md:163`; all 13 dated review records are linked from
  README/ROADMAP and, except the classifier gap audit (README:171, ROADMAP:596), from an
  ADR amendment.
- GitHub links pinned to old SHAs for removed review files: intentional (HISTORY.md).
- README index titles use ":" where some ADR H1s use "—": punctuation only, left.
- CLAUDE.md verification/CI text matches `makefile` targets and `.github/workflows/ci.yml`
  job names; `docs/spikes/`: links resolve, nothing to flag.
- Every §8/tuning number, seed (20261010, 20261012), excluded-venue count (162) and
  laptop-pass count (9,996 / 8,085 / 1,635 / 894 / 1,632) in README/ROADMAP matches its
  record.
