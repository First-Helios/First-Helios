# First-Helios — System Design

A big-picture guide to why this system is built the way it is: the mission behind it, the design decisions that shaped it, the tradeoffs made along the way, and where it stands relative to industry practice.

---

## Table of Contents

1. [The Problem Being Solved](#1-the-problem-being-solved)
2. [What the System Actually Does](#2-what-the-system-actually-does)
3. [Why an LLM Agent Drives Collection](#3-why-an-llm-agent-drives-collection)
4. [Architecture Layers and Why Each Exists](#4-architecture-layers-and-why-each-exists)
5. [Key Design Decisions Explained](#5-key-design-decisions-explained)
6. [Pros of the Current Design](#6-pros-of-the-current-design)
7. [Cons and Known Limits](#7-cons-and-known-limits)
8. [Suggested Practices from Industry Standards](#8-suggested-practices-from-industry-standards)

---

## 1. The Problem Being Solved

Chain employers — Starbucks, McDonald's, Target, CVS — draw workers from local communities, but wages and profits flow out. Local independent employers often pay more and keep money in the neighborhood, but they cannot compete for workers because they lack the recruiting infrastructure that chains have.

The gap is structural: local businesses do not have a careers page, an HR department, or the budget to post on Indeed. They also do not know when workers at a nearby chain are most likely to be looking.

**First-Helios exists to close that information gap.**

It maps where chain stores are under staffing pressure — high job posting volume, poor sentiment, wages below local alternatives — and surfaces those locations to community organizers who can show up with a permitted job fair booth at the right time and place.

Everything the system does flows from this mission:
- Collect publicly available signals from chain employers
- Score each location by staffing stress
- Rank locations by their value as a job fair site
- Let an AI agent drive collection decisions so a human doesn't have to

---

## 2. What the System Actually Does

The pipeline has five stages that form a closed loop:

```
DISCOVER → COLLECT → INGEST → SCORE → TARGET
    ↑                                     │
    └─────────── feedback ────────────────┘
```

**DISCOVER** — The discovery engine reads the current state of the database and identifies gaps: industries with zero stores indexed, stores with no job posting signals, wage data that has gone stale. It ranks these gaps by priority (0–100) and produces a collection agenda.

**COLLECT** — The OpenClaw agent reads that agenda and executes queries against external public data sources: AllThePlaces for store locations, BLS for wages, JobSpy/Workday for job postings, Reddit for sentiment. All external calls go through a rate-manager that enforces daily API budgets.

**INGEST** — Raw `ScraperSignal` objects from adapters are written to the database as `Store`, `Signal`, `WageIndex`, and `Snapshot` rows. Geocoding runs on any store that lacks coordinates. Spatial deduplication prevents the same physical location from being recorded twice under different IDs.

**SCORE** — The scoring engine reads signals and computes a per-store composite score from three independent sub-scores: job posting volume (age-decay weighted), worker sentiment (Reddit + reviews), and wage gap (chain pay vs local alternatives). Scores are percentile-ranked within the region so the ranking is always relative, not absolute.

**TARGET** — The targeting algorithm combines staffing stress, wage gap, geographic isolation, and local employer density into a final site ranking. The top-ranked locations are the job fair recommendations.

---

## 3. Why an LLM Agent Drives Collection

The alternative to an LLM agent is a fixed collection scheduler: a cron job that runs every intent on every brand on a fixed interval. This is simpler and more predictable, but it fails for this problem for three reasons.

**Reason 1 — The collection space is semantically rich.**

Knowing that "barista" is a valid job search term for `coffee_cafe` but NOT for `retail_general` requires semantic understanding. Knowing that "matcha bar" is an emerging category in Austin that belongs in `coffee_cafe` requires the kind of open-ended reasoning that a fixed scheduler cannot do. The LLM adds genuine value in term selection, category reasoning, and recognizing emerging gaps.

**Reason 2 — The collection state machine is too complex for a fixed schedule.**

Every collection decision is governed by at least five interacting constraints: data freshness (has this been collected recently enough?), API budget (how many calls remain today?), mode (is this a collection or analysis session?), coverage (what percentage of this industry is already indexed?), and priority (which gaps matter most for the mission?). A fixed scheduler treats all of these independently. The LLM treats them as a unified problem.

**Reason 3 — The system needs to surface what it doesn't know it doesn't know.**

A scheduler runs the same queries on the same brands on the same intervals. It cannot recognize "we have zero data for the entire healthcare_clinic industry" and spontaneously decide to fix it. The discovery engine surfaces these gaps, but something needs to read them and act. The LLM agent does that.

**What the agent does NOT do** — the LLM does not decide what data sources are valid, what terms are permitted, or what counts as a fresh data point. Those decisions are made by the prevalidation gate and freshness system. The agent works within guardrails; it is not trusted to invent them.

### The Discovery-First Architecture

The key structural decision is that the agent should be a **reader and executor of a pre-built agenda**, not a guesser. Before the agent loop starts, `_build_pilot_briefing()` runs `discovery_scan` internally and injects the ranked collection agenda into the system prompt:

```
## Collection Agenda (auto-generated from discovery scan)
  1. [coverage_gap] poi_chain_locations brand=mcdonalds industry=fast_food
     — Zero stores for entire 'Fast Food' industry. 5 mega-corps tracked. (priority=90)
  2. [stale] wage_baseline industry=fast_food
     — 92 days old, threshold=90 days (priority=85)
  ...
Already collected — do NOT re-collect:
  ✓ poi_chain_locations brand=starbucks: 119 records, 1d old
```

This eliminates the roulette wheel problem where the agent guesses what to collect and wastes iterations on data that is already fresh or already blocked by the prevalidation gate.

---

## 4. Architecture Layers and Why Each Exists

### Layer 1 — Scrapers (`scrapers/`)

**Why it exists:** External public data does not arrive in a consistent format. AllThePlaces returns GeoJSON. Overture returns DuckDB-queried Parquet over S3. BLS returns JSON time series. JobSpy returns dataframes. Each source needs its own adapter.

**Why it is isolated:** Scraper code has a single contract — it receives parameters and returns a list of `ScraperSignal` objects. Nothing upstream knows or cares how data was collected. This means any adapter can be swapped, upgraded, or replaced without touching ingest, scoring, or the agent.

**The key abstraction:** `ScraperSignal` is the universal handoff type. It carries `store_num`, `chain`, `source`, `signal_type`, `value`, `metadata`, and `observed_at`. Ingest maps these fields to the appropriate DB tables. The scraper never writes to the DB directly.

### Layer 2 — Backend (`backend/`)

**Why it exists:** Business logic — how to score a store, when data is stale, how to deduplicate a new location against an existing one — lives here. It is independent of both the HTTP layer above and the scrapers below.

**The database is append-friendly by design.** Every collection adds new `Signal` rows rather than overwriting existing ones. This preserves historical observations for trend analysis. The `SourceFreshness` table is the separate tracking layer that decides when to re-collect, without polluting the signal data itself.

**Why the scoring model is percentile-based:** Absolute job posting counts are meaningless across regions and industries. A Starbucks with 5 open positions in Austin has a different meaning than an HVAC franchise with 5 open positions. Percentile ranking within the region and industry ensures that "critical" always means "in the top third of your peers right now."

### Layer 3 — Agent Interface (`agent_interface/`)

**Why it exists:** The LLM should not talk directly to scrapers. The agent interface is the structured contract layer between LLM intent and backend execution. It enforces that every query has a valid `Intent`, `Region`, and `AgentMode`, that required fields are present, and that the query passes freshness and budget checks before any external call is made.

**Why `validate_and_check()` runs before execution:** Validation is cheap. API calls are not. The validator screens out duplicate requests (data is still fresh), budget-exhausted requests (no API calls remain today), and schema-invalid requests (missing required fields) — all in-memory, in under 10ms.

**Why modes exist:** Different operational contexts have different needs. COLLECT mode requires new records — if nothing was collected, it failed. ANALYZE mode is purely DB-internal — it never makes external calls and accepts partial data as success. MONITOR mode is read-only. MIXED is the intelligent default that uses freshness gates to decide whether to collect or serve from cache. One executor handles all four modes; the mode config controls behavior.

### Layer 4 — OpenClaw (`openclaw/`)

**Why it exists:** The agent needs a specialized orchestration layer, not a generic LLM wrapper. OpenClaw adds: term pool prevalidation, industry awareness, freshness-based query filtering, wishlist tracking for gaps the agent cannot fill itself, request logging, and a session-local term pool so agent discoveries are immediately usable.

**Why prevalidation is a separate gate from validation:** Validation (in `agent_interface/validator.py`) is run at execution time for every query. Prevalidation (in `openclaw/prevalidate.py`) is run before a batch of LLM proposals are even submitted. Prevalidation catches: terms the LLM hallucinated that are not in the approved pool, freshness violations before they hit the validator, and budget overruns before any API calls are attempted. This two-gate design means the LLM can propose aggressively and the system filters safely.

### The Pipeline Package (`pipeline/`)

**Why it exists:** The route index, tracing, and validation modules exist to answer the question: "Given an intent, what is the complete path from here to a DB write, and is that path healthy?" Without this, debugging a collection failure requires reading five different files. With it, `ROUTES["poi_chain_locations"]` immediately shows which adapters are live, which are unwired, what DB table they write to, and what the freshness threshold is.

---

## 5. Key Design Decisions Explained

### Public data only

Every data source used is publicly accessible without authentication (or using only public API keys with published rate limits). This is not a pragmatic constraint — it is a legal and ethical principle. The defensibility of the mission depends on not bypassing access controls. This rules out scraped private pages, breached datasets, or anything that requires impersonating a user.

### Local LLM via Ollama, not cloud API

The LLM (qwen2.5:7b-instruct) runs locally via Ollama. This was chosen for three reasons:

1. **Cost** — Cloud LLM API calls at session scale (12 iterations × N sessions) accumulate. A locally-run 7B model is free after the initial download.
2. **Latency** — Local inference is faster than a round-trip to a cloud API, particularly for short structured JSON outputs.
3. **Data privacy** — The collection agenda and query payloads contain real business intelligence. Running locally means none of it leaves the machine.

The tradeoff is capability: qwen2.5:7b-instruct is significantly less capable than frontier models (GPT-4, Claude Opus). The prevalidation gate exists partly to compensate for this — the LLM does not need to be clever about what terms are valid because the gate tells it.

### SQLite over PostgreSQL

SQLite is sufficient for the current scale: one region, one operator, sequential writes. SQLite's simplicity means zero operational overhead — no server process, no connection pool, no authentication. The database is a single file (`data/tracker.db`) that can be backed up with `cp`. When concurrent writes become a bottleneck (multiple simultaneous scrapers + the agent + the scheduler), the migration path to PostgreSQL is well-defined because the ORM (SQLAlchemy) abstracts the SQL dialect.

### Freshness tracking is a separate table, not a field on Store

`SourceFreshness` tracks when each (intent, region, brand, industry) combination was last collected. This design was chosen over adding a `last_collected_at` column to `Store` because:

1. A store has multiple collection dimensions (locations, job postings, wages, sentiment). Each has its own freshness threshold.
2. The freshness check runs before execution, not after. It needs to answer "should I collect this?" without querying the actual data tables.
3. Collection metadata (threshold, records_collected, status) is different from store metadata. Mixing them pollutes the Store model.

### Score refresh always runs in ANALYZE mode

Score refresh has no external API calls. It reads `Signal` and `WageIndex` rows and writes `Score` rows. Running it in COLLECT mode (which requires `records_new > 0`) always fails because scoring produces no "new" external records. Forcing `mode=analyze` for all DB-internal intents (`score_refresh`, `data_quality_audit`, `discovery_scan`, `campaign_status`) is a structural fix, not a workaround.

---

## 6. Pros of the Current Design

**Self-limiting by design.** The rate manager, freshness system, and prevalidation gate together ensure the system cannot accidentally over-collect. A misconfigured agent session cannot DDoS a data source or rebuild the entire database overnight. Every collection decision has at least two independent checks before an external call is made.

**Observable at every layer.** Every scraper call is logged in `ApiRequestLog`. Every agent query goes through `request_tracker`. Every collection outcome stamps `SourceFreshness`. The `pipeline/` package provides `RouteContract` for any intent and a startup health check that verifies all routes are importable and consistent. When something breaks, the failure is attributable to a specific layer.

**Extensible without modification.** Adding a new brand requires adding one entry to `industries.py` and one to `schemas.py`. Adding a new data source requires writing a `BaseScraper` subclass, registering a `RouteContract`, and adding it to the relevant executor handler. No existing code needs to change. The prevalidation gate and freshness system pick it up automatically.

**The agent is a net accelerator, not a crutch.** On a session-with-briefing basis, the LLM reads a discovery-generated agenda and executes it. The agent's 12 iterations are spent executing real collection work rather than figuring out what to collect. The wishlist provides a feedback channel for gaps the formal discovery strategies cannot surface (emerging categories, new brands, novel term phrasing).

**Test coverage is comprehensive and isolated.** 258 tests cover the full pipeline with zero external dependencies. In-memory SQLite means integration tests run in ~1.5 seconds. Patching at the call site (not the definition site) means tests match production import paths exactly.

---

## 7. Cons and Known Limits

**7B LLM capability ceiling.** qwen2.5:7b-instruct can misclassify terms, mix industries, or produce malformed JSON that breaks the action parse loop. The prevalidation gate and action parser have compensating logic, but the fundamental limit is model capacity. A larger model (14B+) would reduce prevalidation rejections at the cost of inference time and memory.

**Single region, single operator.** The architecture supports multi-region in config, but the pipeline, scheduler, and frontend are all built around Austin TX. Adding a second region requires verifying that every adapter handles non-Austin bounding boxes, adding BLS series IDs for the new MSA, and extending the discovery engine's region-awareness. This is medium effort, not low.

**SQLite write contention.** The scheduler, the agent, and manual API calls can all attempt DB writes simultaneously. SQLite serializes writes, so high-frequency simultaneous collection could create latency. This is not a problem at Austin scale but will need to be addressed before multi-region scaling.

**No cross-session learning.** Each OpenClaw session starts from scratch. The agent does not remember that `JobSpyAdapter` consistently returns 0 results for healthcare brands, or that `AllThePlaces` does not have a spider for `marriott`. Discovery leads surface these gaps as coverage_gap items, but the agent cannot carry forward "lesson learned" context across sessions. This requires either prompt injection from a persistent knowledge store or a larger context window.

**Scoring requires enough regional peers.** The percentile scoring model needs at least 3 stores in the same region and industry to produce meaningful rankings. For industries where coverage is thin (e.g., accommodation, HVAC), scores are assigned but are not yet statistically meaningful. The data_quality_audit surfaces this as a coverage anomaly.

**Wishlist is advisory, not automated.** The agent can request new terms, brands, and data sources via the wishlist. The wishlist is saved to a JSON file. Session-local wishes are immediately usable within the same session, but permanent additions to the approved term pool still require a human to edit `industries.py`. There is no automated pipeline from wishlist approval to term pool update.

**Targeting output is not yet connected to scheduling.** The targeting algorithm produces a ranked list of job fair sites. This list is exposed via the API and visible on the frontend map, but there is no module that translates "location X ranked #1" into a scheduling recommendation (best day of week, time of day, co-presence of a local employer fair, etc.). That contextual layer does not yet exist.

---

## 8. Suggested Practices from Industry Standards

The following recommendations are drawn from published standards and common patterns in labor market data systems, LLM agent pipelines, and public data collection infrastructure. Each is evaluated against the current First-Helios design.

---

### 8.1 Data Collection Ethics and Legality

**Standard: `robots.txt` and ToS compliance (EFF, hiQ v. LinkedIn, CFAA)**
Public data scraping is legally contested but generally permitted when: (1) data is publicly accessible without login, (2) the scraper does not circumvent technical access controls, (3) use is not commercial exploitation of the host's data.

*Current status:* All First-Helios sources are either official public APIs (BLS, AllThePlaces, Overture) or Reddit's public JSON endpoint. The Playwright-based Google Maps adapter is UNWIRED precisely because its legal standing is less clear. This is the right call — keep it unwired until legal review.

*Recommendation:* Add a `LEGAL.md` that documents the access basis for each source: API terms of service link, rate limit in ToS vs. rate limit enforced in code, and any attribution requirements. BLS data requires attribution.

---

### 8.2 Data Freshness and Validity Windows

**Standard: BLS Statistical Policy Directive No. 1 / OECD Statistics guidelines**
Labor market statistics have defined validity windows based on collection methodology. BLS OEWS data is published annually; treating it as "stale after 90 days" is already more conservative than necessary. Job posting data from aggregators has a typical half-life of 7–14 days before postings are filled or expired.

*Current status:* Freshness thresholds are intent-aware and match published collection cycles reasonably well (POI: 60 days, wages: 90 days, job postings: 14 days).

*Recommendation:* Document the *source* of each threshold in `schemas.py` as a comment — e.g., `# BLS OEWS is annual; 90d is conservative`. This makes thresholds auditable and prevents future changes that drift away from the underlying data reality.

---

### 8.3 LLM Agent Systems: Guardrails and Constraint Enforcement

**Standard: NIST AI RMF (AI Risk Management Framework) — Govern, Map, Measure, Manage**
NIST's framework for AI systems recommends separating the "AI decision layer" from "constraint enforcement" so that AI reasoning errors cannot propagate into system actions without passing through a validation boundary.

*Current status:* This is exactly what the prevalidation gate and validator do. The LLM proposes; the system validates independently. LLM hallucinations are caught before any external call is made. This is a strong alignment with NIST's "Manage" function.

*Recommendation:* Log the prevalidation rejection reason alongside the original LLM proposal in the session thought log. When the agent receives "term rejected," the operator should be able to see what the agent proposed and why it was rejected — this surfaces model weaknesses and term pool gaps that need to be addressed.

---

### 8.4 Data Pipeline Observability

**Standard: OpenTelemetry specification (CNCF) / Google SRE "Four Golden Signals"**
Production data pipelines should be observable through: latency (how long does each stage take?), throughput (how many records per run?), error rate (what fraction of attempts fail?), and saturation (how close is the system to its limits?).

*Current status:* `ApiRequestLog` captures latency and success/fail per request. `RateBudget` captures daily saturation. `SourceFreshness` captures throughput implicitly via `records_collected`. The `pipeline/tracing.py` module provides `PipelineTrace` and `TraceSpan` dataclasses for span-level recording, but they are not yet wired into the executor.

*Recommendation (high value, low effort):* Wire `PipelineTrace` into `execute_query()` in `executor.py`. One trace per query, one span per pipeline stage (validation → handler → scraper → ingest → freshness stamp). Expose the trace in the `ConciseResult` so the session log shows exactly where time was spent and where failures occurred.

---

### 8.5 Schema Validation at Boundaries

**Standard: FAIR Data Principles (Findable, Accessible, Interoperable, Reusable) — Interoperability requirement**
Data crossing a system boundary (scraper → ingest, ingest → scoring) should be validated against a contract at the crossing point. Without boundary validation, a scraper that returns malformed data silently corrupts downstream results.

*Current status:* `pipeline/validation.py` defines `SCRAPER_OUTPUT_CONTRACTS` and `validate_scraper_output()`. These are tested but not yet called by the executor before passing signals to `ingest_signals()`.

*Recommendation:* Call `validate_scraper_output(intent_key, signals)` in each `_execute_*` handler before calling `ingest_signals()`. Log warnings (not errors) for contract violations that are non-blocking (e.g., missing coordinates) and return `PARTIAL` status for violations that indicate data quality issues.

---

### 8.6 Rate Limiting and API Stewardship

**Standard: W3C API Best Practices / Google API Design Guide — Quota and billing**
Responsible API usage means staying well within published limits, implementing exponential backoff on errors, and treating daily limits as a shared resource across all consumers.

*Current status:* The `rate_manager` enforces daily limits per source before execution. `ApiRequestLog` tracks every call. Budget dry-runs in prevalidation prevent over-commitment. This is solid.

*Recommendation:* Add `retry_after_seconds` to `ApiSource` so that when a source returns 429 (Too Many Requests), the rate manager can enforce a cooldown before retrying rather than failing immediately. This is especially important for JobSpy (50/day) which is close to its limit in active sessions.

---

### 8.7 Labor Market Data Interpretation

**Standard: BLS Handbook of Methods / EPI (Economic Policy Institute) wage methodology**
Labor market data requires careful interpretation. Job posting counts are a leading indicator of hiring intent, not a confirmed headcount. Posted wages may differ from realized wages. Glassdoor/Indeed review scores are subject to selection bias (disgruntled workers over-represented).

*Current status:* The scoring model uses BLS OEWS data for wage baseline (methodology well-established), Reddit sentiment as a directional signal (not a representative sample), and job posting volume as a proxy for staffing pressure (appropriate use given the source).

*Recommendation:* Add a `data_caveats` field to `ConciseResult` or the targeting output that surfaces relevant caveats for human consumers. "Sentiment based on 12 Reddit posts — low confidence" is valuable context for a community organizer deciding whether to visit a location. Consider a minimum data threshold below which a score should be labeled "insufficient data" rather than placed on a scale.

---

### 8.8 Reproducibility and Auditability

**Standard: ACM Principles for Algorithmic Transparency / IEEE Ethically Aligned Design**
Systems that produce ranked outputs (who gets a job fair, which stores are targeted) should be auditable. A community organizer or policy researcher should be able to understand why location X ranked above location Y.

*Current status:* Scores are stored in the `scores` table with `score_type` (composite, careers, sentiment, wage) and `value`. Targeting inputs (stress, wage_gap, isolation, density) are computed from stored data. The chain of computation is reconstructible from the DB, but there is no user-facing explanation layer.

*Recommendation:* Add a `score_explanation` endpoint to the API that, for a given `store_num`, returns: which signals were used, their weights, the resulting sub-scores, and the percentile rank at time of computation. This makes the ranking explainable to non-technical stakeholders and is aligned with emerging algorithmic transparency expectations.

---

### 8.9 Data Governance for Sensitive Context

**Standard: FTC guidelines on data collection / NLRB labor organizing protections**
This platform operates at the intersection of labor organizing, commercial activity, and public data. Relevant constraints:

- **No personally identifiable information.** The system collects location-level data, not worker-level data. This is intentional and must be maintained. Any future signals that could identify individual workers (social media posts, employee reviews linked to usernames) should be aggregated before storage.
- **Labor organizing is protected activity.** Using publicly available labor market data to inform where job fairs happen is protected commercial speech and lawful labor market competition. The system should never cross into surveillance of individual workers or coordination with anti-union activity.
- **Attribution.** BLS data requires attribution when published. AllThePlaces data is licensed under Creative Commons (ODbL). Overture Maps data is licensed CC-BY 4.0. These licenses must be respected in any public-facing output.

*Recommendation:* Add a `DATA_SOURCES.md` file that lists each source, its license, any attribution requirements, and its intended use within the system. This protects the project legally and provides a clear basis for expanding data sources responsibly.

---

### 8.10 Iterative City-by-City Scaling

**Standard: Urban Institute / PolicyLink community data practice guides**
Research platforms serving community economic development work best when they are built with the community, validated locally before scaling, and designed so that local organizations can interpret and act on the outputs without data science expertise.

*Current status:* The "Austin TX first, done right" principle is correct. The platform is building depth in one market — real store counts, real wage data, real sentiment — before attempting breadth.

*Recommendation:* Before adding a second city, define a "city readiness checklist": minimum stores indexed per industry (e.g., >50), scoring coverage > 80%, at least one successful job fair informed by the platform's output, and a community partner who has reviewed the targeting methodology. The data does not become useful until it is used.

---

*Document version: March 2026. Reflects system state after pipeline/ package implementation, pilot briefing, and test suite completion.*
