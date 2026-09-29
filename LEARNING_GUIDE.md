# Helios V2 — Learning Guide

> **Purpose.** A twelve-module course for the human reviewer. The V2 build is
> [agent-driven](./ROADMAP.md#60-the-agenthuman-split): agents write the code
> and you judge it. Read a module *before reviewing* the phase it maps to, so
> you can judge the work rather than just merge it.
>
> Treat each module's **self-check rubric as the bar**: if you can't answer it,
> you can't meaningfully review that phase's PRs. Exercises are optional and
> belong in a throwaway scratchpad repo. For what is built today, see
> [README.md § Status](./README.md#status).
>
> **Free-first rule.** Every module's primary resources are free. Paid
> resources are marked `[$]` and listed only where the free ones fall short.

---

## Which module for which phase

Phase numbers are the ones in [ROADMAP.md §5](./ROADMAP.md); the roadmap gives
the build order.

| Phase | Modules |
|---|---|
| 0 — Foundations & tooling | M1, M2, M3 |
| 1 — Domain model & migrations | M5, M6 |
| 2 — First Light (read API + staging) | M11, M12 |
| 3, 5, 6 — Menu reading and ingest ([ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md)) | M4, M7, M8, M9 |
| 4 — Venue discovery, identity & geocoding | M7, M10 |
| 7 — API surface | M11 |
| 8 — Operations | M12 |
| 9 — Harden | Revisit your weakest modules |

## How each module is laid out

- **Why it matters** — the tie to Helios.
- **Core concepts** — the ideas to internalize.
- **Resources** — free first, paid marked `[$]`.
- **Exercises** — scratchpad practice. *Optional.*
- **In this repo** — the real code or decision to read as the worked example.
- **Self-check** — answer from memory before reviewing that phase.

## Contents

- [M1 — Modern Python Project Hygiene](#m1--modern-python-project-hygiene)
- [M2 — Git & Team Workflow](#m2--git--team-workflow)
- [M3 — Design Docs (ADRs and RFCs)](#m3--design-docs-adrs-and-rfcs)
- [M4 — Testing](#m4--testing)
- [M5 — Relational Modeling](#m5--relational-modeling)
- [M6 — SQLAlchemy 2.0 & Alembic](#m6--sqlalchemy-20--alembic)
- [M7 — HTTP, HTML & the Real Web](#m7--http-html--the-real-web)
- [M8 — Scraping & Menu Extraction](#m8--scraping--menu-extraction)
- [M9 — Data Engineering Patterns](#m9--data-engineering-patterns)
- [M10 — Geospatial](#m10--geospatial)
- [M11 — API Design](#m11--api-design)
- [M12 — Operations](#m12--operations)
- [How to study alongside a day job](#how-to-study-alongside-a-day-job)

---

## M1 — Modern Python Project Hygiene

**Why it matters.** V1's problems started with "the project grew without a
structure." A `pyproject.toml`, a lockfile, a linter and a type checker are the
difference between hacking and engineering.

### Core concepts

- Virtual environments and why isolation matters.
- `pyproject.toml` (PEP 621) as the single source of project metadata and deps.
- Lockfiles and reproducibility.
- Runtime vs dev dependencies.
- Linters, formatters, type checkers and tests: four distinct jobs.
- `ruff` as the linter + formatter that replaces flake8/black/isort.
- `mypy --strict`: what "strict" actually changes.
- Pre-commit hooks: catching mistakes before they reach CI.

### Resources

- [PEP 621 — Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/).
- [uv docs](https://docs.astral.sh/uv/) — Getting Started → Projects.
- [ruff docs](https://docs.astral.sh/ruff/) — the "Rules" overview.
- [mypy — Getting started](https://mypy.readthedocs.io/en/stable/getting_started.html) and the [type hints cheat sheet](https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html).
- [pre-commit](https://pre-commit.com/) — the quickstart is enough.
- [$] *Fluent Python, 2nd ed.* (Luciano Ramalho) — chapters 1, 8, 15.

### Exercises

1. Write a `pyproject.toml` from scratch for a tiny calculator library with
   `ruff`, `mypy` and `pytest` as dev deps. Install with `uv sync`.
2. Write three untyped functions, run `mypy --strict`, fix every error. Try
   `list` vs `list[int]` vs `Sequence[int]` and note the difference.
3. Wire ruff and mypy into `.pre-commit-config.yaml`. Commit a lint error and
   confirm the hook blocks it.

### In this repo

[`pyproject.toml`](./pyproject.toml), [`uv.lock`](./uv.lock),
[`ruff.toml`](./ruff.toml), [`mypy.ini`](./mypy.ini) (strict, repo-wide),
[`.pre-commit-config.yaml`](./.pre-commit-config.yaml) and the
[`makefile`](./makefile) targets (`make ci` is described in
[CLAUDE.md](./CLAUDE.md#verification--run-before-calling-anything-done)).
[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs the same tools
in CI.

### Self-check

- [ ] I can explain the difference between `requirements.txt` and a lockfile.
- [ ] I can write a minimal `pyproject.toml` from memory.
- [ ] I know what `ruff` does that `black` doesn't.
- [ ] I can say what `mypy --strict` enforces that default `mypy` doesn't.
- [ ] I understand why pre-commit runs locally and not only in CI.

---

## M2 — Git & Team Workflow

**Why it matters.** Every V2 change lands through a PR, even on a solo
project. This module turns "someone who uses git" into "someone who
collaborates with git."

### Core concepts

- The object model: commits, trees, blobs, refs.
- Branches are labels on commits.
- Rebase vs merge; interactive rebase; `git reflog` as the safety net.
- [Conventional Commits](https://www.conventionalcommits.org/).
- PR anatomy: title, description, checks.
- Branch protection and CODEOWNERS — and what they can't do for a solo
  maintainer.
- What a squash merge does to history.

### Resources

- [Pro Git](https://git-scm.com/book) — chapters 2, 3, 5, 7.1–7.3.
- ["Git Internals" talk](https://www.youtube.com/watch?v=P6jD966jzlk) (40 min) — the object model.
- [Conventional Commits spec](https://www.conventionalcommits.org/en/v1.0.0/).
- [GitHub — About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
- [Atlassian — Merging vs Rebasing](https://www.atlassian.com/git/tutorials/merging-vs-rebasing).

### Exercises

1. Make three commits on a branch, then squash them into one with an
   interactive rebase and a conventional-commit message.
2. Cause and resolve a rebase conflict.
3. Lose a commit with `git reset --hard`, then recover it from `git reflog`.

### In this repo

The workflow, commit format and merge gate are in
[CONTRIBUTING.md](./CONTRIBUTING.md) and
[CLAUDE.md § What actually gates a merge](./CLAUDE.md#what-actually-gates-a-merge);
the reasoning is in [ROADMAP.md §6.0](./ROADMAP.md#60-the-agenthuman-split).
Files: [`.github/pull_request_template.md`](./.github/pull_request_template.md),
[`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE/),
[`.github/CODEOWNERS`](./.github/CODEOWNERS) and
[`.github/workflows/pr-title.yml`](./.github/workflows/pr-title.yml).

### Self-check

- [ ] I can explain what `git commit` does in terms of objects, not UI.
- [ ] I know when to rebase vs merge and why.
- [ ] I can recover a commit "lost" to `git reset --hard`.
- [ ] I can write a conventional-commit message without looking it up.
- [ ] I can explain why this repo requires 0 approvals and what that means for
      review.

---

## M3 — Design Docs (ADRs and RFCs)

**Why it matters.** V1 kept no record of *why* decisions were made, so every
decision stayed open for re-debate. V2 writes them down.

### Core concepts

- ADR (Architecture Decision Record): short, one decision.
- RFC (Request for Comments): longer, proposes a change and invites review
  before implementation.
- Statuses: Proposed, Accepted, Superseded, Deprecated.
- Once accepted, an ADR's decision is not rewritten; a new ADR supersedes it.
- Context → decision → consequences → alternatives considered.
- When *not* to write one: trivial or easily reversed choices.

### Resources

- [Michael Nygard — Documenting Architecture Decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
- [adr.github.io](https://adr.github.io/) — templates and examples.
- [Oxide — RFD 1: Requests for Discussion](https://oxide.computer/blog/rfd-1-requests-for-discussion).
- [Google Technical Writing courses](https://developers.google.com/tech-writing).

### Exercises

1. Read five ADRs from [joelparkerhenderson/architecture-decision-record](https://github.com/joelparkerhenderson/architecture-decision-record/tree/main/examples).
2. Write an ADR for a decision you've already made. Fill in Alternatives
   honestly.
3. Re-read it a week later and edit until it's still clear.

### In this repo

[`docs/adr/`](./docs/adr/) (template: [0000](./docs/adr/0000-template.md)) and
[`docs/rfc/`](./docs/rfc/). Good examples:
[ADR-0001](./docs/adr/0001-stack-choice.md) (stack choice),
[ADR-0003](./docs/adr/0003-three-layer-schema.md) superseded by
[ADR-0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md) (how
supersession looks), and [RFC-0001](./docs/rfc/0001-menu-pricing-first.md).
When to write which is in
[CONTRIBUTING.md](./CONTRIBUTING.md#adrs-rfcs-and-plans).

### Self-check

- [ ] I can explain the difference between an ADR and an RFC.
- [ ] I know when a decision deserves an ADR.
- [ ] I understand why an accepted ADR is superseded rather than edited.
- [ ] I know what the Consequences section is for (not restating the decision).

---

## M4 — Testing

**Why it matters.** V1's parsing was "tested by running it on real scrapes and
squinting." V2 gates on tests, golden sets and measured precision, and the
menu pipeline is judged by quality bars against a labelled gold set.

### Core concepts

- The testing pyramid: many unit, some integration, few end-to-end.
- pytest fixtures (scope, finalizers, factories) and `parametrize`.
- Golden files: "this input produces exactly this output."
- Property-based testing (Hypothesis) as a way to find cases you didn't think of.
- Test doubles: stubs, mocks, fakes, spies.
- Replaying recorded HTTP instead of making live calls in CI.
- Precision and recall against a labelled set.
- Coverage vs quality; fixing flaky tests instead of retrying them.

### Resources

- [pytest docs](https://docs.pytest.org/en/stable/) — getting started, fixtures, parametrize.
- [Hypothesis quickstart](https://hypothesis.readthedocs.io/en/latest/quickstart.html).
- [Martin Fowler — TestDouble](https://martinfowler.com/bliki/TestDouble.html).
- [Obey the Testing Goat](https://www.obeythetestinggoat.com/) (free book).
- [pytest-cov](https://pytest-cov.readthedocs.io/en/latest/).

### Exercises

1. Write `add(a, b)` with three parametrized tests, then one Hypothesis
   property test (`add(a, b) == add(b, a)`).
2. Write a golden-file test for a function that renders a dict to YAML.
3. Write a flaky test using `time.time()` and fix it with `monkeypatch`.

### In this repo

- [`test/conftest.py`](./test/conftest.py) — database fixtures that skip
  locally and fail under strict mode.
- [`test/fixtures/golden_matches.json`](./test/fixtures/golden_matches.json)
  and [`test/test_discovery_audit.py`](./test/test_discovery_audit.py) — a
  golden set that gates matcher precision.
- [`test/test_web_client.py`](./test/test_web_client.py) — HTTP replayed from
  a mock transport, no live network.
- [`test/test_menu_schema.py`](./test/test_menu_schema.py) — heavy use of
  `parametrize`.
- The menu pipeline's quality bars: [ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md)
  and the [menu-model spike](./docs/spikes/menu-model/README.md).

### Self-check

- [ ] I can explain why the testing pyramid is shaped that way.
- [ ] I know the difference between a mock and a fake.
- [ ] I can explain precision vs recall and which one a false merge hurts.
- [ ] I can tell whether a flaky test is the code's fault or the setup's.
- [ ] I can read a coverage report and say which uncovered lines matter.

---

## M5 — Relational Modeling

**Why it matters.** The schema is the backbone of the system. Get it wrong and
every later phase is painful; this is also the hardest part to reverse.

### Core concepts

- Normal forms 1NF–3NF, and when to break them on purpose.
- Primary keys vs unique constraints; foreign keys (cascade, restrict, set
  null); `CHECK` constraints.
- Indexes: B-tree, partial, composite, expression, GIN for JSONB.
- Transaction isolation levels.
- When JSONB is right and when it's a cop-out.
- Triggers that enforce invariants the app can't be trusted with (e.g.
  append-only tables).
- Migration safety: adding a NOT NULL column to a large table.

### Resources

- [PostgreSQL docs — Data Definition](https://www.postgresql.org/docs/current/ddl.html) and [Trigger Functions](https://www.postgresql.org/docs/current/plpgsql-trigger.html).
- [Use The Index, Luke](https://use-the-index-luke.com/) (free book).
- [PostgreSQL — Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html).
- [$] *SQL Antipatterns* (Bill Karwin).
- [$] *Designing Data-Intensive Applications* (Martin Kleppmann), chapters 2, 7.

### Exercises

1. In a local Postgres, build `authors`, `books` and `author_books`
   (many-to-many). Load some rows.
2. Query "books by authors with ≥ 5 books", run `EXPLAIN ANALYZE`, add an
   index, compare.
3. Write a trigger that rejects `UPDATE` and `DELETE` on a table, making it
   append-only.

### In this repo

Helios uses triggers deliberately: Bronze provenance and Menu aggregates are
immutable, and identity history is append-only, enforced in the database.
Read the `CREATE TRIGGER` statements in
[`alembic/versions/`](./alembic/versions/) (for example
`6344725640bd_add_bronze_provenance_foundation.py` and
`d83f0a21c592_add_immutable_menu_aggregates.py`), the models in
`packages/helios_core/*/models.py` and
`packages/helios_core/domains/menu/models.py`, and the
[identity/provenance ERD](./docs/diagrams/0004-identity-provenance-erd.md).
ROADMAP Phase 1 has a reviewer's checklist for schema PRs.

### Self-check

- [ ] I can explain 1NF, 2NF, 3NF without looking them up.
- [ ] I know why you want a foreign key even if the app "handles it."
- [ ] I can read `EXPLAIN ANALYZE` and spot a missing index.
- [ ] I can say which Helios invariants live in triggers and why.
- [ ] I can describe a migration that would lock a large table and how to
      avoid it.

---

## M6 — SQLAlchemy 2.0 & Alembic

**Why it matters.** V2 uses SQLAlchemy 2.0's typed `Mapped[...]` style, so
mypy sees the models. Alembic autogenerate saves time only if you understand
what it produces.

### Core concepts

- Declarative base with typed `Mapped[T]`; `mapped_column`, `relationship`.
- Session lifecycle: begin, commit, rollback, close — and what happens on an
  exception.
- Eager vs lazy loading (`selectinload`, `joinedload`, `lazy="raise"`).
- Alembic autogenerate: what it catches and what it misses (renames, triggers,
  functions).
- Reviewing migrations by hand.
- Zero-downtime migrations: expand → migrate → contract.

### Resources

- [SQLAlchemy 2.0 Unified Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/index.html) — all of it.
- [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).
- [Alembic — What does autogenerate detect?](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect).

### Exercises

1. Rewrite the M5 bookstore in SQLAlchemy 2.0 style with full type hints.
2. Set up Alembic and apply an initial migration to an empty database.
3. Add a column, run `alembic revision --autogenerate`, and review what it
   caught. Rename a column and see what it misses.

### In this repo

- [`packages/helios_core/db/base.py`](./packages/helios_core/db/base.py) — the
  shared `Base`.
- [`packages/helios_core/db/model_registry.py`](./packages/helios_core/db/model_registry.py)
  — why every model must be registered for autogenerate.
- [`packages/helios_core/db/session.py`](./packages/helios_core/db/session.py)
  — lazy engine and session factory.
- [`alembic/env.py`](./alembic/env.py) and [`alembic/versions/`](./alembic/versions/)
  — hand-reviewed migrations; CI's `alembic check` fails when models and
  migrations disagree.
- The rules for models and migrations are in [CLAUDE.md](./CLAUDE.md#repo-conventions).

### Self-check

- [ ] I can explain the difference between SQLAlchemy Core and ORM.
- [ ] I know what `selectinload` does vs `joinedload`.
- [ ] I can describe the session lifecycle, including on an exception.
- [ ] I know what autogenerate misses, and why Helios migrations still need a
      hand review.
- [ ] I can describe a zero-downtime migration in three steps.

---

## M7 — HTTP, HTML & the Real Web

**Why it matters.** Fetching restaurant sites is HTTP and HTML parsing with
good manners. V1's scrapers failed partly because they ignored what the network
was doing: redirects, cookies, caching, `robots.txt`.

### Core concepts

- HTTP verbs and status codes (301 vs 302 vs 307, 401 vs 403).
- Headers that matter: `User-Agent`, `Accept-Encoding`, `Cache-Control`,
  `Cookie`, `Referer`.
- Redirect chains, and why a fetcher follows them by hand.
- `robots.txt` (RFC 9309) — what it is and isn't; `Crawl-delay`.
- Sitemaps — often better than crawling.
- DOM, CSS selectors, XPath.
- JSON-LD and microdata — structured data in plain sight.
- What `curl` sees vs what a browser sees (JS-rendered pages).
- SSRF: why a fetcher must refuse private addresses.

### Resources

- MDN: [HTTP overview](https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview), [headers](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers), [status codes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status).
- [High Performance Browser Networking](https://hpbn.co/) — chapters 9–11.
- [Google — robots.txt specification](https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt).
- [httpx docs](https://www.python-httpx.org/).
- [OWASP — Server-Side Request Forgery](https://owasp.org/www-community/attacks/Server_Side_Request_Forgery).

### Exercises

1. `curl -v https://example.com` and annotate every line.
2. Find a site that serves different HTML to `curl` than to a browser, and
   work out why.
3. Read a restaurant site's `robots.txt` and `sitemap.xml`; extract any JSON-LD
   (`<script type="application/ld+json">`) from one of its pages.

### In this repo

[`apps/discovery/web_client.py`](./apps/discovery/web_client.py) is the
polite fetcher: robots.txt via `protego`, manual same-site redirects, per-host
rate limiting, public-address checks, size caps and a disk cache. The pure
candidate logic (homepage links, sitemaps) is in
[`apps/discovery/menu_url.py`](./apps/discovery/menu_url.py). The decision is
[ADR-0010](./docs/adr/0010-website-and-menu-url-resolution.md).

### Self-check

- [ ] I can explain the difference between 301 and 302 and why it matters to a
      fetcher.
- [ ] I know what `robots.txt` protects and what it doesn't.
- [ ] I can find JSON-LD on a modern site.
- [ ] I know why `curl` often sees different HTML than Chrome.
- [ ] I can explain why the fetcher checks every redirect hop's address.

---

## M8 — Scraping & Menu Extraction

**Why it matters.** The hard part of Phase 5 turned out to be *reading* menu
pages, not crawling them. Owner decision G.b replaced ROADMAP's
Scrapy-vs-Crawlee framework question with the spike's pipeline — page
classifier, LLM extraction, validator — written up as
[ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md). You need to be
able to judge that pipeline's quality claims.

### Core concepts

- Static vs JS-rendered pages; when a headless browser is needed.
- Headless browser basics: pages, waits, selectors.
- Structured data first: schema.org `Menu` in JSON-LD, and why it's rare.
- Page classification: telling a menu page from everything else.
- LLM extraction: prompts, output repair, and validating what comes back.
- Measuring quality: item recall, price accuracy, false rejects, held-out sets.
- One universal process vs per-site parsers (the owner chose universal).
- Ethics and law: terms of service, CFAA basics, rate limits as politeness.

### Resources

- [Playwright for Python](https://playwright.dev/python/docs/intro).
- [schema.org — Menu](https://schema.org/Menu).
- [scikit-learn — precision, recall and F-measures](https://scikit-learn.org/stable/modules/model_evaluation.html#precision-recall-f-measure-metrics).
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — running a local model on CPU.
- [EFF — CFAA](https://www.eff.org/issues/cfaa).

### Exercises

1. Fetch the same page with `httpx` and with Playwright; compare the HTML and
   the time taken.
2. Label twenty pages as menu / not menu, then measure a simple keyword
   heuristic's precision and recall against your labels.
3. Ask a local or hosted LLM to extract items and prices from one menu page as
   JSON. Write a validator that rejects rows whose price does not appear in
   the page text.

### In this repo

Partly built: segmentation
([`packages/helios_parsing/segment.py`](./packages/helios_parsing/segment.py)),
the page classifier
([`apps/menu_pipeline/classifier.py`](./apps/menu_pipeline/classifier.py)) and
the renderer; LLM extraction and the validator are not built yet. Read
[ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md)
and the [menu-model spike](./docs/spikes/menu-model/README.md) for the numbers
behind it. The Menu domain it writes into already exists
([`packages/helios_core/domains/menu/`](./packages/helios_core/domains/menu/),
[ADR-0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md)).

### Self-check

- [ ] I know when a headless browser is needed and when `httpx` is enough.
- [ ] I can explain why the pipeline has a validator after the LLM.
- [ ] I can read ADR-0013's quality table and say what each bar protects
      against.
- [ ] I understand what the CFAA says about scraping public data.

---

## M9 — Data Engineering Patterns

**Why it matters.** V1 got duplicate rows, lost rows and pipelines that were
impossible to debug. V2 treats every write as re-runnable and keeps
source-faithful records so any result can be traced and rebuilt.

### Core concepts

- Idempotency: running twice equals running once. Stable keys + upsert.
- Delivery semantics: at-most-once, at-least-once, exactly-once.
- Lifecycle layers: source-faithful raw records, validated interpretations,
  rebuildable consumer projections.
- Immutable, append-only records vs in-place correction.
- Lineage: which source produced this row, when, with which code version.
- Watermarks, change detection and incremental processing.
- Dead-letter handling for rows that fail validation.
- Replay vs backfill.

### Resources

- [$] *Designing Data-Intensive Applications*, chapters 10–12.
- [Jay Kreps — The Log](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying).
- [dbt — How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview).
- [PostgreSQL — INSERT … ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT).

### Exercises

1. Build `source.jsonl` → raw table → derived view. Run it twice; confirm no
   duplicates.
2. Route bad rows to a dead-letter table with a reason code.
3. Delete the derived table and rebuild it from the raw table.

### In this repo

[ADR-0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md)
defines the layers as Bronze (source-faithful, immutable), Silver (validated
identity and domain data) and Gold (rebuildable projections); it supersedes the
earlier raw/canonical/mart plan in ADR-0003. Worked examples:
[`apps/discovery/pipeline.py`](./apps/discovery/pipeline.py) (idempotent
discovery keyed on stable Overture IDs, [ADR-0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md)),
[`packages/helios_core/provenance/`](./packages/helios_core/provenance/)
(Bronze), and [`packages/helios_core/gold/refresh.py`](./packages/helios_core/gold/refresh.py)
with its idempotency and full-rebuild tests in
[`test/test_gold_refresh.py`](./test/test_gold_refresh.py)
([ADR-0006](./docs/adr/0006-gold-menu-read-models.md)).

### Self-check

- [ ] I can explain why idempotency matters and how a stable key provides it.
- [ ] I know the three delivery semantics.
- [ ] I can say what belongs in Bronze, Silver and Gold, and which may be
      dropped and rebuilt.
- [ ] I can design a pipeline that survives a crash mid-run.

---

## M10 — Geospatial

**Why it matters.** Discovery places every venue on a map, dedupes nearby
duplicates and fills coordinate gaps by geocoding. Getting coordinates and
distances right decides whether two records are the same restaurant.

### Core concepts

- Latitude/longitude: units, precision, axis-order pitfalls.
- Geocoding vs reverse geocoding.
- Nominatim usage policy: one request per second, a real User-Agent, caching.
- Great-circle (haversine) distance and radius queries.
- Bounding boxes vs radius vs polygon containment.
- Spatial indexes and grids (PostGIS, H3, geohash) — and when plain lat/lon is
  enough.
- Address normalization: when two strings mean the same place.

### Resources

- [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/) (required reading) and [Nominatim docs](https://nominatim.org/release-docs/latest/).
- [Movable Type — Calculate distance between lat/long points](https://www.movable-type.co.uk/scripts/latlong.html).
- [PostGIS intro workshop](https://postgis.net/workshops/postgis-intro/).
- [Overture Maps docs](https://docs.overturemaps.org/).

### Exercises

1. Geocode a handful of Austin addresses through Nominatim at one request per
   second, caching every answer (including misses).
2. Write a haversine function and a "within N metres" check; test it against
   known distances.
3. Find an address Nominatim gets wrong and work out why.

### In this repo

[ADR-0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md)
chose **lat/lon only, no H3**. Read
[`packages/helios_core/geo.py`](./packages/helios_core/geo.py) (cached,
rate-limited Nominatim fallback),
[`packages/helios_core/identity/normalize.py`](./packages/helios_core/identity/normalize.py)
(`haversine_m`, name and address normalization) and
[`apps/discovery/overture.py`](./apps/discovery/overture.py). Coordinate
corrections are the subject of
[Proposed ADR-0014](./docs/adr/0014-location-overrides.md).

### Self-check

- [ ] I know why lat/lon is y/x on maps but x/y in code.
- [ ] I can describe Nominatim's rate-limit rules from memory.
- [ ] I can explain why Helios dropped H3 and what it uses instead.
- [ ] I know when to use a bounding box vs a radius query.

---

## M11 — API Design

**Why it matters.** V1's API was an afterthought: every route a new naming
scheme, every error a new shape. In V2 the API is the product — one resource
style, one error envelope, one pagination protocol.

### Core concepts

- REST vs RPC vs GraphQL.
- Resource-oriented URLs; verbs and idempotency.
- Pagination: offset vs cursor, and why cursor holds up at scale.
- One consistent error shape.
- Versioning (`/v1/`).
- OpenAPI as a contract, not just docs.
- Pydantic v2 models and validators.
- CORS — the actual rules.
- Rate limiting: token bucket vs leaky bucket vs fixed window.

### Resources

- [FastAPI docs](https://fastapi.tiangolo.com/) — tutorial through the Advanced User Guide.
- [Pydantic v2 docs](https://docs.pydantic.dev/latest/).
- [Microsoft REST API Guidelines](https://github.com/microsoft/api-guidelines/blob/vNext/Guidelines.md) and [Google AIPs](https://google.aip.dev/).
- [Slack — Evolving API pagination](https://slack.engineering/evolving-api-pagination-at-slack/).
- [OWASP API Security Top 10](https://owasp.org/API-Security/editions/2023/en/0x00-header/).

### Exercises

1. Build `GET /items` with offset pagination over 10k rows; measure page 100
   vs page 1. Switch to a cursor and measure again.
2. Add an exception handler so every error returns the same JSON shape.
3. Commit the generated OpenAPI schema and add a test that fails when it
   changes.

### In this repo

[ADR-0008](./docs/adr/0008-read-api-conventions.md) sets the conventions.
Code: [`apps/api/main.py`](./apps/api/main.py) (routes under `/v1`,
unversioned `/healthz` and `/readyz`),
[`apps/api/routes/venues.py`](./apps/api/routes/venues.py),
[`apps/api/pagination.py`](./apps/api/pagination.py) (opaque cursor),
[`apps/api/errors.py`](./apps/api/errors.py) and
[`apps/api/schemas.py`](./apps/api/schemas.py) (`{detail, code, trace_id}`),
and [`test/test_openapi_contract.py`](./test/test_openapi_contract.py), which
compares the app against [`apps/api/openapi_snapshot.json`](./apps/api/openapi_snapshot.json).

### Self-check

- [ ] I can explain the difference between REST and RPC.
- [ ] I know why cursor pagination beats offset at scale.
- [ ] I can design an error shape a frontend can reliably parse.
- [ ] I know what CORS does and doesn't enforce.
- [ ] I know the OWASP API Top 10 well enough to spot a violation in a PR.

---

## M12 — Operations

**Why it matters.** V1 ran on one Orange Pi with no monitoring and no backups.
V2 runs the same container image in dev and on the staging Pi, and needs
logs, backups and runbooks before it goes to prod.

### Core concepts

- The twelve-factor app.
- Docker: images vs containers, layers, multi-stage builds, compose for dev.
- systemd units and timers.
- Environment promotion: same image, different config.
- Structured logging — JSON in prod, human-readable in dev.
- Liveness vs readiness probes.
- Metrics: counters, gauges, histograms.
- Backup and restore: a backup you haven't restored isn't a backup.
- Runbooks.

### Resources

- [The Twelve-Factor App](https://12factor.net/).
- [Docker — Building best practices](https://docs.docker.com/build/building/best-practices/).
- [structlog docs](https://www.structlog.org/en/stable/).
- [Prometheus — Metric naming](https://prometheus.io/docs/practices/naming/).
- [Google SRE Book](https://sre.google/sre-book/table-of-contents/) — chapters 3, 4, 5, 11, 15.
- [$] *Docker Deep Dive* (Nigel Poulton).

### Exercises

1. Dockerize a small FastAPI app with a multi-stage build; compare the image
   size to a single-stage build.
2. Write a `docker-compose.yml` with Postgres and the API.
3. Write a five-step runbook for "Postgres disk is full", then run a
   backup/restore drill and time it.

### In this repo

[ADR-0002](./docs/adr/0002-containerization.md) (containerization, pulled
forward from Phase 8), [`infra/Dockerfile`](./infra/Dockerfile) (multi-stage),
[`infra/docker-compose.yml`](./infra/docker-compose.yml), the `make dev` /
`make migrate` targets in the [`makefile`](./makefile), and
[`apps/api/observability.py`](./apps/api/observability.py) (structlog and
request ids). Environments are described in
[ROADMAP.md §4.2](./ROADMAP.md#42-environments-dev--staging--prod). Prod
hosting is not decided yet; it will get an ADR (next free number).

### Self-check

- [ ] I can explain the twelve-factor rules.
- [ ] I know the difference between a Docker image and a container.
- [ ] I can explain liveness vs readiness and why `/readyz` needs the database.
- [ ] I know which metric type fits a given observable.
- [ ] I have run a backup/restore drill.

---

## How to study alongside a day job

- **One module at a time.** Don't leapfrog.
- **Timebox.** 1–2 hours, three evenings a week, beats a weekend sprint.
- **Keep a learning journal** in your scratchpad repo: one dated entry per
  session — what you read, tried, and what surprised you.
- **Pair with an AI assistant like a senior dev.** Ask why, not what.
- **Use the self-check as your syllabus.** A question you can't answer is your
  next topic.

---

*Update this guide via PR when a resource goes stale or the code it points at
moves.*
