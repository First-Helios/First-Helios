# Agent Observation Handoff
**Focus:** Evaluating OpenClaw agent quality — JSON errors, rejection patterns, and execution success rate

---

## Context

The OpenClaw agent is a `qwen2.5:7b-instruct` LLM loop that receives a structured system prompt,
a pre-built collection agenda, and then iterates up to 12 turns proposing and executing data
collection queries. The goal of this observation session is to determine where the 7B model
breaks down and what changes to the system prompt or pipeline would improve it.

A new diagnostic frontend exists at **`/openclaw/session`** (Session Lab). Launch sessions from
there and watch behavior in real time.

---

## The Three Signals to Measure

### 1. JSON Error Rate
**What it is:** How often the model outputs something that cannot be parsed as JSON.

**Where to see it:** Stats bar → `JSON errors` counter. Each "thinking" entry that fails
`JSON.parse()` increments this. The turn card will show `⚠ not valid JSON` badge and display
the raw output.

**What it tells you:**
- `0` errors — model is following the output format instructions well
- `1–2` errors — occasional confusion, probably recoverable
- `3+` errors — the prompt is creating confusion; the model reverts to freeform prose

**Common causes:**
- Prompt is too long and the format instructions get pushed out of the model's context window
- The model is trying to "explain" before outputting JSON (`Sure! Here is my response...`)
- The model got a confusing result back and responded conversationally

**Where the format instruction lives:** `orchestrator.py:150`
```
11. Output ONLY valid JSON per response — no surrounding text
```

---

### 2. Rejection Rate and Rejection Reasons
**What it is:** Proposals that fail pre-validation before any API call is made.

**Where to see it:**
- Sidebar → `Rejection Log` — live list as the session runs
- Stats bar → `Rejected` counter
- Per-turn card → red `✗` items with the rejection reason and suggestions
- Post-session: `data/openclaw_logs/requests_YYYY-MM-DD.json` — records with `prevalidation_passed: false`

**Common rejection reasons and what they indicate:**

| Rejection reason | What it means |
|---|---|
| `term not found in approved pool` | Model invented a search term not in the industry's approved list |
| `intent requires brand field` | Model omitted a required field for this intent |
| `intent X is not valid in collect mode` | Model used an analysis-only intent without using the query action |
| `industry X is not recognized` | Model hallucinated an industry name |
| `freshness gate: already collected within N days` | Model is trying to re-collect data that is still fresh |

**What repeated rejections on the same reason tell you:**
If the model keeps getting `term not found` for the same industry, the approved term pool for
that industry is either too small (needs more terms) or the model isn't reading the terms
list closely enough. If it's the latter, restructuring the SYSTEM_PROMPT term tables may help.

**Pre-validation code:** `openclaw/prevalidate.py`
**Term pools:** `backend/schemas.py` → `POI_SEARCH_TERMS`, `JOB_SEARCH_TERMS`, `SENTIMENT_KEYWORDS`

---

### 3. Execution Success Rate
**What it is:** Of the queries that pass pre-validation, how many come back `completed` vs `partial`/`error`.

**Where to see it:**
- Turn card result items: `✓` = completed, `~` = partial/error
- Stats bar: `Executed` is the validated count; compare to `Proposed` to see the filter rate
- Post-session: `data/openclaw_logs/requests_YYYY-MM-DD.json` → `"success": true/false`

**Ratio to watch:** `Executed / Proposed`. A healthy session looks like `8/10` or better.
Anything below `5/10` means either the term pool needs expansion or the model is consistently
proposing things it shouldn't.

---

## What to Look for in Each Turn

Open the Session Lab and expand each turn card. Ask these questions:

**In the thinking section (🧠):**
- Did the model provide a `reasoning` field? If `(no reasoning field)` appears frequently,
  the model is skipping its justification — add `"reasoning": "..."` as a required JSON field
  in the SYSTEM_PROMPT examples
- Is the reasoning coherent with the agenda? If the agenda shows Priority 1 = `poi_chain_locations`
  for starbucks but the model's reasoning says "I'll start with a data quality check", it is
  ignoring the pre-built agenda (Rule 1 violation)
- For `⚠ not valid JSON` turns: what did the model write instead? Look for patterns:
  - Starts with prose ("Let me think...") → model needs stronger JSON-only enforcement
  - Partial JSON (cut off) → model hit a token limit or got confused mid-output
  - Markdown fencing (```json ... ```) → model is wrapping correctly but the extractor strips it

**In the result section (⚡):**
- Are rejections always the same intent/industry? → that term pool is too small
- Are rejections spreading across many intents? → model is guessing terms instead of reading the list
- `records = 0` on a `✓ completed` result → the adapter ran but found nothing; this is valid, not a bug

---

## Agenda Adherence Check

The right sidebar shows the **Collection Agenda** — the ranked list of gaps the discovery engine
found before the session started. Watch whether the model:

