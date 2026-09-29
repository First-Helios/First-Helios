# Remediation checklist — 2026-09-22 full codebase review

Companion to the [full codebase review](./2026-09-22-full-codebase-review.md).
Every finding (R01–R117) appears below, in a work session or in the accept/defer
list. Two are deliberately split: R31 (Gold tests in S7, selector tests in S11) and
R97 (accepted in D9; its misleading test comment is fixed in S16). Finding details (file:line, failure scenario) live in the review;
this file is the tracker and the plan.

## How this works

1. **You answer a decision group** (Part 1). Each group unlocks one or two sessions.
   You don't need to answer everything first — answer D1, hand off S1, answer D2
   while S1 runs, and so on. If you agree with every ⭐, tick them and move on.
2. **You start a fresh agent session** and paste that session's one-line hand-off
   prompt. Each session is sized for one 5-hour token window.
3. **The agent does the session**: follows its *Recommended approach*, writes tests
   first, fixes, runs strict CI, opens a PR, ticks the boxes here, and logs the
   result in the [session log](#session-log).
4. **You review and merge the PR.** Sessions marked ⚠ touch a CLAUDE.md
   stop-and-ask path; the agent stops at a draft PR and waits for you.
5. If a session runs out of budget, the agent commits what it has to the branch,
   writes resume notes in the session log, and the next session picks up there.

Legend: ⭐ recommended answer · ⚠ needs your review before merge ·
🚦 gate — don't pass until the listed sessions are merged.

## Progress at a glance

| Order | Session | Needs | Size | Status |
|---|---|---|---|---|
| 0 | You: answer D1–D9 (group by group is fine) | — | ~1 h of your time | [ ] |
| 1 | S1 Guardrails (DB target, CI gates, CLAUDE.md) ⚠ | D1 | M | [X] #23 |
| 2 | S2 Crawler etiquette ⚠ (protego) | D2 | M | [X] #24 |
| 3 | S3 URL pipeline logic | D3 | M | [X] #25 |
| 4 | S4 Menu-URL quality | D3 | S | [X] #26 |
| 5 | S5 Evidence ADR (draft, then stop) ⚠ | D4 | S | [X] #27 merged; ADR-0011 accepted 2026-09-27 |
| 6 | S6 Evidence implementation ⚠ | D4 + S5 accepted | M | [X] #42 merged; Pi rebuilt 2026-09-28; precision review found errors; gate closed |
| 6b | S6b Platform menu URLs alongside site menus | S6 merged | S | [X] #46 |
| 6c | S6c Location overrides + correction plan (implements ADR-0014) ⚠ | ADR-0014 accepted | M | [X] #50 merged (`e61486c`) |
| 6e | S6e Corrections applier (merges/retirements from a reviewed file; proposed by S6c) ⚠ | S6c merged | S | [ ] |
| 6d | S6d Menu-URL re-verification (implements ADR-0015; part 2 = `classifier-v1` ⚠) | ADR-0015 accepted | M | [ ] part 1 #51 (ADR-0015 accepted 2026-09-29); part 2 #52 draft ⚠ (stacked on #51) |
| 6f | S6f Page rendering: headed Chromium under Xvfb for platform/JS-only pages (ADR-0013 Amendment 1) ⚠ | S6d part 2 merged | M | [ ] |
| 🚦 | **Pi gate 1a — Phase 4 location quality:** correction plan + location overrides (ADR-0014) + passing fresh-sample re-audit. Does **not** gate `resolve_urls` | G.a | | [ ] 2026-09-28 adjudication: fails both bars (4 wrong geocodes, 6 duplicate venues / 100) |
| 🚦 | **Pi gate 1b — URL-resolution readiness:** gates the first Pi `resolve_urls` run; ADR-0015 re-verification with `classifier-v1` as verifier, platform rendering (S6d, S6f) | G.a | | [ ] |
| 7 | S7 Gold refresh fix | D5 | M | [X] #28 |
| 8 | S8 Identity lock order + guard tests | D6 | M | [X] #30 |
| 9 | S9 API polish | D7 | M | [X] #32 |
| 10 | S10 Test hardening sweep | — | S | [X] #31 |
| 11 | S11 Menu selector semantics ⚠ | D5 | M | [X] #33 |
| 12 | S12 Fingerprint fix + venue-lifecycle ADR draft ⚠ | D6 | M | [X] #34 merged; ADR-0012 accepted 2026-09-27 |
| 13 | S13 Venue-lifecycle implementation ⚠ | S12 ADR accepted | M | [X] #45 merged |
| 🚦 | **Phase 5 gate:** after S7/S11/S12/S13 merge AND lifecycle acceptance tests pass | | | [X] 2026-09-28: #28/#33/#34/#45 merged; main CI green (strict DB, run 36508316467). Next: proposed ADR-0013 before any Phase 5 code (G.b) |
| 13b | S13b Phase 5 pipeline ADR-0013 draft (ask the owner spike Q2–Q9 first) ⚠ | Phase 5 gate | S | [X] #48 draft (ADR-0013 Proposed; stop for review) |
| 14 | S14 Schema tightening migration ⚠ | D8 | M | [X] #35 merged |
| 15 | S15 Infra and tooling cleanup ⚠ | D8 | S | [X] #40, #41 merged |
| 16 | S16 Docs drift sweep | D6.5 | M | [X] #49 draft (docs consolidation; CLAUDE.md edits for owner review) |
| 17 | S17 Close-out | all | S | [ ] |

S15 and S16 have no dependencies; slot them in whenever you're waiting on a review.

### Overall recommendations

- **Do S1 first even though it isn't the most severe.** Every later session is run by
  an agent; S1 removes the default that points at the legacy archive and adds the
  `alembic check` gate before any session touches models or migrations.
- **Don't run `resolve_urls` on the Pi until Pi gate 1b.** Bronze rows can't be
  edited, so every run before S2–S6 writes permanent bad data (duplicate website
  versions, endpoint-less evidence, wrong menu URLs). Since 2026-09-28 the gate is
  split: 1b (menu-URL precision) gates `resolve_urls`; 1a (location quality) gates
  Phase 4 acceptance, not URL resolution.
- **Keep at most 2–3 PRs open.** Your review time is the bottleneck, not the agents.
- **Merge in table order unless a session says otherwise.** Later sessions assume
  earlier fixes (e.g. S4 reads the robots `Sitemap:` lines S2 collects).
- **When a ⚠ session stops, review the design, not every line.** The PR lists the
  R-IDs it closes and the tests that prove each one.

---

## Part 1 — Your decisions

Tick one box per question (put an `x` in it). ⭐ is my recommendation; the *Why* line
explains it. When a group is done, its sessions are ready to hand off.

### D1 — Guardrails → unlocks S1

- **1.1 Default database URL** (today it points at the legacy archive's address)
  - [X] ⭐ Remove the default; commands fail loudly when `DATABASE_URL` is unset
  - [ ] Keep a default but refuse `localhost:5432/helios`
  - *Why:* an unset variable should stop, not silently hit the archive. Compose
    already passes `DATABASE_URL` explicitly, so nothing else breaks.
- **1.2 `apps/api/seed.py`** (fake venues; discovery replaced it)
  - [X] ⭐ Delete it
  - [ ] Keep it, add a test-DB guard and make it idempotent
  - *Why:* discovery seeds 9,996 real venues; the fake seed now only creates
    duplicates that discovery can't dedupe.
- **1.3 CI changes** ⚠ (CI is your only merge gate)
  - [X] ⭐ Approve all: `alembic check` step, read-only token permissions, job
    timeouts, pinned uv, SHA-pinned actions, cancel-in-progress only for PRs,
    large-file hook enforced, PR-title Conventional Commits check
  - [ ] Approve only: ______
  - *Why:* `alembic check` is the one missing gate on your most expensive paths;
    the rest is cheap hardening that makes CI results reproducible.
- **1.4 Add `pytest-timeout` (dev dependency) so hung tests fail instead of running 6 h**
  - [X] ⭐ Yes  - [ ] No
  - *Why:* turns a silent 6-hour hang into a one-line failure.
- **1.5 Coverage**
  - [X] ⭐ Exclude `test/` from coverage and fail CI below 88% (real number today: 91%)
  - [ ] Leave as is
  - *Why:* 96% overstates reality; a threshold stops silent erosion.
- **1.6 CLAUDE.md fixes** (drop the stale "Venue stub" exemption; stop claiming
  `make ci` equals CI)
  - [X] ⭐ Agent drafts, I approve in the PR
  - [ ] I'll edit it myself
  - *Why:* agents follow CLAUDE.md literally; a stale exemption is a safety bug.
- **1.7 CODEOWNERS**: add `db/base.py`, `db/model_registry.py`, `alembic/env.py`,
  `.github/workflows/`, `infra/`; drop the dead `db/models/` line
  - [X] ⭐ Yes  - [ ] No
  - *Why:* those files control schema autogenerate and the merge gate.

### D2 — Crawler → unloks S2

    For the crawler we may want to reconsider how we do this. With the potental of including a JEV classifier model to help determine pages of interest

- **2.1 robots.txt rules**
  - [ ] ⭐ Hand-write an RFC 9309 matcher (stdlib, no new dependency)
  - [X] Add the `protego` library ⚠ (new runtime dependency)
  - [ ] User idea: we need to have a discussion on the rules
  - *Discussed 2026-09-23 (S2):* robots.txt answers "**may** we fetch this URL"
    (the site owner decides) and stays independent of any page-of-interest
    classifier, which answers "is it **worth** fetching / is it a menu" (we
    decide) and only chooses among robots-allowed URLs. Robots parsing is a
    solved problem, so use the known library (`protego`, Scrapy's parser)
    rather than hand-rolling it.
  - *Follow-up (Phase 5, no code now):* classifier for pages of interest; its
    own ADR; plugs in at `ordered_menu_candidates` (ranking) and the page check
    in `discover_menu_url`; never overrides robots.
  - *Follow-up (needs its own ADR first):* owner asked about an option to
    ignore robots for sites with no other data source. Not built: it reverses
    ADR-0010 §3. First measure how many sites robots actually blocks us from on
    a Pi run, then decide (e.g. a hand-approved site list, not a global switch).
  - *Why:* the matcher is ~60 lines plus tests; no dependency review, no image growth.
- **2.2 robots.txt can't be fetched (5xx, timeout)**
  - [X] ⭐ Skip that site this run
  - [ ] Crawl anyway (current behaviour)
  - *Why:* RFC 9309 says to assume "disallow"; skipping one month costs little.
- **2.3 Redirects**
  - [X] ⭐ Follow only within the same site (host ± `www.`), re-check robots on each
    hop, http/https only, block private/loopback addresses
  - [ ] Never follow redirects
  - *Why:* same-site redirects cover http→https and `www.`; cross-host redirects are
    where robots bypass and exposure of the Pi's LAN happen.
- **2.4 Max page size**
  - [ ] ⭐ 2 MB  - [X] Other: 3 MB
  - *Why:* menu pages are small; this caps memory on the Pi.
- **2.5 Cache lifetime**
  - [X] ⭐ robots.txt 7 days, failed fetches 7 days, good pages kept for the run
  - [ ] Other: _____
  - *Why:* month-old robots rules and permanent "failed" results are both wrong.

### D3 — URL pipeline → unlocks S3, S4

- **3.1 Records a human (or the resolver) marked `needs_review`**
  - [X] ⭐ Never auto-assign them; count and report them
  - *Why:* `needs_review` means someone asked for a decision; automation must not
    overrule it.
- **3.2 Registry entry vs an already-saved menu URL**
  - [X] ⭐ Registry always wins: save a new version whenever it differs
  - [ ] Only when run with an `--apply-registry` flag
  - *Why:* the registry exists to correct automation.
- **3.3 Transaction size for long runs**
  - [X] ⭐ Commit every 100 venues  - [ ] Other: ______
  - *Why:* bounds any loss to 100 venues and keeps locks short.
- **3.4 What counts as a real menu page**
  - [ ] ⭐ Reject homepage/self/`#` links; require a menu word in the page title,
    heading, or URL path; detect catch-all sites
  - [ ] Keep "any 200 HTML page"
  - [X] We should consider using a JEV classifier for this decicision processes, or feeding page conext to the classifier, if this isnt a rational place to do this the let me know and we can address this issue again.
  - *Why:* catches every false positive the review found with cheap checks and no
    HTML-parsing dependency.
  - *S4 (2026-09-23), owner confirmed:* the cheap checks (⭐) ship in S4 now as the
    pre-filter; a page classifier is a new dependency, so it gets its own ADR in
    Phase 5 (already recorded in ADR-0010 as "ranks/verifies candidates, never
    overrides robots"). S4's checks stay as the classifier's input filter.
- **3.5 Platform sites (Toast, Square, Facebook, Instagram, DoorDash, …)**
  - [X] ⭐ Keep the full website path; don't probe `/menu` at the platform's root --  Note: We do want to collect this data if possible as some places dont have a menu listed anywhere but on outside platforms. We may need to eventually have a method to reconsile this information, but it should be collected even if it provides duplicates, with a prefrence menus and pricing found on the main website.
  - *Why:* root paths on a shared platform belong to the platform, not the venue.
  - *S4 (2026-09-23), owner confirmed:* platform as fallback, one URL per venue. A
    website on a platform host keeps its full path and is itself the menu URL
    (signal `platform`, no root probes; a platform root is never a venue page). For
    an own-site venue, a same-site menu wins; if none verifies, a homepage link
    to a venue page on an *ordering* platform (Toast, Square, DoorDash, …) is
    accepted (signal `platform`) — social links (Facebook, Instagram) are not. Keeping both the site's and the platform's menu URL per
    venue needs a record-contract change — deferred to S5/S6 (D4).
- **3.6 Menu-URL grain** (ADR-0010 says "one per chain"; code saves one per venue)
  - [X] ⭐ Keep per-venue; fix the ADR wording
  - [ ] One per chain (needs redesign)
  - *Why:* each Overture POI mints its own Organization today; one-per-chain needs
    the merge work first.
- **3.7 Saved menu URL when the venue's website changes** (asked in S3, 2026-09-23)
  - [X] ⭐ Re-discover; replace only when discovery succeeds, else keep the old one
  - [ ] Never re-discover (registry only)
  - *Owner note:* keep the old data in a "graveyard" and only replace it when
    re-discovery succeeds. *S3:* Bronze already is that graveyard: each new menu
    URL is appended as a new immutable version and the old versions are never
    deleted, so no new table was added (that would need a migration + ADR; raise
    it in S5/S6 if a separate table is still wanted).
- **3.8 Website record in `needs_review`: crawl it for a menu anyway?** (asked in S3)
  - [X] ⭐ Skip the venue (count it; no write, no crawl)
  - [ ] Still crawl for a menu
- **3.9 What `--limit N` counts** (asked in S3)
  - [X] ⭐ Only venues that need work (a write or a crawl)
  - [ ] Add an `--after-id` cursor
  - *Caveat:* venues where no menu was found are re-crawled each run until S6
    records failed fetches (D4.2).

### D4 — Evidence and provenance → unlocks S5, S6 (answer before the next Pi run)

- **4.1 Source URL recording**
  - [X] ⭐ Always record where data came from (Source Endpoint); make "match
    identity by this URL" a separate opt-in field
  - *Why:* fixes R06 at the root without bringing back the location-collapse hazard
    ADR-0009 avoided.
- **4.2 Record failed fetches in Bronze with an outcome and reason**
  - [X] ⭐ Yes ⚠ (probably a small migration)  - [ ] No
  - *Why:* ADR-0004 already requires it, and failure history stops re-crawling dead sites.
- **4.3 The ~10k existing Pi rows without an endpoint** (Bronze can't be edited)
  - [ ] ⭐ Leave them; document them as pre-ADR history
  - [X] We are in early development, if something is done wrong and the data is malformed, or not needed/is in the way of a fix and preserving data adds complexiry we can delete it. especally old legacy data that can add confusion to the system as it cannot be traced. In fact once we are at the pont where we are at produciton, we should do a full data purge and attempt to rebuild everything from scratch.
  - *Why:* they're immutable anyway; documenting avoids later confusion.
  - *S5 (2026-09-23):* handled as a **database rebuild**, not row deletion (Bronze
    triggers block `DELETE`, Identity blocks `TRUNCATE`): S6's migration refuses to
    run on pre-ADR rows, and the owner rebuilds the Pi DB (drop volume, `compose up`,
    re-run discovery). Venues get new Subject ids; re-run the precision audit. See
    ADR-0011 §8.
- **4.4 Evidence locators become real field paths (e.g. `$.websites[0]`)**
  - [X] ⭐ Yes  - [ ] No
  - *Why:* evidence becomes checkable without reading pipeline code.
- **4.5 Add a server "ingested at" timestamp to Bronze** (R101)
  - [X] ⭐ Yes, in the same migration as 4.2  - [ ] No
  - *Why:* the only way to know when a row arrived; free if migrating anyway.
- **4.6 Platform menu URLs alongside the site's own menu** (D3.5 carry-over; asked in
  S5, answer when accepting ADR-0011). ADR-0011 §7: the contract allows several menu
  URLs per venue, one record per (venue, menu source), keys `<gers>` and
  `<gers>|<platform host>`, site preferred on read.
  - [X] ⭐ S6 adopts only the key rule; collecting platform links even when a site
    menu verifies is a follow-up session S6b (not Pi-gating)
  - [ ] Do both in S6
  - *Why:* keeps S6's review on the contract and migration (the expensive-to-reverse
    part); a Pi run before S6b only collects fewer platform menus, and a later run adds them.
- **4.7 Don't re-crawl a site whose last menu-discovery attempt failed or was skipped
  for …** (asked in S5; ADR-0011 §4)
  - [X] ⭐ 20 days  - [ ] Other: ____
  - *Why:* a chunked run spread over days never re-crawls a dead site, and the next
    monthly run still retries it.

### D5 — Gold and menu selection → unlocks S7, S11

- **5.1 Reads (selector, Gold) use a separate read-only eligibility check** — no
  locks, never aborts the transaction
  - [X] ⭐ Yes
  - *Why:* root cause of R01 and R21; reads shouldn't be able to break or block writes.
- **5.2 Bounded Gold refresh replaces all rows for each requested scope**
  - [X] ⭐ Yes
  - *Why:* matches what "refresh this venue" means.
- **5.3 History-mode requests passed to the Gold refresh**
  - [X] ⭐ Reject them
  - *Why:* the current table should hold current answers only.
- **5.4 Menus in Phase 5 v1**
  - [X] ⭐ Self-contained location snapshots only; chain inheritance stays off
    until real chain data needs it
  - [ ] Use inheritance from day one
  - *Why:* inheritance is the least-tested, most complex code; the schema already
    supports self-contained snapshots, so this costs no migration.
- **5.5 Selector fixes R03, R22–R24 are ADR-0005 conformance fixes, not new rules**
  - [X] ⭐ Agree  - [ ] Treat as ADR change (write an amendment first)
  - *Why:* ADR-0005 already states these rules; the code misses them.

### D6 — Identity → unlocks S8, S12, S13, S16

- **6.1 Lock order between identity write paths**
  - [X] ⭐ Agent picks one global order, documents it, proves it with tests
  - *Why:* one order everywhere is the standard deadlock fix; the repro in the
    review appendix becomes the regression test.
- **6.2 Name fingerprint**
  - [X] ⭐ Keep non-English letters (strip accents only)
  - [ ]  No, this wastes tokens, in dev mode its better to not need one off conversion when a rerun fix will be sufficent. if i misunderstood this push back ⭐ Recompute stored fingerprints on the Pi (agent writes the script, you run it)
  - [ ] ⭐ Don't auto-merge existing venues after the recompute
  - *Answered 2026-09-24 (S12, confirmed with owner):* **no recompute script.** The
    ADR-0011 §8 / D4.3 Pi purge + rebuild re-mints every Organization with the new
    fingerprint. An *incremental* rerun would not: known POIs resolve by GERS id before
    a fingerprint is computed. So don't run incremental discovery on the current Pi DB
    before the rebuild. The auto-merge item is N/A (nothing is recomputed).
  - *Why:* today different bilingual names merge; recomputing keeps old and new
    fingerprints comparable; auto-merging is irreversible.
- **6.3 Venue lifecycle** (re-seen venues never update; closed venues never retire)
  - [X] ⭐ Agent drafts an ADR with options (update changed venues; close venues
    missing from 2 monthly releases), then stops for your review
  - *Why:* decide the policy before monthly runs pile up stale data.
- **6.4 Establishment eligibility** (none can take menu writes today)
  - [X] ⭐ Auto-promote when its Place and Organization are both eligible
  - *Why:* without it, no location menu can ever be written.
- **6.5 Can the API read Identity models directly?** (ADR-0004 says yes, ADR-0008 says no)
  - [X] ⭐ Yes — amend ADR-0008 §9
  - [ ] No — add an Identity read contract and switch the API to it
  - *Why:* the code already does it, ADR-0004 allows it, and a read contract adds a
    layer with no current payoff.

### D7 — API → unlocks S9

- **7.1 405 Method Not Allowed** (reports `internal_error` today)
  - [X] ⭐ Add code `method_not_allowed`; other 4xx become `validation_error`
  - *Why:* clients switch on `code`; their own mistake shouldn't look like a server fault.
- **7.2 `/readyz` failure uses the standard error body**  - [X] ⭐ Yes
  - *Why:* one error shape everywhere, with a `trace_id` to find the log line.
- **7.3 Reject `*` in the CORS setting**  - [X] ⭐ Yes
  - *Why:* ADR-0008 says never a wildcard; enforce it.
- **7.4 DB timeouts**  - [X] ⭐ Connect 5 s, pool wait 10 s, pre-ping on
  - *Why:* fail fast instead of tying up workers for 130 s.
- **7.5 Client-supplied `X-Request-ID`**
  - [X] ⭐ Accept only ≤ 64 safe characters, otherwise generate one
  - *Why:* keeps correlation, blocks log spoofing and giant headers.

### D8 — Schema and infra approvals → unlocks S14, S15 ⚠

- **8.1 One schema-tightening migration** (R53, R54, R56, R60, R63, R69), reviewed as its own PR
  - [X] ⭐ Approve  - [ ] Skip for now
  - *Why:* all low-risk constraints; batching them means one migration review, not six.
- **8.2 Infra PR**: `.dockerignore`, compose env handling, `var/` volume, restart
  policy, project name, image digests
  - [X] ⭐ Approve  - [ ] Skip for now
  - *Why:* stops the Pi losing caches every run and lets the stack survive a reboot.
- **8.3 `pyproject.toml`**: rename to `helios`, declare `pydantic`/`starlette`, drop
  unused `pytest-asyncio`
  - [X] ⭐ Approve  - [ ] Skip for now
  - *Why:* cosmetic, but makes the dependency list honest.

### D9 — Accept or defer (no session needed; confirm with a tick)

*Why accept these:* each is either harmless for public read-only data, already
covered by another guard, or documentation of a deliberate trade-off.

**Accept — no code change:**
- [ ] R97 Cursor is forgeable (data is public; S16 fixes the misleading test comment)
- [ ] R100 OpenAPI snapshot test is exact-match, not breaking-change
- [ ] R102 Payload hash treats `Decimal("1.5")` and `"1.5"` the same
- [ ] R103 Early downgrades destroy history without saying so
- [ ] R104 Legacy scaffold downgrade quirks
- [ ] R107 `readiness` column has no DB guard (admission re-checks it)
- [ ] R109 Gold determinism depends on the supplied time E
- [ ] R117 Secret scan found nothing

**Defer — revisit when the trigger happens:**
- [ ] R66 Menu replay vs revision key mismatch → *if duplicate Bronze versions ever appear*
- [ ] R71 Gold unique index could exceed size limit → *when Phase 5 produces deep menu paths*
- [ ] R108 Observation-time rank can't decide; Unsectioned items unselectable → *Phase 5 extraction design*
- [ ] R110 Overture category list and pinned release → *next Overture release run*
- [ ] R111 No review queue for ambiguous venues → *when a review UI is planned*
- [ ] R116 Image healthcheck / arm64 CI build → *Phase 8 deploy work*

### G — Gate decisions (owner, 2026-09-28)

Recorded verbatim from the owner's session prompt:

- **(a) Pi gate:** "I defer to the agent to address solving this conflict." The owner
  delegates adjudication of [docs/reviews/2026-09-28-precision-review.md](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-28-precision-review.md) and the gate
  criteria to the agent.
- **(b) Phase 5:** Phase 5 menu processing uses the spike's pipeline
  (docs/spikes/menu-model/README.md: page classifier + LLM extraction + validator),
  replacing ROADMAP's Scrapy-vs-Crawlee framing.

*Outcome (agent, 2026-09-28):* (a) precision review adjudicated and the Pi gate split
into 1a/1b with the criteria under S6b below; ADR-0014 and ADR-0015 drafted for owner
review. (b) Phase 5 gate ticked; Phase 5 code waits for a proposed ADR-0013 (see S13).

---

## Part 2 — Work sessions

### Session rules (agents: read this first)

1. Read `CLAUDE.md`, this file's answered decisions for your session, and the rows
   for your R-IDs in the [review](./2026-09-22-full-codebase-review.md) (§5 table,
   plus the appendix for reproductions).
2. Check the [session log](#session-log) for resume notes. Branch from latest `main`
   as `fix/<session-slug>` (or continue the logged branch).
3. For each finding: write a test that fails because of it (where testable), then
   fix it, then tick its box here. Follow the session's *Recommended approach*
   unless the code proves it wrong — if so, say why in the PR. Pick up nothing
   outside your session's list.
4. **Safety.** Never connect to `localhost:5432`, never read `.env`, no live network
   in tests, no SSH to the Pi. Scripts meant for the Pi are written, not run.
5. **Verify on a fresh disposable DB every time** (a reused DB fails, see R11):
   ```bash
   docker run -d --name helios-fix-db -e POSTGRES_USER=helios -e POSTGRES_PASSWORD=helios \
     -e POSTGRES_DB=helios_test -p 127.0.0.1:55432:5432 imresamu/postgis:16-3.4
   # wait for pg_isready, then:
   export DATABASE_URL=postgresql+psycopg://helios:helios@127.0.0.1:55432/helios_test
   HELIOS_STRICT_DB_TESTS=1 make ci && uv run alembic check
   docker rm -f helios-fix-db
   ```
6. Open a PR titled `fix(<area>): <summary> (S<n>)` that lists the R-IDs it closes.
   ⚠ sessions open a **draft** PR and stop for the owner. Never merge.
7. Before ending: tick the boxes, add a row to the session log (date, branch, PR,
   status, resume notes if unfinished). If the budget runs low, commit WIP to the
   branch and write resume notes before stopping.

---

### S1 — Guardrails ⚠ · size M · needs D1
Hand-off prompt: `Do session S1 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/guardrails` · Stops for review: CI workflow, CLAUDE.md, dev dependency.

- [X] R09 Default database URL points at the legacy archive; seed CLI unguarded (per D1.1, D1.2)
- [X] R10 CI never runs `alembic check`; turn on `compare_server_default`
- [X] R39 CLAUDE.md "current `Venue` stub" exemption points at a dropped table
- [X] R40 CLAUDE.md/CONTRIBUTING say `make ci` equals CI
- [X] R80 Concurrency tests can hang; no test or job timeouts (per D1.4)
- [X] R87 uv version not pinned in CI
- [X] R88 `make ci` lockfile check can't fail locally
- [X] R89 CI: no permissions block, tag-pinned actions, no timeouts
- [X] R94 Large-file hook and commit-message check don't run in CI
- [X] R95 CODEOWNERS dead path and missing key paths (per D1.7)
- [X] R112 Coverage counts test files; no threshold (per D1.5)
- [X] R115 CI cancels in-progress runs on `main`

**Recommended approach**
- Do the safety part first: make `Settings.database_url` required (no default) with
  a clear error; update README setup; delete `apps/api/seed.py` and its test (or
  guard it per D1.2).
- In `alembic/env.py` set `compare_server_default=True` and confirm `alembic check`
  is still clean on a fresh DB.
- `ci.yml`: add `uv run alembic check` after pytest in the Tests job;
  `permissions: contents: read`; `timeout-minutes` per job; `setup-uv` with a pinned
  `version:` that matches the Dockerfile; SHA-pin actions with a version comment;
  `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`.
- `pyproject.toml`: add `pytest-timeout` with a default timeout; coverage config
  `omit = ["test/*"]`, `fail_under = 88`. `makefile`: run `uv lock --check` first or
  use `uv run --locked`.
- `.pre-commit-config.yaml`: `--enforce-all` on the large-file hook; add a PR-title
  check job (or document that squash titles must be Conventional Commits).
- Keep CLAUDE.md edits minimal: delete the Venue parenthetical; say `make ci` is the
  local subset and strict DB acceptance needs the disposable-DB command.

### S2 — Crawler etiquette · size M · needs D2
Hand-off prompt: `Do session S2 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/crawler-etiquette` · Stops for review only if D2.1 = `protego` (it is: draft PR).

- [X] R05 robots.txt rules misread (first match, no wildcards) → disallowed pages fetched
- [X] R13 robots.txt fetch failure treated as "crawl everything"
- [X] R14 Redirects followed anywhere (other hosts, private IPs), skipping robots and throttle
- [X] R35 No tests for rate limiting, redirects, robots errors
- [X] R74 Homepage links resolved against the pre-redirect URL; `<base>` ignored
- [X] R79 Web cache: no size cap, non-atomic writes, failures and robots cached forever

**Recommended approach**
- New small module `apps/discovery/robots.py`: group rules by user-agent, longest
  match wins (Allow wins ties), support `*` and `$`, expose `crawl_delay` and
  `sitemaps`. Replace `RobotFileParser` with it.
- robots fetch outcome: 2xx → parse; 4xx → allow all; 5xx/network → skip the site.
- Set `follow_redirects=False` and write a manual loop (max 5 hops): each hop must be
  http/https, same host ignoring `www.`, resolve to a public IP (reject
  private/loopback/link-local/reserved via `ipaddress`), pass robots, and go
  through the throttle. Return the final URL for link resolution.
- Stream responses and stop at 2 MB. Write cache files to a temp file then
  `os.replace`; store `fetched_at` and expire robots and failures after 7 days.
- Make the clock injectable (`monotonic`, `sleep`) so tests can prove throttling.
- Tests (MockTransport): wildcard and longest-match rules, robots 403 and 503,
  off-site and private-IP redirects, size cap, throttle intervals, `<base href>`.

### S3 — URL pipeline logic · size M · needs D3
Hand-off prompt: `Do session S3 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/url-pipeline`

- [X] R04 Overrides `needs_review` decisions; crashes on retired Organizations
- [X] R07 Registry can't replace a menu URL once one is saved (per D3.2)
- [X] R15 Discovery CLIs run as one giant transaction; one error loses the whole run (per D3.3)
- [X] R16 Every run re-saves every website → permanent duplicate Bronze rows
- [X] R32 `--limit` never advances past the first N venues
- [X] R57 "Latest" Overture version picked by id, not date
- [X] R72 Registry host not validated; missing registry file silently empty
- [X] R73 Duplicate processing of venues with two Overture records; ADR-0010 grain wording (per D3.6)

**Recommended approach**
- `_persist_and_assign`: branch on state — `resolved` → skip; `needs_review` → count
  and skip; `unresolved` → assign only if the Organization is current, else count
  `org_not_current` and skip. Add those counters to the report.
- Before persisting a website, compare with the latest saved payload; persist only
  when the website or origin changed.
- Move the registry `menu_url` check ahead of `_has_current_record`; if the registry
  value differs from the saved one, persist a new version (the record is already
  assigned, so no reassign is needed).
- Iterate Establishments once each (pick the latest Overture record by
  `observed_at`, then id). Page through ids and commit every 100 in the CLIs
  (`resolve_urls.py` and `__main__.py`); skip venues whose records are already
  current and unchanged so `--limit` makes progress.
- Registry: validate `host` as a bare hostname (no scheme, port, or path); if
  `--config` is given explicitly and the file is missing, fail.
- Update ADR-0010's "one per chain" wording per D3.6.

### S4 — Menu-URL quality · size S · needs D3
Hand-off prompt: `Do session S4 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/menu-url-quality`

- [X] R08 Homepage, `#` links, and catch-all sites saved as menu URLs (per D3.4)
- [X] R33 Platform sites probed at the root `/menu` (per D3.5)
- [X] R34 Menu word list too loose (`/menu-of-services`, `nav-menus.php`)
- [X] R75 Sitemap index files, robots `Sitemap:` lines, `.xml.gz` not handled
- [X] R76 Garbage website strings "fixed" into bogus URLs

**Recommended approach**
- Drop candidates that are `#`, empty, non-http, or resolve to the homepage.
- Catch-all detection: probe one random path per site; if it returns 200, don't
  trust well-known path probes on that site.
- Accept a page only if its URL path, `<title>`, or first heading contains a menu
  word, and its body hash differs from the homepage's.
- Platform host list (toasttab, square, clover, facebook, instagram, doordash,
  ubereats, grubhub, linktr.ee, …): keep the full website path; skip root probes.
- Lexicon: match whole tokens and add a blocklist (`wp-admin`, `services`, `safety`,
  `careers`, `policy`, …).
- Sitemaps: follow up to 5 index children, read robots `Sitemap:` lines (from S2),
  gunzip `.xml.gz`, reserve candidate slots for homepage anchors.
- `_coerce_website`: reject when the `https://` retry yields a host without a dot.

### S5 — Evidence ADR (draft, then stop) ⚠ · size S · needs D4
Hand-off prompt: `Do session S5 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `docs/adr-0011-evidence-endpoints` · Output: an ADR proposal; no code. Stops for your acceptance.

- [X] ADR-0011 drafted covering R06, R17, R58, R101 (per D4)

**Recommended approach**
- Title: "Provenance endpoints vs identity match keys". Record the D4 answers as
  the decision.
- Contract sketch: `BronzeObservation.source_url` (always recorded as the Source
  Endpoint) plus `identity_match_url` (opt-in; the only field Identity reads).
- What each namespace records: Overture → release URL + GERS id; website → the
  website URL; menu-URL → the page actually fetched, with the capture hashing the
  fetched bytes.
- Capture outcome + reason-code values; locator format (JSON path); the
  `ingested_at` column; the exact migration shape (if any) for review.
- State how the ~10k existing rows are treated and list the tests that will prove
  "return the original source URL on demand" for every namespace.

### S6 — Evidence implementation ⚠ · size M · needs D4 + S5 accepted
Hand-off prompt: `Do session S6 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/evidence-endpoints` · Stops for review: provenance contract; migration if D4.2/4.5 = yes.

- [X] R06 Discovery evidence doesn't record the source URL (endpoint)
- [X] R17 Failed fetches and skipped input not recorded in Bronze
- [X] R52 Source Record written before its URL is validated (no savepoint)
- [X] R55 Re-running a release with a differently spelled path duplicates rows
- [X] R58 Evidence locators aren't field paths
- [X] R101 No server "ingested at" timestamp

**Recommended approach**
- Implement exactly what ADR-0011 accepted; don't widen scope.
- Validate every URL before inserting anything, and wrap persistence in a
  savepoint (the Menu writer already does this).
- Record failed/skipped fetches as Captures; preserve rejected POIs as Bronze observations with outcome + reason code.
- Normalize the release path before using it in the exact-retry key.
- For any migration: hand-review the generated SQL and commit it under
  `docs/reviews/sql/` with a byte-compare test, as Steps 5 and 6 did.
- Test: for each namespace, walk Evidence → Version → Capture → Endpoint and get the
  original URL back.

### S6b — Platform menu URLs alongside site menus · size S · needs S6 merged (D4.6 = S6b)
Hand-off prompt: `Do session S6b from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/platform-menu-urls` · Not Pi-gating.

- [X] Collect ordering-platform menu URLs from the homepage even when an own-site menu
  verifies; persist each as `<gers>|<host>` (ADR-0011 §7)

**Recommended approach**
- `discover_menu_url` returns the own-site result plus verified platform results (one
  per host, capped by `MAX_PLATFORM_CANDIDATES`); social links and platform roots stay
  excluded (ADR-0010 Amendment 3).
- Test: a homepage with a site menu and a Toast link writes both records; a re-run
  writes nothing.

🚦 **Pi gate — split 2026-09-28 under owner decision G.a.** S2/S3/S4/S6 are merged and
the Pi was rebuilt 2026-09-28 ([S6 runbook](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-27-s6-pi-rebuild.md)). The agent
adjudicated the [precision review](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-28-precision-review.md) and verified the gate
conflict in code:

- URL records are keyed by GERS id (`<gers>`, `<gers>|<platform host>`), and no file in
  the URL path (`resolve_urls.py`, `url_pipeline.py`, `menu_url.py`, `web_client.py`,
  `registry.py`) reads a coordinate. Duplicates only add redundant per-POI records that
  stay true; bad coordinates change nothing the resolver writes. **Location precision
  does not gate `resolve_urls`.**
- The URL-data risk is menu-URL precision: the S4 verifier measured 0.605 venue-level
  precision (spike stage C); S6b platform pages are accepted on 200 + HTML + venue path
  with no content check (`web_client.py` 585-598); a resolved menu URL on an unchanged
  website is reused without any fetch (`url_pipeline.py` 704-711), so first-run errors
  never get re-checked. The Pi has no menu-URL records yet, so the first run matters.

**1a — Phase 4 location quality. Closed.** Gates Phase 4 "done" and anything that relies
on venue location or dedupe; does not gate `resolve_urls`. Opens when all hold:
- [X] Correction plan committed: every confirmed defect classified (source coordinate
  error, address error, duplicate incl. misplaced twins and chain location-label records,
  lifecycle/closed or renamed, non-venue), each mapped to its fix: an existing evented
  command with Evidence (merge, remap, retire) or a location override; a corpus-wide twin
  search, not only the co-location detector (and fix `audit.street_key` dropping 5-digit
  house numbers). S6c: [location correction plan](./2026-09-28-location-correction-plan.md).
- [X] [ADR-0014](../adr/0014-location-overrides.md) (location overrides) accepted and
  implemented, with tests for minting, dedupe, lifecycle projection (no false relocation)
  and rebuild. Without it the lifecycle pass turns a hand fix into a "relocation" at the bad
  point (`lifecycle.py` 287-298).
- [ ] Corrections applied on the Pi in an owner-authorized run (no raw SQL). Overrides
  apply via a discovery re-run; merges and retirements need S6e.
- [ ] Fresh-sample re-audit: new seed, 100 rows, every row hand-labeled under the
  precision review's criteria (geocode check + twin search), plus a regression check of
  the corrected cohort. Pass = 0 confirmed wrong geocodes (1/100 is not < 1%), at most 1
  sampled venue with a confirmed duplicate, and at most 5 unresolved rows per measure,
  with the worst case (unresolved counted as failures) reported beside it. Never drop rows
  or change the denominator.

**1b — URL-resolution readiness. Closed.** Gates the first Pi `resolve_urls` run.
Independent of 1a. Opens when all hold:
- [X] Owner decision on [ADR-0015](../adr/0015-menu-url-reverification.md): accepted
  2026-09-29 (option C with Amendment 1), verifier = the ADR-0013 page classifier from
  the first run. Implemented and merged with strict CI: part 1 (S6d, #51) [ ], part 2
  `classifier-v1` (S6d, #52) [ ], rendering (S6f) [ ].
- [X] A saved menu URL records its verifier version and is re-checked when the verifier
  changes (or its window expires); a URL the current verifier rejects is withdrawn to
  `needs_review`, never reused. (S6d part 1)
- [X] Platform pages pass a content check (not 200 + HTML + path alone). (S6d part 1;
  without rendering, platform pages in practice fail it, see S6f)
- [X] PR #46's multi-location chain question decided: automated address-match guard
  (S6d part 1; phone matching deferred, ADR-0015 Amendment 1 item 6).
- [ ] `classifier-v1` is the verifier (S6d part 2) and platform pages are rendered (S6f).
- [ ] Owner authorizes the run. After it: record website/menu-URL coverage (the last
  Phase 4 "done when" item) and a hand-checked precision sample of saved menu URLs.

S6b is not Pi-gating.

### S6c — Location overrides + correction plan ⚠ · size M · needs ADR-0014 accepted
Branch: `feat/location-overrides` · Opens nothing by itself: Pi gate 1a also needs the
owner-authorized Pi corrections and the fresh-sample re-audit.

Owner decisions at session start (2026-09-28): ADR-0014 **accepted, option A**; open
question 1 = **in-place correction** on first application (no relocation, stable ids);
open question 2 = **ship address overrides now**.

- [X] Implement accepted ADR-0014 (Bronze `location-override` namespace, one
  effective-location function for minting, dedupe and lifecycle; stale overrides disabled)
- [X] Correction plan committed (the gate 1a list above), with a corpus-wide twin search
  that finds misplaced twins and chain location-label records; fix `audit.street_key`
  dropping 5-digit house numbers
- [X] Pi correction and re-audit steps written as a runbook for the owner (not run)

### S6e — Corrections applier ⚠ · size S · needs S6c merged
Branch: `feat/identity-corrections` · Proposed by S6c: merges and retirements have
evented commands but no CLI, and gate 1a forbids raw SQL.

- [ ] A reviewed `config/identity_corrections.yaml` (merge clusters with a survivor,
  retirements; rationale + evidence URL each), keyed by GERS id so it survives a rebuild
- [ ] `python -m apps.discovery.corrections` applies it idempotently via
  `create_adjudication`, `remap_source_record`, `record_subject_change`; decide which
  merged-away parents (Organization, Place) retire
- [ ] Entries for the plan's §2 merges (6 sampled + 23 detector pairs) and, if the owner
  wants, §5 retirements
- [ ] Tests: merge, retire, re-run is a no-op, rebuild re-applies, a lifecycle pass leaves
  merged venues alone

### S6d — Menu-URL re-verification · size M · needs ADR-0015 accepted
Branch: `feat/menu-url-reverification` (part 1), `feat/page-classifier` (part 2 ⚠)

Owner decisions at session start (2026-09-29), recorded in ADR-0015 Amendment 1 and
ADR-0013 Amendment 1:

- ADR-0015 **accepted**, option C, amended: a passing re-check appends a same-payload
  Version; only a verdict on the page withdraws (network/5xx/robots keep the URL);
  withdrawal Evidence is a `rejected/menu_not_verified` observation.
- `REVERIFY_WINDOW` = **90 days**. Rule-withdrawn records **recover** automatically;
  human-disputed ones don't.
- Chain homepages: **automated** match of the venue's phone or address on the platform
  page (address built; phone needs Overture `phones`, deferred), no manual entries.
- Platform content check: **pull the ADR-0013 page classifier into S6d** as
  `classifier-v1` (ADR-0013 classifier parts accepted; the rest stays Proposed).
- Rendering: platform pages need a browser (probe: 0/37 readable static, 19/37 priced
  rendered; Toast needs headed Chromium). Owner: **headed Chromium under Xvfb, honest
  UA, robots obeyed**, as new session **S6f**. Split: 3 PRs (part 1, part 2, S6f).

- [X] Part 1: verifier version in the payload (`PageVerifier`, `s4-v1`), re-verify
  instead of reuse, withdraw to `needs_review` via `unassign_source_record`, rule-withdrawn
  recovery, platform content check, automated chain-homepage guard (`platform_ambiguous`)
- [X] Tests: saved URL from an older verifier is re-checked; a rejected URL is withdrawn,
  not reused; registry entries are never withdrawn; platform page without menu content is
  not saved; transient failures keep the URL; window; recovery; chain guard
- [X] Part 2 ⚠: `classifier-v1` (ADR-0013 slices 1 without `llama-server`, and 4):
  segmentation + price-token features, checked-in weights trained on the spike labels,
  `menu` extra (`fastembed`/`onnxruntime`), model manifest + checksum-refusing download,
  worker image target, `resolve_urls` uses it; a recorded evaluation (ADR-0013 §8):
  [classifier-v1 evaluation](./2026-09-29-classifier-v1-evaluation.md)

### S6f — Page rendering ⚠ · size M · needs S6d part 2 merged
Branch: `feat/page-render` · ADR-0013 Amendment 1 (render part of slice 6, for discovery).

- [ ] Render platform pages (static `403` or failing the classifier) and JS-only own-site
  candidates with headed Chromium under Xvfb in the worker image: Helios UA token,
  robots.txt, per-host rate limit, no stealth or challenge solving; still-`403`/challenge
  = skipped Capture
- [ ] Decide ADR-0013 open question 3 (robots for rendered sub-requests) with the owner
- [ ] Measure (ADR-0013 §4): render success and classifier quality on rendered platform
  pages (label the probe's pages in `var/spikes/menu-model/render-probe-2026-09-29/`),
  Pi time and peak RAM per render; enable for Pi runs only after it is recorded
- [ ] `classifier-v1` rejects every rendered Toast order page (0.004–0.28, threshold 0.508;
  Square/Clover/Grubhub pass): label rendered platform pages, train and evaluate a
  successor version (`classifier-v2`; the verifier bump re-checks saved URLs)
- [ ] One Toast link redirected to `toast.app` (not in `ORDERING_PLATFORM_HOSTS`): decide
  whether platform host lists grow (a generic list change, not a per-platform parser)

### S7 — Gold refresh fix · size M · needs D5
Hand-off prompt: `Do session S7 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/gold-refresh` · No stop-and-ask path, but changes accepted ADR-0006 behaviour: owner review.

- [X] R01 Full Gold refresh crashes after any identity correction (missing savepoint)
- [X] R02 Selector can show a retired venue's prices under its successor
- [X] R11 Tests pass only in file order; a rerun on the same DB fails
- [X] R19 Which head gets checked depends on database row order
- [X] R20 Bounded refresh leaves stale rows for scopes that closed (per D5.2)
- [X] R21 Reads take write locks (per D5.1)
- [X] R26 Import-boundary test doesn't check Gold
- [X] R31 (Gold half) Missing tests: retired/remapped/pending exclusion, stale-scope removal, org-scoped rows
- [X] R70 History-mode requests written into the "current" table (per D5.3)

**Recommended approach**
- Start with the regression test from the review appendix:
  `pytest test/test_menu_precedence.py test/test_gold_catalog.py` must pass on a
  fresh DB.
- Add a read-only scope check to the Identity contracts (a plain SELECT, no
  `FOR UPDATE`, no `RAISE`) that returns live/not-live per scope. Selection and
  enumeration use it; writers keep the existing guard. Prefer a Python query over
  a new SQL function, so no migration is needed.
- `_stream_heads`: add `ORDER BY stream_revision, id`. In current mode, keep only
  heads owned by the requested subject, and gate on all of them.
- Bounded refresh deletes all rows of each requested scope; reject requests with a
  knowledge cutoff.
- Make Gold tests assert only on their own seeded rows so leftover data can't break
  them; add retired, remapped, pending-lineage, and org-scoped cases.
- Add a `packages.helios_core.gold` branch to `test/import_boundaries.py`.

### S8 — Identity lock order and guard tests · size M · needs D6
Hand-off prompt: `Do session S8 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/identity-locks` · Concurrency-sensitive accepted code: owner review.

- [X] R12 Two identity write paths lock in opposite order → deadlock (per D6.1)
- [X] R25 Stale cached row can unassign a valid mapping in the same transaction
- [X] R27 "Rejects delete" tests pass via FK errors (would pass with triggers removed)
- [X] R28 Missing tests: identity TRUNCATE, projection tampering, remap rules
- [X] R30 Concurrency tests count deadlocks as success
- [X] R61 Readiness refresh can be stale and only covers Organizations (stale read fixed; Establishment demotion left to ADR-0012 per D6.4, see #30)
- [X] R62 Readiness refresh adds a second lock-order risk

**Recommended approach**
- Turn the review appendix's R12 reproduction into a concurrency test first.
- Pick one global order and apply it everywhere. The likely least invasive option:
  in `resolve_source_record_observation`, read the prior mapping without locks, lock
  the Subjects, then lock the Source Record and re-validate, retrying once if the
  mapping changed. Fix the two misleading comments.
- Use `populate_existing=True` wherever code reads trigger-maintained projections.
- Add a shared test helper that asserts SQLSTATE `55000` and the trigger message;
  switch the broad `DBAPIError` assertions to it.
- Classify concurrency outcomes explicitly and fail on any `40P01` in tests that
  claim ordering. Add leaf-table TRUNCATE, projection tamper, remap `to == from`,
  and wrong-`from` tests.

### S9 — API polish · size M · needs D7
Hand-off prompt: `Do session S9 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/api-polish` · OpenAPI snapshot changes: owner review.

- [X] R37 OpenAPI documents the wrong error shape
- [X] R38 No database connect/pool timeouts (per D7.4)
- [X] R41 Huge id or cursor → 500 instead of 400/404
- [X] R42 500 errors missing request-id and CORS headers
- [X] R43 405 reported as `internal_error`, no `Allow` header (per D7.1)
- [X] R44 `/readyz` failure not in the error envelope and not logged (per D7.2)
- [X] R45 CORS wildcard allowed via environment (per D7.3)
- [X] R46 `X-Request-ID` not readable by browser JavaScript
- [X] R47 Deprecated 422 constant; TestClient `httpx` deprecation (constant fixed;
  the `httpx`→`httpx2` swap is deliberately left — see PR)
- [X] R48 uvicorn/stdlib logs unstructured, duplicate tracebacks
- [X] R49 API error tests all require a database
- [X] R50 Timestamps not forced to UTC
- [X] R99 Client `X-Request-ID` trusted verbatim (per D7.5)

**Recommended approach**
- Catch unhandled exceptions inside the request middleware and render the envelope
  there, so request-id and CORS headers apply to 500s too.
- Bound `venue_id` and the decoded cursor to the BIGINT range (→ 422/400).
- Declare `responses=` with `ErrorResponse` on each route and make `code` a Literal
  enum, then regenerate the snapshot.
- Pass `exc.headers` through (for `Allow`); add `expose_headers=["X-Request-ID"]`.
- Engine: `connect_args={"connect_timeout": 5}`, `pool_timeout=10`,
  `pool_pre_ping=True`. `/readyz` logs the failure and returns the envelope.
- Validate CORS origins (reject `*`), serialize datetimes as UTC `Z`, route uvicorn
  logs through structlog, use `HTTP_422_UNPROCESSABLE_CONTENT`.
- Envelope tests override `get_session` so they run without a DB. Leave the
  `httpx` → `httpx2` swap for later unless it's a one-line change (note it in the PR).

### S10 — Test hardening sweep · size S · no decisions
Hand-off prompt: `Do session S10 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `test/hardening` · Tests only.

- [X] R29 Discovery/URL/seed writes never tested with a real commit
- [X] R59 Menu TRUNCATE test can't detect a missing trigger
- [X] R77 Golden-set test re-implements the match rule
- [X] R78 Audit report label is always "wrong"
- [X] R81 Menu rejection tests accept too many error types
- [X] R82 Migration test cleanup swallows errors; alembic helper depends on cwd
- [X] R83 Parser-isolation guard checks nothing; Gold refresh missing from no-commit test
- [X] S7-found (not in review) `test_deterministic_resolution.py::test_identical_observation_retry_reuses_immutable_bronze_rows`
  counts whole Bronze tables (`== 1`), so a full rerun on a used `*_test` DB fails
  (`assert 706 == 1`); scope the counts to its own source record (R11 class)

**Recommended approach**
- Add one real-commit test each for `run_discovery` and `resolve_urls`, using the
  concurrency tests' committed-session pattern with UUID-token cleanup-free data.
- Menu TRUNCATE: test the trigger directly (call it on a leaf, or check
  `pg_trigger`) instead of accepting `0A000`.
- Golden set: call the pipeline's `_dedupe_candidates` on seeded rows; add hard
  negatives near the 50 m boundary.
- Name the constraint or SQLSTATE in every menu rejection test.
- `check=True` on the migration restore; give `migrate()` `-c` and `cwd`.
- Point the parser guard at wherever parsing will live, or delete it until then;
  add `gold/refresh.py` to the no-commit test. Fix the audit label bug.

### S11 — Menu selector semantics ⚠ · size M · needs D5
Hand-off prompt: `Do session S11 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/menu-selector` · ADR-0005 behaviour: owner review (per D5.5).

- [X] R03 Menu content survives when the chain menu it depends on is withdrawn (prices don't)
- [X] R22 Two different chain-menu pins treated as the same item
- [X] R23 Two nodes with the same path in one page → result depends on row order
- [X] R24 History queries show chain "head" prices observed after the cutoff
- [X] R31 (selector half) Missing tests: base remap/retire, revival under cutoff, tie-break, channel wildcard, different bases, suppression, replacement
- [X] R64 Replay can falsely conflict because of Decimal formatting
- [X] R65 Tie-break compares string reprs and a surrogate id
- [X] R67 "withdrawn" reported too eagerly
- [X] R68 Selection requests not validated (naive timezones)

**Recommended approach**
- Write the missing M-rule scenario tests first (each maps to an ADR-0005 decision);
  most fixes then follow directly.
- Content uses the same `_depends_on_base` rule as price.
- Include the base page (or Organization record namespace) in canonical paths for
  base-linked nodes, so different bases never correspond.
- Load graphs in id order; if two nodes share a canonical path, treat the target as
  ambiguous rather than picking one.
- Apply the observation cutoff and subject check to the Organization head claim.
- Tie-break on the business-key tuple itself, never `repr` or surrogate ids;
  quantize Decimals before replay comparison.
- Report `withdrawn` only when the winning stream is tombstoned; reject naive
  datetimes in `SelectionRequest`.

### S12 — Fingerprint fix + venue-lifecycle ADR draft ⚠ · size M · needs D6
Hand-off prompt: `Do session S12 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/identity-matching` · Matching-policy change + Pi data script (you run it) + ADR stop.

- [X] R18 Name fingerprint drops non-English letters → wrong merges (per D6.2; no recompute script, owner chose the Pi rebuild, see D6.2)
- [X] ADR-0012 drafted for venue lifecycle: R36, R98, R105, R106 (per D6.3, D6.4) — then stop

**Recommended approach**
- Normalize: casefold → NFKD → drop combining marks → map letters NFKD can't split
  (đ→d, ø→o, ł→l, æ→ae, ß→ss, ı→i) → keep any Unicode letter or digit → collapse
  spaces. Add U+02BC and similar to the apostrophe set. Remove the `or name`
  fallback in `pipeline.py`.
- Tests: the review's bilingual collision cases, `Đông`/`Ông`, CJK, Arabic, Greek.
- Recompute script (`apps/discovery/recompute_fingerprints.py`): dry-run by default,
  prints a before/after diff and counts; `--apply` writes. Check first whether the
  fingerprint column is writable after insert — if a trigger forbids it, stop and
  report (that would need a migration).
- ADR-0012 "Venue lifecycle": options for applying changed name/address/coordinates,
  closing venues missing from N releases, and promoting Establishments to eligible;
  how that interacts with immutable parent links (new Establishment + remap).

### S13 — Venue-lifecycle implementation ⚠ · size M · needs S12 ADR accepted
Hand-off prompt: `Do session S13 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `feat/s13-venue-lifecycle`

- [X] R36 Re-seen venues update; disappearance closes (never retires) per ADR-0012
- [X] R98 Venue keeps showing a retired Organization's name
- [X] R105 Establishments never become eligible → no menu writes possible
- [X] R106 Establishment parent links are immutable (fix via new Establishment + remap, per ADR)

**Recommended approach**
- Implement exactly what ADR-0012 accepted, in discovery (apps layer), using the
  existing Identity commands; no schema change unless the ADR says so.
- Every lifecycle decision is Evidence-backed and `actor_class="rule"`, like minting.
- Tests: a re-observed POI with a new address, a POI missing for N releases, an
  Organization merge seen through `/v1/venues`, and Establishment promotion
  unblocking a Menu write.

Implementation and validation: [S13 review](https://github.com/First-Helios/First-Helios/blob/ddb5579dbd439005468581fde99f254a64a2d824/docs/reviews/2026-09-28-s13-venue-lifecycle.md).
Merged as #45 (`ddb5579`).

🚦 **Phase 5 gate — passed 2026-09-28.** Conditions verified from `main`, not from
this file: S7 #28 (`11b0f56`), S11 #33 (`572f1e1`), S12 #34 (`4c2be21`) and S13 #45
(`ddb5579`) are merged. Main CI run
[36508316467](https://github.com/First-Helios/First-Helios/actions/runs/36508316467)
on `8cbce26` (S6b, #46) is green on all five checks with `HELIOS_STRICT_DB_TESTS=1`:
1028 passed, 1 skipped (the unconditional `packages/helios_parsing has not landed yet`
placeholder, `test/test_schema_layout.py`), `alembic check` "No new upgrade operations
detected". The lifecycle acceptance suites (`test_venue_lifecycle.py`,
`test_lifecycle_cli.py`, `test_lifecycle_urls.py`, `test_lifecycle_migration.py`; 29
tests, matrix in the S13 review) ran inside that strict job; CI does not print
per-test names, so "passed" rests on the zero-failure summary plus the single
known skip.

**Passing this gate does not authorize Phase 5 code.** Per owner decision G.b, Phase 5
uses the spike's pipeline, so it first needs a **proposed ADR-0013** (next free
number; ADR-0012 is the highest on `main`), stopped for owner review, because it adds
new runtime dependencies (llama.cpp / `llama-server`, onnxruntime or fastembed for
the page classifier, possibly a headless browser for JS-only menus). The spike's open
questions Q2-Q9 (docs/spikes/menu-model/README.md, "Open questions for the owner")
are still unanswered and must be asked before drafting it. Not written in this
session. ROADMAP Phase 5's Scrapy-vs-Crawlee spike and its "ADR-0006: Scraper
framework choice" number are both stale (ADR-0006 is Gold read models); S16
absorbs that drift.

### S13b — Phase 5 pipeline ADR (draft, then stop) ⚠ · size S · needs the Phase 5 gate
Branch: `docs/adr-0013-menu-pipeline`

- [X] Ask the owner the spike's open questions Q2–Q9 (docs/spikes/menu-model/README.md,
  "Open questions for the owner") with `AskUserQuestion` before drafting
  *Answered 2026-09-28:* Q2 Pi batch job · Q3 hash of the segmented text + pipeline
  version · Q4 headless browser in ADR-0013 now · Q5 catch ≥ 0.97, false reject ≤ 0.12,
  price accuracy ≥ 0.98 · Q6 show accepted `llm` prices, labelled · Q7 plan an rknpu
  ≥ 0.9.7 upgrade (own runbook) · Q8 cooling recommended, not required · Q9 cuisine
  separate (ADR-0006 deferral stands)
- [X] Draft ADR-0013 "Phase 5 menu pipeline" as Proposed: page classifier → segmentation →
  LLM extraction → deterministic repairs → validator (owner decision G.b), with the new
  runtime dependencies (llama.cpp / `llama-server`, onnxruntime or fastembed, possibly a
  headless browser) and the Docker/Pi deployment story; relate it to ADR-0015 (the
  classifier becomes the menu-URL verifier). Stop for review; no code.

### S14 — Schema tightening migration ⚠ · size M · needs D8.1
Hand-off prompt: `Do session S14 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `fix/schema-tightening` · Models + migration: hand-reviewed SQL, owner review.

- [X] R53 Bronze tables lack their own TRUNCATE guard
- [X] R54 Some Bronze columns still editable (`first_seen_at`, `kind`, `endpoint_kind`)
- [ ] R56 **Partially fixed in #35:** Python rejects naive datetimes and out-of-scale confidence. Direct SQL `NUMERIC(6,5)` rounding remains a separate column-type migration follow-up.
- [X] R60 DB text/time checks looser than Python (whitespace, blanks, infinity)
- [X] R63 Invisible or over-long names slip through or abort the run
- [X] R69 Negative staleness allowed in Gold

**Recommended approach**
- One forward migration; check existing Pi data won't violate a new CHECK first
  (write the query, you run it on the Pi).
- Reuse `menu.whitespace()` for Unicode-aware trimming instead of `btrim`.
- Bronze: statement-level `BEFORE TRUNCATE` triggers; pin every column in the
  immutability trigger; `isfinite` on timestamps; non-blank CHECKs on kinds/outcome.
- Python side: reject naive datetimes and out-of-scale confidence in the contracts.
- Generated SQL committed under `docs/reviews/sql/` with a byte-compare test and an
  upgrade → downgrade → upgrade round trip.

### S15 — Infra and tooling cleanup ⚠ · size S · needs D8.2, D8.3
Hand-off prompt: `Do session S15 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `chore/infra-tooling` · Split into an `infra/` PR and a config-only PR.

- [X] R84 `.dockerignore` patterns only match at the repo root
- [X] R85 Root `.env` is read by nothing, but docs say it is
- [X] R86 Compose's `DATABASE_URL` leaks in from your shell
- [X] R90 Images pinned by tag, not digest
- [X] R91 `mypy.ini` dead and redundant sections
- [X] R92 `ruff.toml` dead ignores; no security rules
- [X] R93 ruff version differs between pre-commit and the lockfile
- [X] R96 `pyproject.toml` name, unused and undeclared dependencies
- [X] R113 No volume for `var/`, so containerised runs lose their caches
- [X] R114 Compose has no project name or restart policy

**Recommended approach**
- `infra/` PR: `**/` patterns in `.dockerignore`; compose `name: helios`,
  `restart: unless-stopped`, a `var` volume at `/app/var`, and a compose-specific
  variable (e.g. `HELIOS_COMPOSE_DATABASE_URL`) instead of reusing `DATABASE_URL`;
  images pinned by digest with the tag in a comment.
- Config PR: delete dead mypy/ruff sections, add ruff `S` rules (fix or justify
  hits), align pre-commit ruff with the lockfile, rename the project, declare
  `pydantic`/`starlette`, drop `pytest-asyncio`. README: say which env file is read,
  if any.

### S16 — Docs drift sweep · size M · needs D6.5
Hand-off prompt: `Do session S16 from docs/reviews/2026-09-22-remediation-checklist.md.`
Branch: `docs/drift-sweep` · CLAUDE.md edits (if any remain after S1): owner review.

*Owner decision (2026-09-28, end of S13b):* S16 grows into a full documentation
consolidation run by an **Opus 5.5 lead with an agent swarm** (overrides the §2 model row
and hand-off rule 3.4 "don't spawn subagents" for this session only). Goal: code,
planning and status neat and concise. **Historical docs are deleted** once their lasting
decisions live in an ADR, README or the code; git keeps them, and `docs/HISTORY.md` lists
each removed file with its last commit. **Scope: docs, docstrings, code comments and
templates only**, with no behaviour changes. The active trackers (this checklist, the
hand-off) stay until S17.

- [X] Every item in review §7 "Doc drift" (README, ROADMAP, ADR statuses and numbers, plans, retro, LEARNING_GUIDE, docstrings, templates)
- [X] R51 ADR-0004 vs ADR-0008 on the API reading Identity models (per D6.5)
- [X] R97 Fix the misleading "cannot forge" test comment
- [X] Pick one file as the single status source; others link to it

**Recommended approach**
- Make README the single "current status" page; ROADMAP keeps plans and phase
  definitions and links to README for status. Remove duplicated status text from
  plans and reviews rather than updating it in several places.
- Renumber forward ADR references to "next free number" instead of guessing numbers.
- Fix code docstrings in the same PR (they're listed in §7).
- Mark historical references (removed files, old test counts) as historical rather
  than deleting context.

### S17 — Close-out · size S · needs everything above
Hand-off prompt: `Do session S17 from docs/reviews/2026-09-22-remediation-checklist.md.`

- [ ] Every R01–R117 is ticked here or listed in D9
- [ ] Deferred items (D9) copied to ROADMAP with their triggers
- [ ] Final strict CI on a fresh DB; result recorded in the session log

**Recommended approach**
- Grep this file for unticked boxes; for each, either link its PR or move it to D9
  with a reason.
- Add a short "Remediation complete" note at the top of the review document.

---

## Session log

Agents add one row per session (or per resume).

| Date | Session | Branch | PR | Status | Resume notes |
|---|---|---|---|---|---|
| 2026-09-23 | S1 | fix/guardrails | #23 | Merged | — (ticks recorded by S2; #22 wasn't on `main` yet) |
| 2026-09-23 | S2 | fix/crawler-etiquette | #24 | Merged | — |
| 2026-09-23 | S3 | fix/url-pipeline | #25 | Merged | — (D3.7–3.9 asked and answered at session start) |
| 2026-09-23 | S4 | fix/menu-url-quality | #26 | Merged | — (D3.4 classifier → Phase 5 ADR; D3.5 platform fallback, one URL; see ADR-0010 Amendment 3) |
| 2026-09-23 | S5 | docs/adr-0011-evidence-endpoints | #27 | Merged; ADR-0011 accepted 2026-09-27 | — (D4 answered; D4.6 = S6b and D4.7 = 20 days approved by owner; S6 subsequently merged as #42) |
| 2026-09-23 | S7 | fix/gold-refresh | #28 | Merged (changes ADR-0006 refresh behaviour; amendment note added) | — (D5 already on `main`. #27 was merged, but ADR-0011 still says `Status: Proposed`, so S6 stays blocked until you record acceptance. Also rejects observation-cutoff requests; see PR) |
| 2026-09-23 | S8 | fix/identity-locks | #30 | Merged (concurrency-sensitive) | — (D6.1 answered on `main`. Lock order documented in `identity/commands.py`; the resolver plans without locks, then locks and re-checks inside a savepoint and retries once (`ResolutionConflictError`). R61 fixed for the stale read only; Establishment demotion is left to ADR-0012 (D6.4). Transactions that run several commands (discovery batches, URL resolve-then-assign) can still deadlock; this is documented, not fixed) |
| 2026-09-24 | S9 | fix/api-polish | #32 | Merged | — (row added by S11; S9 left no log row) |
| 2026-09-24 | S10 | test/hardening | #31 | Merged | — (ran in parallel with S9; `seed_sample_venues` gone since S1, so R29 covers discovery + URL paths; forged `subject_id=None` raises `22023`, now pinned. Row restored by S11: the S8 merge dropped it) |
| 2026-09-24 | S11 | fix/menu-selector | #33 | Merged (ADR-0005 conformance per D5.5, no amendment) | — (Base-linked targets now carry `("base", <pinned page id>)`, so Gold `target_path` for inherited prices changes. An ambiguous page supplies nothing (no new state, since Gold's `price_state` CHECK would need a migration). `withdrawn` only when every head is a tombstone. See PR "Design choices") |
| 2026-09-24 | S12 | fix/identity-matching | #34 | Merged; ADR-0012 accepted 2026-09-27 | — (D6.2 confirmed: no recompute script, rely on the Pi rebuild; ADR-0009 Amendment 1 records the fingerprint rule. Symbol-only names are now skipped before Bronze (S6: record them like blank names). ADR-0012 §5 goes beyond D6.4: Places must be promoted too, or no Establishment can ever be eligible. S13 is now ready for implementation under the revised accepted ADR) |
| 2026-09-24 | S14 | fix/schema-tightening | #35 | Merged (migration `12a76ebed458` + models) | — (Uses a new `bronze.whitespace()` instead of `menu.whitespace()`: Bronze/Identity sit below Menu. Existing CHECK names kept. R56's DB rounding stays (would need `ALTER COLUMN TYPE`); Python rejects first. Gold staleness is clamped to 0. Run `docs/reviews/sql/2026-09-22-s14-schema-tightening-precheck.sql` on the Pi before upgrading. `test_legacy_identity_reset` and `test_gold_migration` now compare at `5f3a9c1e7b24`, not head) |
| 2026-09-28 | S6b | fix/platform-menu-urls | #46 | Merged (`8cbce26`; main CI green) |
| 2026-09-28 | Gates (G.a, G.b) | docs/gate-adjudication | #47 | Merged (`b2bba73`; ADR-0014/0015 still Proposed) | — (see "2026-09-28 gate resolution" below; Phase 5 gate ticked; Pi gate split 1a/1b, both closed) | — (see "2026-09-28 S6b platform menus" below; open question on multi-location chain platform links) |
| 2026-09-28 | S13b | docs/adr-0013-menu-pipeline | #48 | Draft ⚠ (ADR-0013 Proposed; stop for review) | — (see "2026-09-28 S13b Phase 5 pipeline ADR" below) |
| 2026-09-28 | S16 | docs/drift-sweep | #49 | Merged (`576c137`) | — (see "2026-09-28 S16 documentation consolidation" below; #48 found merged at start, ADR-0013 still Proposed) |
| 2026-09-28 | S6c | feat/location-overrides | #50 | Merged (`e61486c`) | — (see "2026-09-28 S6c location overrides" below; next: S6e corrections applier) |
| 2026-09-29 | S6d part 2 | feat/page-classifier | #52 | Draft ⚠ (new `menu` extra, worker image target; stacked on #51) | — (see "2026-09-29 S6d menu-URL re-verification" below; merge #51 first, then retarget #52 to `main`) |
| 2026-09-29 | S6d part 1 | feat/menu-url-reverification | #51 | Open (ADR-0015 accepted at session start; ADR-0013 classifier parts accepted) | — (see "2026-09-29 S6d menu-URL re-verification" below; next: S6d part 2 `classifier-v1`, then S6f) |


### 2026-09-27 delegated follow-up

The owner delegated resolution of the review findings and acceptance of both
ADRs. ADR-0011 now defines rejected Bronze observations and explicit Identity
refusal. ADR-0012 now requires durable completion/coverage, fresh derived-URL
verification on rebrand, and monotonic lifecycle replay. S13 is ready to
implement, not completed. S6 passed strict `make ci` on a fresh disposable
database: 957 passed, one expected parsing-package placeholder skip, 92% coverage.
`alembic check` found no drift; the Docker build and `/healthz` smoke test passed.
At that point S6 awaited review and merge. It subsequently merged as #42 and the
owner-authorized Pi rebuild completed 2026-09-28. The new precision audit still
requires confirmation; Phase 5 remains closed. Current operational status is in the
[S6 runbook](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-27-s6-pi-rebuild.md). This supersedes earlier proposed/draft
status text in the historical session log.

### 2026-09-28 Pi rebuild

S6 (#42) merged with green CI. On the owner's explicit instruction, the agent
backed up the Pi database and source snapshot, retained the previous
`infra_postgres_data` volume offline, and deployed the merged commit into a fresh
`helios_postgres_data` volume. Discovery completed with 10,014 observations and
9,996 venues; every observation has the full provenance chain. The API and
schema checks passed. See [the execution record](https://github.com/First-Helios/First-Helios/blob/46d81d4e56612ef040eb552b02247b984f187c90/docs/reviews/2026-09-28-pi-rebuild-results.md).
URL resolution remains stopped pending confirmation of the new precision audit.

### 2026-09-28 precision review

All 43 duplicate pairs and 45 geocode flags have evidence-backed agent
assessments or explicit unresolved notes in the [precision review](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-28-precision-review.md).
Results: 23 duplicate pairs, 4 distinct, 16 unresolved; 20 corroborated
geocodes, 3 supported wrong, 22 unresolved. Owner labels remain pending.
The Pi gate remains closed; confirm/correct the coordinate defects and resolve
outstanding evidence before acceptance. S6b is not Pi-gating.


### 2026-09-28 S13 implementation

Implemented accepted ADR-0012 in isolated `feat/s13-venue-lifecycle`, based on
`main@46d81d4` (PRs #43 and #44 were already merged; no open PRs at start).
See the [S13 review](https://github.com/First-Helios/First-Helios/blob/ddb5579dbd439005468581fde99f254a64a2d824/docs/reviews/2026-09-28-s13-venue-lifecycle.md) for the schema contract,
acceptance matrix, validation, and limitations. Existing worktrees and the Pi
were untouched. Both gates remain closed; broad duplicate cleanup is deferred.

### 2026-09-28 S6b platform menus

S13 (#45) was confirmed merged (`main@ddb5579`) before starting. Branch
`fix/platform-menu-urls`, PR #46. Discovery now returns the own-site menu plus
verified ordering-platform pages (first link per platform host, at most
`MAX_PLATFORM_CANDIDATES`), and `resolve_urls` persists each under `<gers>` or
`<gers>|<host>` with S13's per-key rules (needs_review / foreign-Organization keys
kept as history; fresh verification after a transition). Strict `make ci` on a
fresh disposable DB: 1028 passed, one expected parsing placeholder skip, 93%
coverage; `alembic check` clean. No schema change. Open question for the owner in
the PR: chain homepages linking one platform page per location give every venue
the first link. The Pi was not touched; the Pi gate stays closed pending the
precision-review adjudication.

### 2026-09-28 gate resolution (owner decisions G.a, G.b)

Branch `docs/gate-adjudication` from `main@8cbce26`. Main CI run 36508316467 on
`8cbce26` was green on all five checks before starting. Docs/data only; no code, no Pi
access, `resolve_urls` not run.

- **Phase 5 gate ticked** (evidence in the S13 block). Phase 5 code waits for a proposed
  ADR-0013 (new session S13b); the spike's Q2–Q9 are unanswered.
- **Precision review adjudicated** under G.a. Labels are in `reviewed.json`
  (`label_by: "agent (owner-delegated 2026-09-28)"`) with explicit criteria. All 100 sampled
  rows were hand-checked (the 55 unflagged rows against the business at each address, and
  every row searched for twin records). Result: 4 wrong geocodes and 6 sampled venues with
  a confirmed duplicate, so **both ROADMAP bars fail**; 17 / 11 rows stay unresolved. The
  audit detector misses twins separated by a bad coordinate and chain location-label
  records.
- **Gate conflict resolved:** the owner's assessment holds in the code. The Pi gate is
  split into 1a (location quality) and 1b (URL-resolution readiness), both closed, criteria
  in the S6b block. ADR-0014 (location overrides, 1a) and ADR-0015 (menu-URL
  re-verification, 1b) are drafted as Proposed and stop for owner review; their
  implementation is S6c / S6d.
- Minimal status fixes so no doc says otherwise: ROADMAP Phase 4 status paragraph and the
  S6 runbook (step 5 no longer opens URL resolution on the audit alone). Remaining ROADMAP
  Phase 5 drift (Scrapy-vs-Crawlee, "ADR-0006" scraper number) is left for S16.

### 2026-09-28 S13b Phase 5 pipeline ADR

Branch `docs/adr-0013-menu-pipeline` from `main@b2bba73` (#47 merged). Docs only; no
code, no Pi access, `resolve_urls` not run. The owner answered the spike's Q2–Q9 at
session start (answers in the S13b block and in ADR-0013). Two answers differ from the
agent's recommendation and shape the ADR: **Q4** puts the headless browser (Playwright +
Chromium) into ADR-0013 now, so §4 adds a measure-before-enable step on the spike's 32
JS-only pages (the one stage the spike never measured); **Q7** plans an rknpu ≥ 0.9.7
kernel upgrade as a separate owner-run operation, while Phase 5 stays CPU-only.
ADR-0013 also settles ADR-0011's deferred Capture-targeted Evidence locators, makes the
page classifier ADR-0015's `classifier-v1` verifier (option C), and lists five new open
questions (page scope for per-location platform pages, PDFs, robots for rendered
sub-requests, spot-check size, promotional rows). Phase 5 code waits for acceptance;
ADR-0014/0015 are still Proposed (S6c/S6d wait on them).

### 2026-09-28 S16 documentation consolidation

Branch `docs/drift-sweep` from `main@9796aa6` (#48 merged). Owner decision in the S16
block: Opus lead plus a seven-worker Opus swarm on disjoint files, then an independent
read-only reviewer. Docs, docstrings, comments and templates only; no Pi access,
`resolve_urls` not run; S6c/S6d code untouched.

- README.md is the single status page (status, gates 1a/1b with the re-audit label
  criteria, staging, how to run, ADR index). ROADMAP.md holds phase definitions only;
  Phases 3/5/6 follow Proposed ADR-0013 (G.b); ADR-number drift and H3 leftovers fixed.
- 21 historical docs plus the precision-review data deleted after their lasting
  decisions moved (audits in the PR); [docs/HISTORY.md](../HISTORY.md) lists each with
  its last commit. Kept: the Step 5 schema proposal (normative for ADR-0005), RFC-0001,
  the spike README (log trimmed), these trackers, `docs/reviews/sql/`.
- Accepted ADRs: status lines, permalinks, number fixes and dated implementation notes
  only; ADR-0008 Amendment 2 records D6.5 (R51). R97 comment fixed.
- Markdown: 58 files / 14,601 lines → 36 / 9,689. Strict `make ci` on a fresh
  disposable DB: 1028 passed, one expected parsing placeholder skip, 93% coverage;
  `alembic check` clean.
- For the owner: CLAUDE.md accuracy edits (make lint/typecheck, commit-msg scope); the
  stop-and-ask glob `packages/**/db/models/**` matches nothing and `apps/discovery/models.py`
  (bronze ORM models) is on no stop list or CODEOWNERS entry; the audit CLI's `--help`
  text changed with its docstring.

### 2026-09-28 S6c location overrides

Branch `feat/location-overrides` from `main@576c137` (#49 merged). No Pi access,
`resolve_urls` not run, S6d code untouched; ADR-0013/0015 stay Proposed.

- **Owner decisions at start:** ADR-0014 accepted (option A); a first application is an
  in-place correction, not a relocation; address overrides ship now. Recorded in the ADR.
- **Code:** `apps/discovery/location_overrides.py` + `config/location_overrides.yaml`;
  `run_discovery` applies the effective location before minting, dedupe and lifecycle
  projection; `project_observation` re-opens its checkpoint for an unprojected override
  Version and never relocates on an override change. No migration: the override
  namespace is created on demand and projection reuses `discovery_lifecycle_state`.
- **Audit:** `street_key` keeps five-digit house numbers and folds Trail/Trl and
  MLK spellings; new `find_twins` (`twin_candidates` in the worksheet) and a `--seed`
  flag for the re-audit.
- **Correction plan + runbook:**
  [2026-09-28-location-correction-plan.md](./2026-09-28-location-correction-plan.md).
  One override entry committed (Lali Son, official pin); P. Terry's MLK, El Sol y La Luna
  and La Parrilla need a qualifying basis (the cached Nominatim points are on the Pi,
  not in the repo). Merges and retirements have no CLI, so a new session **S6e
  (corrections applier)** is proposed and added to the progress table.

### 2026-09-29 S6d menu-URL re-verification

Branch `feat/menu-url-reverification` from `main@e61486c` (#50 merged). No Pi access,
`resolve_urls` not run, S6c/S6e code untouched; gate 1b stays closed.

- **Owner decisions:** see the S6d block. ADR-0015 accepted with Amendment 1; ADR-0013
  Amendment 1 accepts its page-classifier parts and records the rendering decision.
- **Render probe** (local, honest UA, robots obeyed): 60 spike-sample URLs; outputs in
  `var/spikes/menu-model/render-probe-2026-09-29/` (gitignored). Platform links: 0/37
  readable without JavaScript; rendered, 19/37 priced menus (Square/Clover/Grubhub
  headless; Toast headed only); 3 DoorDash stayed `403`; 4 gift-card links
  robots-disallowed. JS-only own-site pages: 1/23 priced after render (most are carts,
  locators or empty sites). Most rendered Toast pages print the venue's street line, which
  the chain guard matches.
- **Part 1 code:** `PageVerifier`/`HeuristicVerifier` (`s4-v1`) injected into
  `SiteFetcher`; `verify_menu_attempt` separates page verdicts from an unreadable homepage;
  platform pages pass the page check; `platform_links_by_host` + `address_on_page` +
  `rank_by_address` for chain homepages (`PlatformAmbiguous`); `url_pipeline` records
  `verifier`, re-verifies on verifier change or `REVERIFY_WINDOW` (90 days), withdraws
  with a `rejected/menu_not_verified` observation (`menu-url-reverify`), and retries
  rule-withdrawn records; new report counters. No migration (`alembic check` clean).
- **Not built (flagged):** phone matching (Overture ingestion lacks `phones`); address
  overrides are not consulted by the chain guard.
- **Part 2 (#52, ⚠ draft, stacked on #51):** `packages/helios_parsing` (segmentation, v3
  price tokens, classifier features), `apps/menu_pipeline` (pinned model files, plain-Python
  scorer, training/evaluation script with an ephemeral scikit-learn), `menu` extra
  (`fastembed` 0.8.1), `worker` Docker target + Compose `worker` (profile `menu`);
  `resolve_urls` uses `classifier-v1`. [Evaluation](./2026-09-29-classifier-v1-evaluation.md):
  nested CV 0.976 / 0.833, held-out 9/9 menus, 21/21 accepted pages are menu content. It
  rejects every rendered Toast order page, so S6f trains a successor. Strict `make ci`: 1107
  passed, 0 skipped, 91% coverage; `alembic check` clean; both images built and smoke-tested.
