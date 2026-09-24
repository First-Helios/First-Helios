# Spike: on-device menu model (classify, extract, validate)

**Status:** Not started
**Opened:** 2026-09-23 by the owner
**Feeds:** the Phase 5 menu-extraction ADR (menu-page classifier per
[ADR-0010 Amendment 3](../../adr/0010-website-and-menu-url-resolution.md#amendment-3-2026-09-23-menu-page-verification-and-platform-sites),
D3.4; cuisine tags deferred by
[ADR-0006](../../adr/0006-gold-menu-read-models.md#owner-decision))

This folder tracks a **throwaway evaluation**. It answers whether small models
running on the Orange Pi (RK3588, arm64, 32 GB RAM, CPU first) can replace
per-site parsing code for finding and reading menus, and possibly for cuisine
tagging. It builds nothing that ships. Its output is evidence for an ADR.

## Why

Scraped menus come in endless page formats. Deterministic parsers (JSON-LD,
known platforms) handle only some of them, and custom code per layout doesn't
scale. The idea is to use generic page segmentation, a small classifier for
blocks, and a small LLM for extraction. A **final validation check** must then
prove that every extracted value actually appears on the page before anything
is trusted.

## Pipeline under test

```
page ──► [0] structured? (JSON-LD / known platform) ──yes──► deterministic parse (baseline)
              │ no
              ▼
         [1] menu-page classifier ........ is this page a menu?
              ▼
         [2] generic segmentation ........ DOM/text blocks (no per-site code)
              ▼
         [3] block classifier ............ section | item | price | modifier | noise
              ▼
         [4] LLM extractor ............... blocks → {section, item, description, prices[]} JSON
              ▼
         [5] VALIDATOR (final gate) ...... static grounding checks + optional classifier cross-check
              ▼
         accepted rows (would become the lowest-trust `llm` interpretation, ADR-0005)
```

### [5] Validator: the final check

This stage is deterministic code, optionally backed by a second model. It
decides **accept / downgrade-to-unknown / reject** for each extracted row.

Static checks (required):
- **Price grounding:** the normalized price (`$12.50`, `12.5`, `12,50`,
  `$12`) must occur in the source text of the **same block**, or of an
  adjacent block linked to the item. No price on the page means no priced row;
  at most it becomes `unknown`.
- **Name grounding:** the item name's tokens appear in that block
  (case/whitespace/punctuation-insensitive; a small edit distance is allowed
  only if you measure and report it).
- **Binding:** the price is the nearest one to the item in document order, and
  it isn't already bound to a different item unless it's shared on purpose
  (e.g. a "all tacos $3" section price).
- **Sanity:** currency is consistent within the page; the amount is in a
  plausible range; no duplicate (item, variant, price) rows; the evidence
  locator (block id plus character span) is recorded for each field.

Model cross-check (optional, measured separately): a small NLI or cross-encoder
answers "does this block support *item X costs Y*?". Keep it only if it catches
errors that the static checks miss.

**How the validator is measured:** run it on (a) correct extractions and (b)
deliberately corrupted ones (a mutated price, prices swapped between items, an
invented item, a price from a different section). Report the catch rate and
the false-reject rate.

## Proposed success bars (owner to confirm or adjust)

| Stage | Metric | Proposed bar |
|---|---|---|
| [1] Menu-page classifier | precision / recall vs. S4's cheap pre-filter | precision ≥ 0.95, recall better than the pre-filter |
| [3] Block classifier | item + price F1 | ≥ 0.90 |
| [4] Extractor | exact price accuracy on validator-accepted rows | ≥ 0.98 |
| [4] Extractor | item recall on menu pages | ≥ 0.85 |
| [5] Validator | injected-corruption catch rate | ≥ 0.99 |
| [5] Validator | false-reject rate on correct rows | ≤ 0.10 |
| Pi runtime | median time per menu page (all stages) | ≤ 60 s |
| Pi runtime | peak RAM of the model stack | ≤ 8 GB (leaves room for Helios) |

## Guardrails

- **No Helios writes and no Helios runtime changes.** Spike code lives on the
  branch `spike/menu-model` under `spikes/menu_model/`, outside `packages/` and
  `apps/`, and is never merged. Only findings, metrics and label summaries come
  back to this folder, through a docs PR.
- Raw HTML/PDF snapshots stay in gitignored `var/spikes/menu-model/`; they are
  never committed.
- Fetching uses Helios's `SiteFetcher` (robots.txt, rate limit, size cap),
  identifies itself honestly, and is capped at the sample size.
- On the Pi: work only in `~/menu-model-spike`. Don't touch the Helios
  containers, DB, env files or ports. No sudo. Don't run `resolve_urls`
  (the Pi gate still holds). Bind anything you serve to 127.0.0.1.
- Record each model's licence; prefer Apache-2.0 or MIT. Report every download
  with its size.

## Progress

- [ ] A. Sample: owner-exported candidate list; about 60 pages fetched (≈40 real menus in varied formats: HTML list, table, PDF, image-only or JS-only noted; ≈20 non-menus: home, about, catering, ordering platforms)
- [ ] B. Labels: page labels, block labels, and gold items + prices for the menu pages; owner spot-checks 20%
- [ ] C. Baselines: JSON-LD/platform parse coverage; S4 pre-filter precision/recall
- [ ] D. [1]+[3] classifiers: embedding + logistic regression, cross-validated; timed on the Pi
- [ ] E. [4] extractor: `llama.cpp` + a small (1.5B–8B) instruct model with a JSON-only grammar; timed on the Pi
- [ ] F. [5] validator: static checks + corruption injection; optional NLI cross-check
- [ ] G. (Optional) cuisine: draft label list, compare with Overture categories on the sample
- [ ] H. Findings written below; recommendation for the ADR

## Results

_To be filled in by the spike session._

| Stage | Setup | Result | Meets bar? |
|---|---|---|---|
| | | | |

## Findings and recommendation

_To be filled in._

## Log

| Date | Session | Branch | What happened | Resume notes |
|---|---|---|---|---|
| 2026-09-23 | setup | docs/menu-model-spike | Tracker and hand-off prompt created | — |

## Hand-off prompt

Launch from the repo root: `claude --model claude-opus-5-5`, then `/model` →
effort **high**; mode: auto.

```text
Run the menu-model spike tracked in docs/spikes/menu-model/README.md. Read that file,
CLAUDE.md, ADR-0005 (menu interpretation kinds and ranking), ADR-0006 (cuisine/tag
deferral), ADR-0010 Amendment 3 (menu-page verification) and apps/discovery/web_client.py
(SiteFetcher) first.

This is a throwaway evaluation, not a feature. Branch spike/menu-model from main and keep
all spike code in spikes/menu_model/ (never under packages/ or apps/, never merged). Raw
page snapshots go in gitignored var/spikes/menu-model/. Follow the tracker's Guardrails
exactly: no Helios DB writes, nothing touching the Helios stack on the Pi, no sudo, no
resolve_urls, 127.0.0.1 only, and record licences and download sizes.

Work through the tracker's Progress list in order:
A. Don't query the Pi DB yourself. Look at the models and write me a read-only SELECT that
   exports ~150 candidates (venue name, website, resolved menu URL if any, Overture
   category if stored) as CSV. Stop and ask me to run it. Then pick a stratified ~60-page
   sample and fetch it with SiteFetcher. Count JS-only and image-only pages; don't add a
   headless browser.
B. Draft labels yourself (page / block / gold items+prices) in spikes/menu_model/labels/,
   then give me a random 20% to spot-check before you compute any metric.
C–F. Build the stages in the tracker's pipeline diagram. The validator [5] is the priority:
   implement the static grounding checks exactly as the tracker specifies, then measure
   them with corruption injection (mutated price, swapped prices, invented item, price
   from another section). Develop on this machine; run timing and RAM on the Pi over SSH
   (192.168.1.219; check ~/.ssh/config or ask me) in ~/menu-model-spike with its own venv.
   Prefer ONNX Runtime for embeddings (ask before installing torch). Build llama.cpp there
   only if the build tools already exist; otherwise ask.
G. Optional, only if time remains.
H. Fill in the tracker's Results table (against the proposed bars), Findings and
   recommendation, and a Log row.

End state: push spike/menu-model (don't open a PR for it). Open a docs-only PR that updates
docs/spikes/menu-model/README.md (ticks, results, findings, log) plus a small anonymized
labels summary, no raw HTML. Don't write the ADR. Finish with the recommendation and
the open questions I need to answer before the Phase 5 ADR. If the budget runs low, commit,
push, and write resume notes in the tracker's Log.
```