1. **Picks up Priority 1 first** (good) — it read the agenda and is following it
2. **Jumps to a random intent** (bad) — it ignored the agenda and is choosing based on internal reasoning
3. **Marks agenda items as done** (checkmarks appear) — successful execution against the agenda
4. **Never clears any agenda item** by session end — either all proposals were rejected or the
   model kept picking non-agenda targets

If the model ignores the agenda consistently, Rule 1 in the SYSTEM_PROMPT (`orchestrator.py:140`)
may need to be stronger — for example, quoting the exact intent and brand from Priority 1 as
the literal first action.

---

## Session Loop Architecture (quick reference)

```
run()
  ↓ _build_pilot_briefing()      → ranks gaps, builds collection agenda
  ↓ SYSTEM_PROMPT + context      → injected into first user message
  ↓ session_log.append("system") → logged as first system entry (contains agenda)

loop (max 12 iterations):
  1. session_log.append("system", "Iteration N/12")
  2. _generate(messages)          → POST to Ollama, raw LLM text
  3. session_log.append("thinking", llm_response)
  4. _execute_action(llm_response)
     - JSON extract from llm_response
     - dispatch: propose | query | wish | status | done
     - for propose: prevalidate → execute valid ones
  5. session_log.append("action", result_json, meta={action, iteration})
  6. result fed back to LLM as next user message
```

**Key files:**
- `openclaw/orchestrator.py` — session loop, SYSTEM_PROMPT, `_build_pilot_briefing()`
- `openclaw/prevalidate.py`  — pre-validation gate (what rejects before execution)
- `openclaw/tracker.py`      — per-request outcome logging
- `agent_interface/validator.py` — second validation at execution time
- `data/openclaw_logs/`      — daily JSON logs of all requests

---

## Post-Session Log Analysis

After running a session, the tracker log at `data/openclaw_logs/requests_YYYY-MM-DD.json` has
one record per executed request. Quick patterns to check:

```bash
# Count successes vs failures
python3 -c "
import json, pathlib
d = json.loads(pathlib.Path('data/openclaw_logs/requests_2026-03-21.json').read_text())
ok  = sum(1 for r in d if r['success'])
rej = sum(1 for r in d if not r.get('prevalidation_passed', True))
print(f'Total: {len(d)}  Success: {ok}  Pre-val rejected: {rej}  Fail-after-exec: {len(d)-ok-rej}')
"

# Most common rejection reasons (prevalidation rejections logged separately via tracker)
# See GET /api/openclaw/tracker for the full rollup
```

Or just open `GET /api/openclaw/tracker` in the browser for the dashboard rollup view.

---

## Hypotheses to Test

Run 2–3 sessions with the same goal and different modes. Compare metrics.

| Hypothesis | Test | Success criterion |
|---|---|---|
| Model ignores the agenda | Watch Turn 1 reasoning — does it cite Priority 1? | Reasoning names the exact brand/intent from Agenda item 1 |
| "no reasoning field" is common | Count turns where reasoning panel shows the italic fallback | `< 2` per 12-turn session |
| Rejection rate is term-pool size | Run same session twice, approve one rejected wish term between runs | Rejection count drops on second run |
| JSON errors correlate with long prompts | Compare error count for sessions with 3 industries vs 1 industry | Fewer industries → fewer JSON errors |
| Model hits max_iterations without `done` | Watch for session ending without a ✅ done card | Session ends with explicit `done` action |

---

## Suggested Prompt Interventions (by failure mode)

| Failure mode | Where to change | What to try |
|---|---|---|
| Frequent JSON parse errors | `orchestrator.py:150` | Add a recovery rule: "If you realize you began with prose, STOP and restart your response as pure JSON" |
| No `reasoning` field | `orchestrator.py:91–96` | Add `"reasoning": "why I'm choosing this"` to every JSON example in the SYSTEM_PROMPT |
| Agenda ignored on Turn 1 | `orchestrator.py:140` | Change Rule 1 to: "Your FIRST action MUST be the propose action targeting Agenda item 1 exactly as listed" |
| Same term rejected repeatedly | `backend/schemas.py` POI/JOB term pools | Add the rejected term to the appropriate approved pool |
| Model proposes analysis intents via `propose` | `orchestrator.py:147` | Strengthen Rule 8: list the four analysis intents explicitly in Rule 1 and say "these use the `query` action only" |
| Session hits 12 iterations without `done` | `orchestrator.py:149` | Add Rule: "After iteration 8, if all agenda items are covered, immediately output the `done` action" |

---

## Current Baseline (2026-03-21)

From `data/openclaw_logs/requests_2026-03-21.json`:
- Requests logged: at least 3 observed entries
- Intents seen: `data_quality_audit`, `poi_chain_locations`, `discovery_scan`
- All `success: true` so far
- No prevalidation rejections in current log

This is the baseline before systematic observation begins. Run sessions via the Session Lab,
note JSON error count and rejection reasons, and track changes as you iterate on the prompt.
