"""
openclaw/orchestrator.py — OpenClaw agent orchestrator.

This is the top-level controller.  It:
  1. Connects to qwen2.5:7b-instruct via Ollama
  2. Feeds the LLM industry dimensions, valid terms, and budget state
  3. Has the LLM PROPOSE queries → pre-validates them → executes valid ones
  4. Tracks every request outcome (success/fail)
  5. At session end, asks the LLM to generate a wishlist of desired improvements

The key difference from agent_interface/ollama_agent.py:
  - That file is a generic Ollama ↔ agent_interface bridge
  - THIS file adds the pre-validation loop, industry awareness, tracking, and wishlist

Flow:
  LLM proposes  →  prevalidate  →  if valid → agent_queue.submit  →  tracker.log
       ↑                              if invalid → tell LLM why, retry
       │
       └─── feed results back ────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from agent_interface.queue_manager import agent_queue
from agent_interface.schemas import parse_agent_query, get_all_options

from openclaw.industries import (
    INDUSTRY_REGISTRY,
    get_all_industries,
    get_all_mega_corps,
)
from openclaw.prevalidate import (
    prevalidate_agent_plan,
    validate_search_term,
    validate_brand,
    validate_industry,
    check_budget_for_intent,
)
from openclaw.tracker import request_tracker
from openclaw.wishlist import wishlist_manager, WishCategory

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_CONFIG_PATH = _PROJECT_ROOT / "config" / "agent_config.yaml"

# ══════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct"
MAX_ITERATIONS = 12
TEMPERATURE = 0.3

# ══════════════════════════════════════════════════════════════════════
# System prompt — OpenClaw-specific, not the generic one in ollama_agent.py
# ══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are OpenClaw, a research planning agent for First-Helios.

Your mission: discover where LOCAL businesses can compete with mega-corporations
in industries like healthcare, retail, food service, fitness, childcare, etc.
You do this by planning data collection queries, validating them, and interpreting results.

## CRITICAL RULE: Pre-validation
Before any API call costs budget, your proposed queries go through pre-validation.
You MUST only propose search terms from the approved pools below.
If you want a term that doesn't exist, add it to your wishlist instead of using it.

## Available Industries
{industries}

## Available Mega-Corps
{mega_corps}

## Actions (JSON only — no other text)

### propose — Propose queries to be pre-validated before execution
```json
{{"action": "propose", "queries": [
    {{"intent": "poi_chain_locations", "region": "austin_tx", "brand": "starbucks",
      "industry": "coffee_cafe", "search_terms": ["barista", "coffee"],
      "reason": "Map Starbucks locations"}}
]}}
```

### query — Submit a single already-validated query for execution
```json
{{"action": "query", "intent": "data_quality_audit", "region": "austin_tx", "reason": "Initial audit"}}
```

### wish — Add an item to today's wishlist
```json
{{"action": "wish", "category": "new_term", "title": "Add matcha bar search term",
  "description": "Matcha-focused cafes are growing in Austin, missing from poi_search_terms",
  "suggested_value": "matcha bar", "industry": "coffee_cafe"}}
```
Categories: new_source, new_term, new_industry, new_brand, tool_request

### discovery — Run discovery scan to find expansion targets
```json
{{"action": "query", "intent": "discovery_scan", "region": "austin_tx",
  "reason": "Find coverage gaps and new stores to investigate"}}
```
Returns: coverage statistics, prioritised leads (brands/industries with data gaps,
stale records, geographic clusters needing attention), and suggested next queries.
Use these leads to decide what to explore next in the session.

### status — Check budget and queue state
```json
{{"action": "status"}}
```

### done — End the session with summary and wishlist reflection
```json
{{"action": "done", "summary": "Completed coffee_cafe and fast_food scans for Austin",
  "wishlist_reflection": "Would benefit from Indeed API access and 'matcha bar' as a POI term"}}
```

## CRITICAL term-matching rules
- For poi_chain_locations and poi_local_density → use ONLY poi_search_terms for that industry
- For job_posting_volume and wage_baseline → use ONLY job_search_terms for that industry
- For sentiment_check → use ONLY sentiment_keywords for that industry
- NEVER mix terms across industries. "barista" is a coffee_cafe term, NOT retail_general.
- Each industry block above lists its EXACT valid terms. Copy them exactly.

## Rules
1. ALWAYS start with data_quality_audit
2. After audit, run discovery_scan to find coverage gaps and prioritised expansion targets
3. Use discovery leads to decide which industries and brands to explore next — highest priority leads first
4. For each industry, check: chain locations → local density → wages → job postings → sentiment
5. ONLY use search terms from the approved pools listed above — match term type to intent
6. If a query is REJECTED, you MUST use "wish" to request the missing term/brand — do NOT retry with the same invalid term
7. Track your budget — check "status" if api_calls_remaining_today drops below 20
8. When your goal is met OR you have explored all requested industries, use "done" to end the session
9. At session end in the "done" action, include a wishlist_reflection listing any terms/brands/sources you wanted but didn't have
10. Output ONLY valid JSON per response — no surrounding text
11. Do NOT repeat the exact same query you already executed — check previous results first
12. Run discovery_scan again mid-session after completing a batch of queries to check for newly exposed gaps

## Current Context
{context}
"""


