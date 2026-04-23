# Helios V2 — Learning Guide

> **Purpose.** A twelve-module course that takes you from "knows basics, shipped a hacky V1" to "can build Helios V2 with the rigor of a paid engineer." Each module ends in a **capstone PR** against this repository — study becomes commits, and commits advance the [Roadmap](./ROADMAP.md).
>
> **How to use this guide.**
>
> 1. Work the modules in order — later modules assume earlier ones.
> 2. Give each module 1–2 weeks part-time; don't rush.
> 3. For every module: read the "Why", hit the curated resources, do the exercises in a **scratchpad repo**, then ship the capstone as a PR here.
> 4. Before moving on, answer the self-check rubric from memory. If you can't, you haven't learned it — re-read or ask.
>
> **Free-first rule.** Every module's primary resources are free. Paid resources are listed as *optional deep dives* when the free ones don't cover the topic well.

---

## How to Read Each Module

- **Why it matters** — one paragraph tying the module to a V2 phase.
- **Prerequisites** — what you should already know (modules or topics).
- **Core concepts** — the 5–10 ideas you must internalize.
- **Curated resources** — free first, paid marked `[$]`.
- **Exercises** — in a throwaway `helios-learning` scratchpad repo.
- **Capstone PR** — a real change in `helios-v2` that exercises the skill.
- **Self-check rubric** — questions you should answer from memory before moving on.

---

## Table of Contents