# ══════════════════════════════════════════════════════════════════════
# Session thought log — captures every LLM turn in real-time
# ══════════════════════════════════════════════════════════════════════

@dataclass
class LogEntry:
    """A single event in the session thought stream."""
    seq: int
    timestamp: str
    kind: str           # thinking | action | result | error | system | done
    content: str        # raw text or JSON string
    meta: dict = field(default_factory=dict)   # intent, industry, success, etc.

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.timestamp,
            "kind": self.kind,
            "content": self.content,
            "meta": self.meta,
        }


class SessionLog:
    """Thread-safe append-only log for live session monitoring."""

    def __init__(self) -> None:
        self._entries: list[LogEntry] = []
        self._lock = threading.Lock()
        self._seq = 0
        self.session_id: str = ""
        self.state: str = "idle"  # idle | running | complete | error

    def start(self, session_id: str) -> None:
        with self._lock:
            self._entries.clear()
            self._seq = 0
            self.session_id = session_id
            self.state = "running"

    def append(self, kind: str, content: str, meta: dict | None = None) -> None:
        with self._lock:
            self._seq += 1
            self._entries.append(LogEntry(
                seq=self._seq,
                timestamp=datetime.utcnow().isoformat(),
                kind=kind,
                content=content,
                meta=meta or {},
            ))

    def finish(self, state: str = "complete") -> None:
        self.state = state

    def get_since(self, after_seq: int = 0) -> list[dict]:
        """Return entries with seq > after_seq."""
        with self._lock:
            return [e.to_dict() for e in self._entries if e.seq > after_seq]

    def get_all(self) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in self._entries]

    def snapshot(self) -> dict:
        """Summary for the API."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "state": self.state,
                "entry_count": len(self._entries),
                "last_seq": self._seq,
            }


# Module-level singleton — accessible from server endpoints
session_log = SessionLog()


# ══════════════════════════════════════════════════════════════════════
# Session state
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ClawSession:
    """Tracks state across an OpenClaw research session."""
    region: str
    model: str
    goal: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)
    iterations: int = 0
    queries_proposed: int = 0
    queries_validated: int = 0
    queries_rejected: int = 0
    queries_executed: int = 0
    wishes_added: int = 0
    results: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    is_complete: bool = False
    final_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "region": self.region,
            "model": self.model,
            "goal": self.goal,
            "iterations": self.iterations,
            "queries_proposed": self.queries_proposed,
            "queries_validated": self.queries_validated,
            "queries_rejected": self.queries_rejected,
            "queries_executed": self.queries_executed,
            "wishes_added": self.wishes_added,
            "is_complete": self.is_complete,
            "final_summary": self.final_summary,
            "started_at": self.started_at.isoformat(),
            "duration_seconds": round((datetime.utcnow() - self.started_at).total_seconds(), 1),
        }


# ══════════════════════════════════════════════════════════════════════
# Orchestrator
# ══════════════════════════════════════════════════════════════════════

class OpenClawOrchestrator:
    """Main orchestrator for OpenClaw agent sessions.

    Usage:
        claw = OpenClawOrchestrator()
        session = claw.run("austin_tx", goal="Survey coffee & healthcare labor")
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        ollama_url: str = OLLAMA_BASE_URL,
        max_iterations: int = MAX_ITERATIONS,
        temperature: float = TEMPERATURE,
    ) -> None:
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.max_iterations = max_iterations
        self.temperature = temperature
        self._session: Optional[ClawSession] = None

    # ── Public API ───────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check Ollama server + model availability."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if not resp.ok:
                return False
            models = resp.json().get("models", [])
            names = [m.get("name", "") for m in models]
            base_names = [n.split(":")[0] for n in names]
            target = self.model.split(":")[0]
            return target in base_names or self.model in names
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if resp.ok:
                return [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    def run(
        self,
        region: str = "austin_tx",
        goal: str = "",
        industries: Optional[list[str]] = None,
    ) -> ClawSession:
        """Run an OpenClaw research session.

        Args:
            region: Target region.
            goal: Research goal description.
            industries: Subset of industries to focus on (None = all).
        """
        self._session = ClawSession(region=region, model=self.model, goal=goal)

        # Build system prompt with industry data
        industry_data = get_all_industries()
        if industries:
            industry_data = [i for i in industry_data if i["key"] in industries]

        mega_corps = get_all_mega_corps()
        if industries:
            mega_corps = [m for m in mega_corps if m["industry"] in industries]

        # Truncate for context window — just keys and terms, not full descriptions
        industries_compact = json.dumps([
            {
                "key": i["key"],
                "name": i["display_name"],
                "mega_corps": [m["key"] for m in i["mega_corps"]],
                "job_terms": i["job_search_terms"][:6],
                "poi_terms": i["poi_search_terms"][:6],
            }
            for i in industry_data
        ], indent=2)

        corps_compact = json.dumps([
            {"key": m["key"], "name": m["name"], "industry": m["industry"]}
            for m in mega_corps
        ], indent=2)

        context = f"Region: {region}"
        if goal:
            context += f"\nGoal: {goal}"
        if industries:
            context += f"\nFocus industries: {industries}"

        # ── Freshness context ───────────────────────────────────────
        # Tell the agent what data is stale/fresh so it prioritises wisely
        try:
            from backend.database import get_all_freshness
            from agent_interface.schemas import FRESHNESS_THRESHOLDS

            freshness_records = get_all_freshness()
            if freshness_records:
                stale = [r for r in freshness_records if r.get("is_stale", True)]
                fresh = [r for r in freshness_records if not r.get("is_stale", True)]

                context += f"\n\n## Source Freshness ({len(freshness_records)} tracked)"
                context += f"\nStale (need re-collection): {len(stale)}"
                context += f"\nFresh (skip these): {len(fresh)}"

                if stale:
                    context += "\n\nSTALE data — prioritize these:"
                    for r in stale[:15]:
                        brand_str = f" brand={r['brand']}" if r.get("brand") else ""
                        ind_str = f" industry={r['industry']}" if r.get("industry") else ""
                        context += (
                            f"\n  - {r['intent']}{brand_str}{ind_str}: "
                            f"{r['age_days']}d old (threshold: {r['threshold_days']}d), "
                            f"{r['records_collected']} records"
                        )

                if fresh:
                    context += "\n\nFRESH data — DO NOT re-collect:"
                    for r in fresh[:15]:
                        brand_str = f" brand={r['brand']}" if r.get("brand") else ""
                        ind_str = f" industry={r['industry']}" if r.get("industry") else ""
                        context += (
                            f"\n  - {r['intent']}{brand_str}{ind_str}: "
                            f"{r['age_days']}d old (threshold: {r['threshold_days']}d) ✓"
                        )
            else:
                context += "\n\n## Source Freshness: No data collected yet — everything is stale."

            context += f"\n\nFreshness thresholds (days): {json.dumps(FRESHNESS_THRESHOLDS)}"

        except Exception as e:
            logger.warning("[OpenClaw] Could not load freshness context: %s", e)
            context += "\n\n## Source Freshness: unavailable"

        system = SYSTEM_PROMPT.format(
            industries=industries_compact,
            mega_corps=corps_compact,
            context=context,
        )

        self._session.messages = [{"role": "system", "content": system}]

        # Start the live thought log
        sid = f"session-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        session_log.start(sid)
        session_log.append("system", f"Session started — model={self.model}  region={region}", {
            "model": self.model, "region": region, "goal": goal,
            "industries": industries or list(INDUSTRY_REGISTRY.keys()),
        })

        # Initial instruction
        initial = (
            f"Begin research for {region}. "
            f"Start with a data_quality_audit to understand current data state."
        )
        if goal:
            initial += f" Goal: {goal}"

        self._session.messages.append({"role": "user", "content": initial})
        session_log.append("system", initial)

        logger.info("[OpenClaw] Starting session: model=%s region=%s goal=%s",
                     self.model, region, goal)

        # Agent loop
        while (
            self._session.iterations < self.max_iterations
            and not self._session.is_complete
        ):
            self._session.iterations += 1
            logger.info("[OpenClaw] Iteration %d/%d", self._session.iterations, self.max_iterations)

            try:
                session_log.append("system", f"Iteration {self._session.iterations}/{self.max_iterations} — generating…")
                llm_response = self._generate(self._session.messages)
                if not llm_response:
                    session_log.append("error", "Empty LLM response — stopping session")
                    logger.warning("[OpenClaw] Empty response — stopping")
                    break

                # Log the raw LLM thought
                session_log.append("thinking", llm_response)

                self._session.messages.append({"role": "assistant", "content": llm_response})
                action_result = self._execute_action(llm_response)

                # Log the parsed action and result
                action_name = "unknown"
                try:
                    parsed = json.loads(self._extract_json(llm_response) or "{}")
                    action_name = parsed.get("action", "unknown")
                except Exception:
                    pass
                session_log.append("action", json.dumps(action_result, indent=2, default=str), {
                    "action": action_name,
                    "iteration": self._session.iterations,
                })

                self._session.messages.append(
                    {"role": "user", "content": f"Result:\n{json.dumps(action_result, indent=2)}"}
                )
            except Exception as e:
                logger.error("[OpenClaw] Iteration error: %s", e, exc_info=True)
                session_log.append("error", str(e))
                self._session.messages.append(
                    {"role": "user", "content": f"Error: {e}. Try a different approach."}
                )

        # Session end
        if not self._session.is_complete:
            self._session.final_summary = (
                f"Session ended after {self._session.iterations} iterations. "
                f"Proposed: {self._session.queries_proposed}, "
                f"Executed: {self._session.queries_executed}, "
                f"Rejected: {self._session.queries_rejected}, "
                f"Wishes: {self._session.wishes_added}"
            )

        # Save tracker and wishlist
        request_tracker.flush_now()
        wishlist_manager.set_session_summary(self._session.final_summary)
        wishlist_manager.save_now()

        # Close out the live log
        session_log.append("done", self._session.final_summary, self._session.to_dict())
        session_log.finish("complete")

        logger.info("[OpenClaw] Session complete: %s", self._session.to_dict())
        return self._session

    # ── Ollama communication ─────────────────────────────────────

    def _generate(self, messages: list[dict]) -> str:
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": 768,
                    },
                },
                timeout=180,
            )
            if resp.ok:
                return resp.json().get("message", {}).get("content", "")
            logger.error("[OpenClaw] API error: %s", resp.text[:200])
            return ""
        except requests.exceptions.ConnectionError:
            logger.error("[OpenClaw] Cannot connect to Ollama at %s", self.ollama_url)
            return ""
        except Exception as e:
            logger.error("[OpenClaw] Generate error: %s", e)
            return ""

    # ── Action dispatch ──────────────────────────────────────────

    def _execute_action(self, llm_response: str) -> dict:
        json_str = self._extract_json(llm_response)
        if not json_str:
            return {"error": "No valid JSON found. Output ONLY JSON."}

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {e}"}

        action = data.get("action", "")

        if action == "propose":
            return self._handle_propose(data)
        elif action == "query":
            return self._handle_query(data)
        elif action == "wish":
            return self._handle_wish(data)
        elif action == "status":
            return self._handle_status()
        elif action == "done":
            return self._handle_done(data)
        elif action == "batch":
            # Redirect batch to propose for pre-validation
            return self._handle_propose({"queries": data.get("queries", [])})
        else:
            return {
                "error": f"Unknown action '{action}'. "
                "Valid: propose, query, wish, status, done"
            }

    def _handle_propose(self, data: dict) -> dict:
        """Pre-validate a batch of proposed queries, then execute valid ones."""
        raw_queries = data.get("queries", [])
        if not raw_queries:
            return {"error": "No queries in proposal. Provide 'queries' list."}

        self._session.queries_proposed += len(raw_queries)

        # Pre-validate
        validation = prevalidate_agent_plan(raw_queries)

        # Execute valid ones, skip invalid
        executed_results = []
        for i, raw in enumerate(raw_queries):
            pv = validation.results[i] if i < len(validation.results) else None

            if pv and not pv.is_valid:
                # Log the rejection
                self._session.queries_rejected += 1
                request_tracker.log_prevalidation_rejection(
                    intent=raw.get("intent", ""),
                    industry=raw.get("industry", ""),
                    brand=raw.get("brand", ""),
                    search_term=str(raw.get("search_terms", "")),
                    rejection_reason=pv.rejection_reason or "pre-validation failed",
                )
                executed_results.append({
                    "status": "rejected",
                    "reason": pv.rejection_reason,
                    "suggestions": pv.suggestions,
                })
                continue

            # Build agent_interface query from raw
            query_data = {
                "intent": raw.get("intent", ""),
                "region": raw.get("region", self._session.region),
            }
            if raw.get("brand"):
                query_data["brand"] = raw["brand"]
            if raw.get("industry"):
                query_data["industry"] = raw["industry"]
            if raw.get("priority"):
                query_data["priority"] = raw["priority"]
            if raw.get("reason"):
                query_data["reason"] = raw["reason"]

            query, parse_errors = parse_agent_query(query_data)
            if parse_errors:
                self._session.queries_rejected += 1
                executed_results.append({
                    "status": "rejected",
                    "errors": parse_errors,
                })
                continue

            # Execute via the agent queue
            self._session.queries_validated += 1
            t0 = time.time()
            result = agent_queue.submit(query)
            latency_ms = int((time.time() - t0) * 1000)

            self._session.queries_executed += 1
            result_dict = result.to_dict()
            self._session.results.append(result_dict)
            executed_results.append(result_dict)

            # Log to tracker — treat partial as success but annotate
            status_val = result.status.value
            is_success = status_val == "completed"
            is_partial = status_val == "partial"
            error_msg = "; ".join(result.errors) if result.errors else None
            if is_partial:
                error_msg = (error_msg + "; " if error_msg else "") + "PARTIAL: no live API call, used cached DB data"
            request_tracker.log_request(
                intent=raw.get("intent", ""),
                source="agent_queue",
                success=is_success or is_partial,
                industry=raw.get("industry", ""),
                brand=raw.get("brand", ""),
                search_term=str(raw.get("search_terms", "")),
                records_returned=result.records_found,
                latency_ms=latency_ms,
                error_message=error_msg,
            )

        return {
            "proposed": len(raw_queries),
            "validated": validation.valid,
            "rejected": validation.rejected,
            "results": executed_results,
        }

    def _handle_query(self, data: dict) -> dict:
        """Submit a single query (skip pre-validation for simple intents)."""
        query_data = {k: v for k, v in data.items() if k != "action"}
        if "region" not in query_data:
            query_data["region"] = self._session.region

        self._session.queries_proposed += 1

        query, errors = parse_agent_query(query_data)
        if errors:
            self._session.queries_rejected += 1
            return {"status": "rejected", "errors": errors}

        self._session.queries_validated += 1
        t0 = time.time()
        result = agent_queue.submit(query)
        latency_ms = int((time.time() - t0) * 1000)

        self._session.queries_executed += 1
        result_dict = result.to_dict()
        self._session.results.append(result_dict)

        status_val = result.status.value
        is_success = status_val == "completed"
        is_partial = status_val == "partial"
        error_msg = "; ".join(result.errors) if result.errors else None
        if is_partial:
            error_msg = (error_msg + "; " if error_msg else "") + "PARTIAL: no live API call, used cached DB data"
        request_tracker.log_request(
            intent=data.get("intent", ""),
            source="agent_queue",
            success=is_success or is_partial,
            industry=data.get("industry", ""),
            brand=data.get("brand", ""),
            records_returned=result.records_found,
            latency_ms=latency_ms,
            error_message=error_msg,
        )

        return result_dict

    def _handle_wish(self, data: dict) -> dict:
        """Add a wish item to today's wishlist."""
        category = data.get("category", "tool_request")
        title = data.get("title", "")
        description = data.get("description", "")
        suggested_value = data.get("suggested_value", "")

        if not title:
            return {"error": "Wish must have a 'title'"}

        context = {}
        if data.get("industry"):
            context["industry"] = data["industry"]
        if data.get("brand"):
            context["brand"] = data["brand"]

        wish = wishlist_manager.add_wish(
            category=category,
            title=title,
            description=description,
            suggested_value=suggested_value,
            context=context,
            model=self.model,
        )
        self._session.wishes_added += 1
        return {"status": "wish_added", "wish": wish.to_dict()}

    def _handle_status(self) -> dict:
        """Return budget, tracker, and wishlist summary."""
        queue_status = agent_queue.status().to_dict()
        today_rollup = request_tracker.get_today_rollup().to_dict()
        pending_wishes = wishlist_manager.get_pending()

        return {
            "queue": queue_status,
            "today_tracker": today_rollup,
            "pending_wishes": len(pending_wishes),
            "session": self._session.to_dict() if self._session else {},
        }

    def _handle_done(self, data: dict) -> dict:
        """End the session and process wishlist reflection."""
        self._session.is_complete = True
        self._session.final_summary = data.get("summary", "")

        # If the LLM included a wishlist_reflection, auto-add it
        reflection = data.get("wishlist_reflection", "")
        if reflection:
            wishlist_manager.add_wish(
                category=WishCategory.TOOL_REQUEST.value,
                title="Session reflection",
                description=reflection,
                suggested_value="",
                model=self.model,
            )
            self._session.wishes_added += 1

        return {
            "status": "session_complete",
            "summary": self._session.final_summary,
            "session": self._session.to_dict(),
            "today_rollup": request_tracker.get_today_rollup().to_dict(),
            "wishes_today": wishlist_manager.get_today().to_dict(),
        }

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Extract JSON from LLM response."""
        import re
        text = text.strip()
        if text.startswith("{") or text.startswith("["):
            return text
        patterns = [
            r"```json\s*([\s\S]*?)```",
            r"```\s*([\s\S]*?)```",
            r"(\{[\s\S]*\})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1).strip()
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    continue
        return None


# ══════════════════════════════════════════════════════════════════════
# Convenience API for server endpoints
# ══════════════════════════════════════════════════════════════════════

_active_orchestrator: Optional[OpenClawOrchestrator] = None


def get_or_create_orchestrator(model: str = DEFAULT_MODEL) -> OpenClawOrchestrator:
    global _active_orchestrator
    if _active_orchestrator is None or _active_orchestrator.model != model:
        _active_orchestrator = OpenClawOrchestrator(model=model)
    return _active_orchestrator


def get_claw_status() -> dict:
    """Status endpoint data for the API."""
    orch = get_or_create_orchestrator()
    models = orch.list_models()
    available = orch.is_available()

    status = {
        "openclaw_available": available,
        "ollama_url": orch.ollama_url,
        "configured_model": orch.model,
        "available_models": models,
        "industries_loaded": len(INDUSTRY_REGISTRY),
        "industries": list(INDUSTRY_REGISTRY.keys()),
    }

    if orch._session:
        status["session"] = orch._session.to_dict()

    if not available:
        status["setup"] = {
            "step_1": "Ensure Ollama is running: ollama serve",
            "step_2": f"Pull model: ollama pull {orch.model}",
            "available_now": models,
        }

    return status