- [M1 — Modern Python Project Hygiene](#m1--modern-python-project-hygiene)
- [M2 — Git & Team Workflow](#m2--git--team-workflow)
- [M3 — Design Docs (ADRs and RFCs)](#m3--design-docs-adrs-and-rfcs)
- [M4 — Testing Pyramid](#m4--testing-pyramid)
- [M5 — Relational Modeling](#m5--relational-modeling)
- [M6 — SQLAlchemy 2.0 & Alembic](#m6--sqlalchemy-20--alembic)
- [M7 — HTTP, HTML & the Real Web](#m7--http-html--the-real-web)
- [M8 — Scraping Fundamentals](#m8--scraping-fundamentals)
- [M9 — Data Engineering Patterns](#m9--data-engineering-patterns)
- [M10 — Geospatial](#m10--geospatial)
- [M11 — API Design](#m11--api-design)
- [M12 — Operations](#m12--operations)
- [Appendix: Recommended Reading Order by Phase](#appendix-recommended-reading-order-by-phase)

---

## M1 — Modern Python Project Hygiene

**Why it matters.** Every V1 problem starts with "the project grew without a structure." A clean `pyproject.toml`, a lockfile, a linter, and a type checker are the difference between "hacking" and "engineering." This module is what you do before you write any V2 feature code.

**Maps to:** Roadmap Phase 0.

**Prerequisites:** Python 3.10+ familiarity. Can write a class and a function. Have used `pip` before.

### Core concepts

- Virtual environments — why isolation matters.
- `pyproject.toml` (PEP 621) as the single source of truth for project metadata + deps.
- Lockfiles (`uv.lock`, `poetry.lock`, `requirements.txt` pinned) — reproducibility.
- The difference between runtime, dev, and test dependencies.
- Linters vs formatters vs type checkers vs tests — four distinct jobs.
- `ruff` as the modern linter+formatter replacement for flake8/black/isort.
- `mypy --strict`: what "strict" actually changes.
- Pre-commit hooks — catching mistakes before they reach CI.

### Curated resources

- **Read first:** [PEP 621 — Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/).
- **uv docs:** https://docs.astral.sh/uv/ (skim Getting Started → Projects).
- **ruff docs:** https://docs.astral.sh/ruff/ — read the "Rules" overview.
- **mypy — Getting started:** https://mypy.readthedocs.io/en/stable/getting_started.html.
- **Type hints cheat sheet:** https://mypy.readthedocs.io/en/stable/cheat_sheet_py3.html.
- **pre-commit:** https://pre-commit.com/ — quickstart page is enough.
- [$] **Fluent Python, 2nd ed. (Luciano Ramalho)** — chapters 1, 8, 15. The definitive "thinking in modern Python" book.

### Exercises (scratchpad repo)

1. Create a new repo `helios-learning`. Inside, create `exercises/m1/`.
2. Write a `pyproject.toml` from scratch for a tiny "calculator" library. Runtime dep: nothing. Dev deps: `ruff`, `mypy`, `pytest`.
3. Install with `uv sync`. Verify the lockfile is committed.
4. Write a `calculator.py` with three untyped functions. Run `mypy --strict` — fix every error.
5. Write one that uses `list` vs `list[int]` vs `Sequence[int]` — understand the difference.
6. Install `pre-commit` and wire ruff + mypy into `.pre-commit-config.yaml`. Commit a file with a lint error; confirm pre-commit blocks it.
7. Configure `ruff.toml` to enforce line length 100 and sort imports. Break both rules; confirm `ruff check --fix` repairs them.

### Capstone PR (`helios-v2`)

**Title:** `chore: bootstrap Python tooling and CI`

**What:** Create `pyproject.toml`, `uv.lock`, `ruff.toml`, `mypy.ini`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `Makefile` targets (`install`, `lint`, `test`). The repo should have zero application code but green CI.

**Done when:** merging this PR enables every subsequent PR to run through the same gates automatically.

### Self-check rubric

- [ ] I can explain the difference between `requirements.txt` and a lockfile without looking it up.
- [ ] I can write a minimal `pyproject.toml` from memory (name, version, deps, optional deps).
- [ ] I know what `ruff` does that `black` doesn't.
- [ ] I can describe what `mypy --strict` enforces that default `mypy` doesn't.
- [ ] I understand why pre-commit runs in `.git/hooks/` and not CI alone.
- [ ] I can install dependencies from a lockfile on a fresh machine in one command.

---

## M2 — Git & Team Workflow

**Why it matters.** V1 had ~15 months of commits on `main`. V2 will have zero. Every change lands via PR. This module turns you from "someone who uses git" into "someone who collaborates with git" — even on a solo project.

**Maps to:** Roadmap Phase 0 + all subsequent phases (every merge).

**Prerequisites:** can `git add / commit / push`. Has opened a pull request before.

### Core concepts

- The object model: commits, trees, blobs, refs. *(Watch the YT video below — this is the "aha" moment.)*
- Branches are just labels on commits.
- Rebase vs merge — what happens to history in each.
- Interactive rebase (`git rebase -i`) — editing, squashing, reordering.
- `git reflog` — your safety net.
- [Conventional Commits](https://www.conventionalcommits.org/) — machine-readable commit messages.
- PR anatomy: title, description, reviewers, checks, suggestions.
- Branch protection: required checks, required reviews, signed commits.
- CODEOWNERS — auto-assign reviewers.

### Curated resources

- **Pro Git book (free):** https://git-scm.com/book — read chapters 2, 3, 7.1–7.3, and 5 (workflows).
- **Watch (free):** "Git Internals" — https://www.youtube.com/watch?v=P6jD966jzlk (40 min; the object model lands for good).
- **Conventional Commits spec:** https://www.conventionalcommits.org/en/v1.0.0/.
- **GitHub Docs — About branch protection:** https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches.
- **Atlassian — Merging vs Rebasing:** https://www.atlassian.com/git/tutorials/merging-vs-rebasing.
- **Graphite blog (free):** https://graphite.dev/blog — great short pieces on stacked PRs.

### Exercises

1. In a scratchpad repo, make 3 commits on a feature branch, then rebase interactively to squash them into 1 with a conventional-commit message.
2. Cause a conflict: create two branches touching the same line, rebase one onto the other, resolve, continue.
3. Delete a commit by mistake with `git reset --hard`, then recover it via `git reflog`.
4. Open a PR on your scratchpad repo. Enable branch protection on `main`. Try to push directly — confirm GitHub refuses.
5. Install `commitlint` as a pre-commit hook. Write a commit message that violates conventional-commit format; confirm the hook rejects it.

### Capstone PR (`helios-v2`)

**Title:** `chore: add PR template, issue templates, CODEOWNERS`

**What:** `.github/pull_request_template.md` (What / Why / How tested / Risk / Rollback), `.github/ISSUE_TEMPLATE/bug.md`, `.github/ISSUE_TEMPLATE/feature.md`, `.github/CODEOWNERS` (assign yourself to `/` as sole owner). Enable branch protection on `main`.

**Done when:** the next PR you open auto-populates the template and auto-requests you as reviewer.

### Self-check rubric

- [ ] I can explain what happens in git when I run `git commit` — in terms of objects, not UI.
- [ ] I know when to rebase vs merge and why.
- [ ] I can recover a commit I "lost" via `git reset --hard`.
- [ ] I can write a conventional-commit message without looking up the format.
- [ ] I can configure branch protection rules from memory.
- [ ] I know what a squash-merge actually does to history vs a merge-commit.

---

## M3 — Design Docs (ADRs and RFCs)

**Why it matters.** V1 had no record of *why* decisions were made — so every decision was up for re-debate forever. V2 writes it down. ADRs and RFCs are the industry standard for "we considered X, Y, Z and picked Y because Q."

**Maps to:** Roadmap Phase 0 (ADR-0001, ADR-0002). Every later phase spawns more.

**Prerequisites:** M2 (you'll be opening PRs with these docs).

### Core concepts

- ADR = **Architecture Decision Record**. Short (1 page). Captures a single decision.
- RFC = **Request for Comments**. Long (multiple pages). Proposes a change, lists alternatives, invites review before implementation.
- Statuses: `proposed`, `accepted`, `deprecated`, `superseded-by #NN`.
- Immutability: once accepted, an ADR is never edited; supersede it with a new one.
- Decision hygiene: context → decision → consequences → alternatives considered.
- When NOT to write an ADR: trivial or reversible choices.

### Curated resources

- **Michael Nygard's original ADR post (free):** https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions.
- **ADR GitHub org (templates + examples):** https://adr.github.io/.
- **Spotify's engineering culture on RFCs (free):** https://engineering.atspotify.com/2020/04/when-should-i-write-an-architecture-decision-record/.
- **Oxide Computer RFC Process (free, excellent real-world example):** https://oxide.computer/blog/rfd-1-requests-for-discussion.
- **[$] optional:** "Technical Writing for Engineers" (Google free course): https://developers.google.com/tech-writing — short but very good.

### Exercises

1. Read 5 real ADRs from https://github.com/joelparkerhenderson/architecture-decision-record/tree/main/examples — pick any 5.
2. Write an ADR for a decision you've already made in any project: "Why I use VS Code" is fine. Force yourself to fill the Alternatives section honestly.
3. Write an RFC proposing *one* change to a project you use (not yours) — practice the long form.
4. Re-read your first ADR a week later. Would you still understand it? Edit it until the answer is yes.

### Capstone PR (`helios-v2`)

**Title:** `docs: add ADR + RFC templates and ADR-0001 stack choice`

**What:** `docs/adr/0000-template.md`, `docs/rfc/0000-template.md`, `docs/adr/0001-stack-choice.md` (ratifies the [Roadmap](./ROADMAP.md) stack picks: Postgres + SQLAlchemy 2.0 + FastAPI + Python 3.12 + uv). The Alternatives section lists Node/Go/Rust and why they were not chosen.

**Done when:** ADR-0001 is merged and any future "why Python?" question is answered by a link.

### Self-check rubric

- [ ] I can explain the difference between an ADR and an RFC.
- [ ] I know when a decision deserves an ADR and when it doesn't.
- [ ] I can write an ADR in under 30 minutes.
- [ ] I understand why ADRs are immutable after acceptance.
- [ ] I know what the "Consequences" section is really for (not re-stating the decision).

---

## M4 — Testing Pyramid

**Why it matters.** V1's parsing code was "tested by running it on real scrapes and squinting." V2's parsing code will have property-based tests, golden files, and ≥ 90% coverage. You need the vocabulary and the muscle memory to make that easy.

**Maps to:** Roadmap Phase 2 (parsing library).

**Prerequisites:** M1 (pytest is installed in your dev deps).

### Core concepts

- The testing pyramid: many unit, some integration, few end-to-end.
- pytest fixtures: scope (function/module/session), finalizers, factories.
- `parametrize` — data-driven tests without duplication.
- Golden files — "this input should produce exactly this output, forever."
- Property-based testing with **Hypothesis** — generators find bugs you didn't think to write a test for.
- Test doubles: stubs, mocks, fakes, spies — what each is for.
- Coverage vs quality: 100% coverage of trivial code means nothing.
- Flaky tests — why they exist, how to fix them (not retry them).

### Curated resources

- **pytest docs:** https://docs.pytest.org/en/stable/ — getting started + fixtures + parametrize.
- **Hypothesis quickstart:** https://hypothesis.readthedocs.io/en/latest/quickstart.html.
- **Hypothesis "What you can generate and how":** https://hypothesis.readthedocs.io/en/latest/data.html.
- **Martin Fowler — TestDouble:** https://martinfowler.com/bliki/TestDouble.html — 10-minute read, settles the stub/mock/fake confusion forever.
- **Obey the Testing Goat (free book):** https://www.obeythetestinggoat.com/ — test-driven development worked example.
- **pytest-cov:** https://pytest-cov.readthedocs.io/en/latest/.

### Exercises

1. Write a `add(a, b)` function. Add 3 parametrized tests for happy path, zeros, and negatives.
2. Convert those tests to a single Hypothesis property test: `add(a, b) == add(b, a)` for any integers.
3. Write a `parse_date("YYYY-MM-DD")` function. Add a property test: `parse_date(format_date(d)) == d` for any date.
4. Write a golden-file test for a function that renders a dict to YAML — compare against a checked-in `.yaml` file.
5. Deliberately write a flaky test (one using `time.time()`) and fix it with a fixture + `monkeypatch`.

### Capstone PR (`helios-v2`)

**Title:** `feat(parsing): port sub_deals decomposition with Hypothesis tests`

**What:** Port [`collectors/meal_deals/sub_deals.py`](https://github.com/4Fortune8/First-Helios/blob/V1-Graveyard/collectors/meal_deals/sub_deals.py) from `V1-Graveyard` to `packages/parsing/sub_deals.py`. Add: 50 parametrized golden cases, 3 Hypothesis property tests, ≥ 90% coverage, zero I/O in the module.

**Done when:** coverage report shows ≥ 90% for `packages/parsing/sub_deals.py` with meaningful assertions.

### Self-check rubric

- [ ] I can explain why the testing pyramid is shaped that way.
- [ ] I know the difference between a mock and a fake.
- [ ] I can write a Hypothesis property test from scratch.
- [ ] I know when a test is flaky because of code and when because of test setup.
- [ ] I can read a coverage report and say which uncovered lines actually matter.

---

## M5 — Relational Modeling

**Why it matters.** V1's schema was ported from a spreadsheet mindset — wide tables, repeated groups, ad-hoc JSONB for anything awkward. V2's schema is the backbone of the entire system. If you get this wrong, every later phase is painful. Get it right and the code almost writes itself.

**Maps to:** Roadmap Phase 1.

**Prerequisites:** can write a `SELECT ... JOIN ... WHERE` statement.

### Core concepts

- Normal forms 1NF, 2NF, 3NF — what each prevents and when to break them on purpose.
- Primary keys vs unique constraints.
- Foreign keys: cascade, restrict, set null.
- Indexes: B-tree, hash, partial, composite, expression, GIN for JSONB.
- Transaction isolation levels: read committed, repeatable read, serializable.
- When to use JSONB and when not to.
- Denormalization as a deliberate choice, not an accident.
- Migration safety: adding a column ≠ adding a NOT NULL column ≠ adding a NOT NULL with a default on a billion-row table.

### Curated resources

- **PostgreSQL documentation — Chapter 5 (Data Definition):** https://www.postgresql.org/docs/current/ddl.html. The primary source of truth.
- **Use The Index, Luke (free book):** https://use-the-index-luke.com/ — how indexes actually work.
- **PostgreSQL query planner intro:** https://www.postgresql.org/docs/current/using-explain.html.
- **Markus Winand — "SQL Performance Explained" (free sample chapters):** https://sql-performance-explained.com/.
- **[$] SQL Antipatterns (Bill Karwin)** — the definitive "here's 25 ways to shoot yourself in the foot" book. Worth every dollar.
- **[$] Designing Data-Intensive Applications (Martin Kleppmann), chs 2, 7** — the gold standard.

### Exercises

1. Install Postgres locally via docker-compose. Create a `bookstore` DB with `authors`, `books`, `author_books` (many-to-many).
2. Insert 10 authors, 50 books, 80 author-book links.
3. Write the query "all books by authors with ≥ 5 books." Run `EXPLAIN ANALYZE`. Add an index. Re-run. Note the difference.
4. Try to insert a duplicate `author_books` row. Observe the constraint error.
5. Make the bookstore 3NF. Then denormalize `books` to include `primary_author_name` as a cached column. Write a trigger that keeps it in sync. (You won't use triggers in V2, but doing it once teaches you why.)

### Capstone PR (`helios-v2`)

**Title:** `feat(core): canonical schema for deal observations and venues`

**What:** Using SQLAlchemy 2.0, define `DealObservation`, `DealApplicability`, `DealMaterialization`, `Venue`, `VenueAlias`, `SiteIdentity`. Alembic migration `0001_canonical_schema.py`. Constraint tests for every unique index, `CHECK`, and FK cascade rule.

**Done when:** `alembic upgrade head` on an empty DB produces the schema; `pytest packages/core/tests/` passes with ≥ 20 constraint tests.

### Self-check rubric

- [ ] I can explain 1NF, 2NF, 3NF without looking them up.
- [ ] I know why you want a foreign key even if your app "handles it."
- [ ] I can read `EXPLAIN ANALYZE` and spot a missing index.
- [ ] I know when JSONB is the right call and when it's a cop-out.
- [ ] I can describe a migration that would lock a large table and how to avoid it.

---

## M6 — SQLAlchemy 2.0 & Alembic

**Why it matters.** V1 used SQLAlchemy 1.4 in "legacy" style with untyped `Column(...)`. V2 uses 2.0 style with `Mapped[str]` and `mapped_column()` — mypy catches schema drift at type-check time. Alembic autogenerate saves hours of hand-writing migrations, but only if you understand what it produces.

**Maps to:** Roadmap Phase 1, Phase 6.

**Prerequisites:** M5 (know relational modeling), M1 (typing + mypy).

### Core concepts

- Declarative base with typed `Mapped[T]`.
- `mapped_column(...)`, `relationship(...)`.
- Session lifecycle: `begin()`, `commit()`, `rollback()`, `close()`.
- `Session` vs `scoped_session` vs async session.
- Eager vs lazy loading (`selectinload`, `joinedload`, `lazy="raise"`).
- Alembic autogenerate — what it catches, what it misses (enum renames, column type changes).
- Reviewing migrations by hand.
- Zero-downtime migrations: expand → migrate → contract.

### Curated resources

- **SQLAlchemy 2.0 — Unified Tutorial:** https://docs.sqlalchemy.org/en/20/tutorial/index.html. Read all of it.
- **SQLAlchemy 2.0 migration guide (free):** https://docs.sqlalchemy.org/en/20/changelog/migration_20.html.
- **Alembic tutorial:** https://alembic.sqlalchemy.org/en/latest/tutorial.html.
- **Mike Bayer on async SQLAlchemy (free talks):** search YouTube for "mike bayer sqlalchemy async."
- **Migra (free diffing tool):** https://github.com/djrobstep/migra — optional but eye-opening.

### Exercises

1. Rewrite your bookstore schema from M5 in SQLAlchemy 2.0 declarative style with full type hints.
2. Set up Alembic, generate the initial migration, apply it to an empty DB.
3. Add a column to a model. Run `alembic revision --autogenerate`. Review the generated migration — what did it catch? What would it have missed (e.g., if you also renamed a column)?
4. Write a manual migration that renames a column with zero downtime (add new → backfill → drop old — three PRs).
5. Break autogenerate on purpose: rename a table at the model level without updating the migration. Watch the DB diverge.

### Capstone PR (`helios-v2`)

**Title:** `feat(core): session management and repository pattern`

**What:** `packages/core/db.py` with a session factory, context manager, and a `BaseRepository` class. Unit tests for commit/rollback on exception. Document the session lifecycle in `docs/adr/0002-session-lifecycle.md`.

**Done when:** any package can import `from helios_core.db import session_scope` and get a correctly-bounded session.

### Self-check rubric

- [ ] I can explain the difference between SQLAlchemy Core and ORM.
- [ ] I know what `selectinload` does vs `joinedload`.
- [ ] I can describe the session lifecycle including what happens on an exception.
- [ ] I know what Alembic autogenerate misses.
- [ ] I can describe a zero-downtime migration in 3 steps.

---

## M7 — HTTP, HTML & the Real Web

**Why it matters.** Scraping is just HTTP + HTML parsing with good manners. V1's scrapers failed because they didn't understand what the network was actually doing — cookies, redirects, cache headers, `robots.txt`. This module is the foundation under Module 8.

**Maps to:** Roadmap Phase 4.

**Prerequisites:** can open Chrome DevTools.

### Core concepts

- HTTP verbs, status codes (be able to explain 301 vs 302 vs 307, 401 vs 403).
- Headers that matter: `User-Agent`, `Accept`, `Accept-Encoding`, `Cache-Control`, `Cookie`, `Referer`.
- Redirect chains.
- TLS + SNI at a working level (enough to debug `SSLError`).
- DNS: A, AAAA, CNAME, TTL; what happens when you type a URL.
- `robots.txt` — what it is, what it isn't (not a security mechanism).
- Sitemaps (`sitemap.xml`) — often better than crawling.
- HTML structure: DOM, CSS selectors, XPath.
- JSON-LD and microdata — structured data hiding in plain sight.
- The gap between what the browser sees and what `curl` sees (JS-rendered pages).

### Curated resources

- **MDN — HTTP Overview:** https://developer.mozilla.org/en-US/docs/Web/HTTP/Overview.
- **MDN — HTTP Headers reference:** https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers.
- **MDN — Status codes:** https://developer.mozilla.org/en-US/docs/Web/HTTP/Status.
- **High Performance Browser Networking (free book):** https://hpbn.co/ — read chapters 9, 10, 11.
- **Google — Robots.txt Specification:** https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt.
- **httpx docs:** https://www.python-httpx.org/.
- **selectolax docs:** https://selectolax.readthedocs.io/en/latest/.

### Exercises

1. `curl -v https://example.com` — annotate every line of output.
2. Find three real-world sites: one that works on `curl`, one that returns different HTML to `curl` vs Chrome, one that blocks `curl` entirely. Figure out why.
3. Parse the Wikipedia homepage with `selectolax`. Extract every `<h2>` text.
4. Fetch `https://www.mcdonalds.com/robots.txt` and `https://www.mcdonalds.com/sitemap.xml`. Summarize what they say.
5. Extract JSON-LD from any restaurant site (look for `<script type="application/ld+json">`).

### Capstone PR (`helios-v2`)

**Title:** `feat(scraper): rate-limited HTTP client with replay bundling`

**What:** `apps/scraper/http.py` — a `FetchClient` wrapping `httpx.Client` with per-host token-bucket rate limiting, gzip, sane defaults for User-Agent, and a hook that writes every response to `var/replay/<host>/<date>/<url-hash>.json`.

**Done when:** scraping one page produces a well-formed bundle on disk and respects the configured rate limit (verified by a test).

### Self-check rubric

- [ ] I can explain what happens between typing a URL and the page rendering.
- [ ] I know the difference between 301 and 302 and why it matters for scrapers.
- [ ] I know what `robots.txt` protects and what it doesn't.
- [ ] I can find JSON-LD on any modern site.
- [ ] I know why `curl` often sees different HTML than Chrome.

---

## M8 — Scraping Fundamentals

**Why it matters.** V1 had 20 chains' worth of ad-hoc scraper code sharing almost nothing. V2 picks one framework after conscious evaluation. This is the module where that choice gets made.

**Maps to:** Roadmap Phase 5 — this module drives **ADR-0003**.

**Prerequisites:** M7 (HTTP), M4 (testing).

### Core concepts

- Static vs dynamic pages. When do you *need* a browser?
- Playwright fundamentals: contexts, pages, selectors, waits, network interception.
- Scrapy: spiders, middlewares, pipelines, feeds.
- Crawlee (Python): scope, adapter pattern, Playwright integration.
- Anti-bot landscape: fingerprinting, reCAPTCHA, Cloudflare, Akamai.
- Ethics + legality: CFAA basics, terms-of-service considerations, rate limits as politeness not just protection.
- Structured data extraction: JSON-LD, microdata, OpenGraph tags.
- PDF extraction (many menus are PDFs): `pdfminer.six`, `pypdfium2`.

### Curated resources

- **Playwright Python docs:** https://playwright.dev/python/docs/intro.
- **Scrapy tutorial:** https://docs.scrapy.org/en/latest/intro/tutorial.html.
- **Crawlee for Python:** https://crawlee.dev/python/docs/introduction.
- **Apify Academy (free):** https://docs.apify.com/academy — "Web Scraping for Beginners" is surprisingly good.
- **Kevin Sahin — "The Ultimate Guide to Web Scraping" (free-ish, blog):** https://scrapingant.com/blog.
- **EFF on CFAA + scraping (free):** https://www.eff.org/issues/computer-fraud-and-abuse-act-reform — know your rights.

### Exercises

1. Scrape the first page of HackerNews with `httpx` + `selectolax` — no framework.
2. Do the same with Scrapy — note what infrastructure Scrapy gave you for free.
3. Do the same with Playwright — note how much slower it is and why.
4. Do the same with Crawlee — compare ergonomics to Scrapy.
5. Benchmark all four: throughput (pages/minute), lines of code, output fidelity.
6. Write ADR-0003 draft based on #5.

### Capstone PR (`helios-v2`)

**Title:** `docs: ADR-0003 scraper framework choice`

**What:** `docs/adr/0003-scraper-framework.md` with actual benchmark numbers from your exercises. Implement the winning choice in `apps/scraper/chains/mcdonalds.py`.

**Done when:** ADR is merged and `helios scrape mcdonalds --once` uses the chosen framework end-to-end.

### Self-check rubric

- [ ] I know when I *must* use a headless browser vs when I can use httpx.
- [ ] I can explain what a Scrapy middleware does in my own words.
- [ ] I know what fingerprinting techniques bot-detection uses.
- [ ] I understand what the CFAA says about scraping public data.
- [ ] I can look at a new site and decide which strategy to use within 10 minutes.

---

## M9 — Data Engineering Patterns

**Why it matters.** V1 got duplicate rows, lost rows, and impossible-to-debug pipelines because it didn't treat data flow as a design problem. V2 treats every insert as potentially re-runnable and every failure as debuggable from replay.

**Maps to:** Roadmap Phase 6.

**Prerequisites:** M5 (schema), M6 (sessions), M7 (HTTP).

### Core concepts

- Idempotency: "running this twice does the same as running it once." The unit-constraint + upsert pattern.
- Delivery semantics: at-most-once, at-least-once, exactly-once. Why exactly-once is expensive.
- Raw → staging → mart layering. Why separating raw is non-negotiable.
- Watermarks and checkpoints for incremental processing.
- Dead-letter queues: what they're for, how to empty them.
- Lineage: "which source produced this row, at what time, via what version of the code?"
- Replay vs backfill — different words, same core idea, different use cases.
- Change Data Capture (CDC) — good to know of, not needed for V1.

### Curated resources

- **Martin Kleppmann — Designing Data-Intensive Applications chs 10, 11, 12 [$].** The most valuable 200 pages in data engineering.
- **Jay Kreps — The Log: What every software engineer should know (free, classic):** https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying.
- **Max Beauchemin — "The Rise of the Data Engineer" (free):** https://maximebeauchemin.medium.com/the-rise-of-the-data-engineer-91be18f1e603.
- **dbt docs — even if you don't use dbt, read "How we structure our dbt projects":** https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview.
- **PostgreSQL — INSERT ... ON CONFLICT:** https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT.

### Exercises

1. Build a tiny pipeline: `source.jsonl` → `raw.events` table → `canonical.events` view. Run it twice. Confirm zero duplicates.
2. Add a new column to `canonical.events`. Re-run without touching `raw.events`. Confirm the new column populates.
3. Introduce a bad row in `source.jsonl`. Add a dead-letter table. Route bad rows there with a reason code.
4. Build a backfill: delete `canonical.events`, re-derive it from `raw.events`.
5. Measure: how many rows/sec does each stage sustain?

### Capstone PR (`helios-v2`)

**Title:** `feat(ingest): idempotent pipeline with applicability fan-out`

**What:** `apps/scraper/ingest.py` with: upsert on `(source, source_observation_key)`, applicability fan-out for chain-wide deals, materialization refresh, dead-letter on quality-gate failure. CLI: `helios backfill --source=mcdonalds --from=2026-01-01`.

**Done when:** dropping the `canonical` schema and running `helios backfill --all` rebuilds it from replay bundles identically.

### Self-check rubric

- [ ] I can explain why idempotency matters in distributed systems.
- [ ] I know the three delivery semantics and can name a real system for each.
- [ ] I understand why raw → canonical → mart is three layers, not two.
- [ ] I can design a pipeline that survives a process crash mid-run.
- [ ] I know when CDC is needed and when simple polling is fine.

---

## M10 — Geospatial

**Why it matters.** V1 geocoded every restaurant. V2 needs to do it correctly, cached, with a proximity index that can answer "deals within 1 mile of this lat/lng" in under 10ms.

**Maps to:** Roadmap Phase 3.

**Prerequisites:** M5 (schema), M7 (HTTP).

### Core concepts

- Latitude / longitude — units, precision, common pitfalls.
- Geocoding (address → coords) vs reverse geocoding (coords → address).
- Nominatim usage policy — 1 req/sec, User-Agent, viewbox to bound search.
- Bounding boxes vs radius queries.
- H3 hexagonal grid — resolutions 0–15, why hexes beat squares for proximity.
- PostGIS: `GEOGRAPHY` vs `GEOMETRY`, SRID 4326, `ST_DWithin`, `ST_Distance`.
- Geohash (older than H3, still in the wild).
- Address normalization — when two strings refer to the same place.

### Curated resources

- **Nominatim Usage Policy (free, required reading):** https://operations.osmfoundation.org/policies/nominatim/.
- **Nominatim docs:** https://nominatim.org/release-docs/latest/.
- **Uber Engineering — H3 intro (free):** https://www.uber.com/blog/h3/.
- **H3 docs:** https://h3geo.org/docs/.
- **PostGIS manual — "Using PostGIS: Data Management" chapter:** https://postgis.net/workshops/postgis-intro/.
- **OpenCage — free geocoding comparison guide:** https://opencagedata.com/guides.

### Exercises

1. Install PostGIS on your local Postgres. Create a `places` table with a `GEOGRAPHY(POINT, 4326)` column.
2. Insert 100 real Austin coffee shops by address — geocode via Nominatim, respecting rate limits.
3. Write the query "coffee shops within 500m of a given lat/lng." Run `EXPLAIN ANALYZE`. Add a GIST index. Re-run.
4. Install the `h3-pg` extension. Compute H3 r9 cells for every point. Write the same proximity query via H3 — compare.
5. Find 3 addresses that Nominatim misgeocodes in Austin. Write the override dict for them.

### Capstone PR (`helios-v2`)

**Title:** `feat(core): Nominatim client with cache and H3 indexing`

**What:** `packages/core/geo.py` with token-bucket rate limiting, disk cache keyed by normalized query, manual overrides for known ambiguities, H3 r6–r9 computation on insert. Fixture-based integration tests (no live calls in CI).

**Done when:** geocoding 100 Overture addresses hits Nominatim ≤ 100 times (first run) and 0 times (second run, cached).

### Self-check rubric

- [ ] I know why lat/lng is ordered y/x on maps but x/y in math.
- [ ] I can explain why H3 hexagons beat geohash rectangles.
- [ ] I know the difference between `GEOGRAPHY` and `GEOMETRY` in PostGIS.
- [ ] I can describe Nominatim's rate-limit rules from memory.
- [ ] I know when to use a bounding-box filter vs a radius query.

---

## M11 — API Design

**Why it matters.** V1's API was an afterthought — every route a new naming scheme, every error a new shape. V2's API is the product; the scrapers are plumbing. One consistent shape, one consistent error format, one paginated protocol.

**Maps to:** Roadmap Phase 7.

**Prerequisites:** M1 (typing), M6 (sessions).

### Core concepts

- REST vs RPC vs GraphQL — what each is best at, when to mix.
- Resource-oriented URLs: `/deals/{id}` not `/getDeal?id=`.
- HTTP verbs as semantics: idempotent (GET/PUT/DELETE) vs not (POST).
- Pagination: offset/limit vs cursor. Why cursor wins at scale.
- Error shapes: one consistent structure with `detail`, `code`, `trace_id`.
- Versioning: URL (`/v1/`), header, or accept-type.
- OpenAPI as a contract, not just docs.
- Pydantic v2: `BaseModel`, `Field`, validators, `model_config`.
- CORS — the actual rules, not the usual hand-waving.
- Rate limiting — token bucket vs leaky bucket vs fixed window.

### Curated resources

- **MDN — HTTP methods:** https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods.
- **FastAPI docs:** https://fastapi.tiangolo.com/ — tutorial through "Advanced User Guide."
- **Pydantic v2 docs:** https://docs.pydantic.dev/latest/.
- **Microsoft — REST API Guidelines (free):** https://github.com/microsoft/api-guidelines/blob/vNext/Guidelines.md.
- **Google — AIP (API Improvement Proposals, free):** https://google.aip.dev/.
- **Cursor-based pagination (Slack engineering, free):** https://slack.engineering/evolving-api-pagination-at-slack/.
- **OWASP API Security Top 10:** https://owasp.org/API-Security/editions/2023/en/0x00-header/.

### Exercises

1. Write a FastAPI app with `GET /items` and `GET /items/{id}` using offset pagination. Load 10k rows. Measure p95 latency at page 100 vs page 1.
2. Switch to cursor pagination. Measure again. Notice the difference.
3. Add a uniform error middleware. Every exception → `{detail, code, trace_id}`.
4. Commit the generated `openapi.json`. Break the schema (rename a field). Add a CI check that diffs it and fails the build.
5. Write a Pydantic model with a custom validator (e.g., `valid_at` must be in the future).

### Capstone PR (`helios-v2`)

**Title:** `feat(api): /deals and /venues read endpoints with cursor pagination`

**What:** `apps/api/routes/deals.py`, `apps/api/routes/venues.py`, uniform error shape, cursor pagination, committed `openapi.json`, CI check diffing schema.

**Done when:** `curl /deals?h3=...&valid_at=now` returns a page with `next_cursor`, and breaking the schema intentionally fails CI.

### Self-check rubric

- [ ] I can explain the difference between REST and RPC.
- [ ] I know why cursor pagination beats offset at scale.
- [ ] I can design an error shape that frontends can reliably parse.
- [ ] I know what CORS actually does and doesn't enforce.
- [ ] I know the OWASP API Top 10 well enough to spot a violation in a PR.

---

## M12 — Operations

**Why it matters.** V1 ran on one Orange Pi with no monitoring and no backup. V2 runs on staging (OPi) + prod (hosted), with metrics, backups, and a runbook. This is the module that takes you from "it works on my machine" to "it works, and I know when it doesn't."

**Maps to:** Roadmap Phase 8.

**Prerequisites:** M1 (tooling), M6 (migrations), M11 (API).

### Core concepts

- The twelve-factor app: 12 rules, all of them real. https://12factor.net/.
- Docker basics: images, containers, layers, `CMD` vs `ENTRYPOINT`.
- Multi-stage builds — small prod images.
- docker-compose for local dev.
- systemd units + timers (instead of cron when you need logs, retries, dependencies).
- Environment promotion: dev → staging → prod. Same image, different config.
- Structured logging (`structlog`) — JSON in prod, human in dev.
- Prometheus metrics: counters, gauges, histograms. When to use each.
- Backup + restore: a backup you haven't restored is not a backup.
- Hosted options: Hetzner Cloud, Fly.io, Railway, DO, Render. When each is right.
- Runbooks — step-by-step instructions for "what do I do when X breaks."

### Curated resources

- **The Twelve-Factor App (free):** https://12factor.net/ — read all 12 chapters.
- **Docker — Best Practices:** https://docs.docker.com/build/building/best-practices/.
- **Julia Evans — systemd zine (free excerpts):** https://wizardzines.com/zines/bite-size-linux/.
- **Prometheus — Best practices for metrics:** https://prometheus.io/docs/practices/naming/.
- **structlog docs:** https://www.structlog.org/en/stable/.
- **SRE Book (free, Google):** https://sre.google/sre-book/table-of-contents/ — chapters 3, 4, 5, 11, 15 are the essentials.
- **Fly.io — deploy guides:** https://fly.io/docs/.
- **Hetzner Cloud docs:** https://docs.hetzner.com/cloud/.
- **[$] Docker Deep Dive (Nigel Poulton)** — skim, not essential but excellent.

### Exercises

1. Dockerize a small FastAPI app. Build a multi-stage image. Compare the size of the final image vs a naive single-stage build.
2. Write a `docker-compose.yml` with Postgres + your API + a cron-scheduler sidecar.
3. Deploy the image to Fly.io free tier. Measure cold start.
4. Deploy the same image to a Hetzner CAX11 with systemd. Compare.
5. Write a runbook for "Postgres disk is full" — 5 numbered steps.
6. Do a backup/restore drill against a staging DB. Time it.

### Capstone PR (`helios-v2`)

**Title:** `chore: production deploy via Docker + systemd on OPi staging`

**What:** `infra/Dockerfile` (multi-stage), `infra/docker-compose.yml`, `infra/systemd/helios-api.service`, `infra/systemd/helios-scrape.timer`, `docs/runbooks/postgres-full.md`, `docs/runbooks/scraper-broken.md`, nightly `pg_dump` → Backblaze B2.

**Done when:** wiping the OPi, running one `make stage` command, and having the system back with yesterday's data in ≤ 30 minutes.

### Self-check rubric

- [ ] I can explain all 12 twelve-factor rules.
- [ ] I know the difference between a Docker image and a container.
- [ ] I can write a systemd unit from memory (User, ExecStart, Restart, Environment).
- [ ] I know which metric type (counter/gauge/histogram) to use for any observable.
- [ ] I have a backup-restore drill I've actually run.
- [ ] I can describe my prod deploy pipeline in 5 sentences.

---

## Appendix: Recommended Reading Order by Phase

| Phase | Modules |
|-------|---------|
| **Phase 0** — Foundations | M1, M2, M3 |
| **Phase 1** — Domain Model | M5, M6 |
| **Phase 2** — Parsing Library | M4 |
| **Phase 3** — Identity & Geo | M10 |
| **Phase 4** — First Scraper | M7 |
| **Phase 5** — Framework Decision | M8 |
| **Phase 6** — Ingest Pipeline | M9 |
| **Phase 7** — API Surface | M11 |
| **Phase 8** — Operations | M12 |
| **Phase 9** — Harden | — (revisit weak modules) |

---

## Meta: How to Study While Working a Day Job

- **Pick one module at a time.** Don't leapfrog.
- **Timebox.** 1–2 hours, 3 evenings/week. Inconsistent but sustained beats a weekend sprint.
- **Write every capstone as a real PR.** "I'll come back and clean it up later" is how V1 happened.
- **Keep a `./learning-journal.md` in your scratchpad repo.** One dated entry per session. What you read, what you tried, what surprised you. Re-read it weekly.
- **Pair with an AI assistant the way you'd pair with a senior dev.** Ask it to review your capstone PR *before* merging. Ask why, not what.
- **When stuck, use the self-check rubric.** If you can't answer a rubric question, that's your next topic.

---

*Last updated: 2026-04-23. Update this guide via PR whenever a module's resources go stale or a new essential resource appears.*
