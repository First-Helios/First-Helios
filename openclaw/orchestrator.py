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
from agent_interface.schemas import parse_agent_query, get_all_options, AgentMode, get_mode_config

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
SESSION_LOG_DIR = _PROJECT_ROOT / "data" / "openclaw_logs" / "sessions"

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

## Actions — output raw JSON ONLY, never use markdown fences or prose

### propose — Propose queries to be pre-validated before execution
{{"action": "propose", "queries": [
    {{"intent": "poi_chain_locations", "region": "austin_tx", "brand": "starbucks",
      "industry": "coffee_cafe", "search_terms": ["barista", "coffee"],
      "reasoning": "Starbucks is Priority 1 on the agenda — mapping locations reveals saturation zones for local competitors",
      "reason": "Map Starbucks locations"}}
]}}

### query — Submit a single DB-internal query (data_quality_audit, discovery_scan, score_refresh, campaign_status ONLY)
{{"action": "query", "intent": "data_quality_audit", "region": "austin_tx",
  "reasoning": "Starting with audit to understand current data state before collecting anything",
  "reason": "Initial audit"}}

### wish — Add one or more items to today's wishlist (use "wishes" array for multiple)
{{"action": "wish", "wishes": [
  {{"category": "new_term", "title": "Add matcha bar search term",
    "description": "Matcha cafes are growing in Austin, missing from poi_search_terms",
    "suggested_value": "matcha bar", "industry": "coffee_cafe"}},
  {{"category": "new_term", "title": "Add boba tea search term",
    "description": "Boba shops are underrepresented in coffee_cafe terms",
    "suggested_value": "boba tea", "industry": "coffee_cafe"}}
]}}
Categories: new_source, new_term, new_industry, new_brand, tool_request

### Running a discovery scan — use the query action with intent discovery_scan
{{"action": "query", "intent": "discovery_scan", "region": "austin_tx",
  "reason": "Find coverage gaps and new stores to investigate"}}
Returns: coverage statistics and suggested_next leads. Each suggested_next item has a
"suggested_intent" field showing what to collect — use it as the "intent" inside a propose action.
Do NOT use suggested_intent as a top-level action. Always wrap it: {{"action":"propose","queries":[...]}}

### status — Check budget and queue state
{{"action": "status"}}

### done — End the session with summary and wishlist reflection
{{"action": "done", "summary": "Completed coffee_cafe and fast_food scans for Austin",
  "wishlist_reflection": "Would benefit from Indeed API access and 'matcha bar' as a POI term"}}

## CRITICAL term-matching rules
- poi_chain_locations, poi_local_density → use ONLY poi_search_terms (place names like "hair salon", "HVAC")
- job_posting_volume, wage_baseline → use ONLY job_search_terms (job titles like "hair stylist", "HVAC technician")
- sentiment_check → use ONLY sentiment_keywords for that industry
- These pools are DIFFERENT. "hair salon" is a place type (POI). "hair stylist" is a job title (job).
- Each industry block above lists its EXACT valid terms under separate poi_terms and job_terms keys.

## Rules
1. Output ONLY valid JSON — your ENTIRE response must be a single JSON object starting with {{ and ending with }}. No prose before or after. No markdown fences (no ```). No "Let's...", "Here is...", or any other text.
2. Do NOT repeat the exact same query you already executed — check previous results first
3. Your Collection Agenda is already prepared in the Context above — start from Priority 1 and work down in order
4. Items marked ✓ in "Already collected" are fresh — do NOT re-collect them, they will be rejected
5. Run discovery_scan again mid-session after completing a batch of queries to find newly exposed gaps
6. For each industry, check: chain locations → local density → wages → job postings → sentiment
7. ONLY use search terms from the approved pools listed above — match term type to intent
8. If a query is REJECTED for a missing term, use "wish" to request it — it will be added to this session's term pool immediately so you can use it in the next query
9. Track your budget — check "status" if api_calls_remaining_today drops below 20
10. score_refresh, data_quality_audit, discovery_scan, and campaign_status are always DB-internal — they run in analyze mode automatically regardless of session mode
11. When your goal is met OR you have explored all agenda items, use "done" to end the session
12. At session end in the "done" action, include a wishlist_reflection listing any terms/brands/sources you wanted but didn't have
13. If a result contains "session_hint", follow it immediately — it is a system-level directive

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

    def save_to_file(self, messages: list[dict] | None = None, session_meta: dict | None = None) -> Path:
        """Write the full session log (entries + message history) to a timestamped JSON file.

        Args:
            messages: Full message list (system prompt + all user/assistant turns).
            session_meta: ClawSession.to_dict() snapshot.

        Returns:
            Path of the written file.
        """
        SESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
        fname = SESSION_LOG_DIR / f"session_{ts}_{self.session_id}.json"

        with self._lock:
            payload = {
                "session_id": self.session_id,
                "saved_at": datetime.utcnow().isoformat(),
                "state": self.state,
                "session": session_meta or {},
                "entries": [e.to_dict() for e in self._entries],
                "messages": messages or [],
            }

        fname.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("[OpenClaw] Session log saved → %s", fname)
        return fname


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
    mode: str = "mixed"
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
    executed_queries: set = field(default_factory=set)   # (intent, brand, industry) tuples
    consecutive_freshness_rejections: int = 0  # resets on any successful execute
    is_complete: bool = False
    final_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "region": self.region,
            "model": self.model,
            "mode": self.mode,
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
        self._session_terms: dict[str, list[str]] = {}  # terms added this session via wish

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
        mode: str = "mixed",
    ) -> ClawSession:
        """Run an OpenClaw research session.

        Args:
            region: Target region.
            goal: Research goal description.
            industries: Subset of industries to focus on (None = all).
            mode: Operational mode — collect, analyze, monitor, or mixed.
        """
        # Validate and resolve mode
        try:
            agent_mode = AgentMode(mode)
        except ValueError:
            logger.warning("[OpenClaw] Invalid mode '%s' — falling back to mixed", mode)
            agent_mode = AgentMode.MIXED

        # Resolve industry aliases (e.g. "mechanics" → "auto_repair")
        if industries:
            from openclaw.prevalidate import _resolve_industry_key
            resolved_industries = []
            for ind in industries:
                canonical = _resolve_industry_key(ind)
                if canonical:
                    if canonical != ind:
                        logger.info("[OpenClaw] Industry alias resolved: '%s' → '%s'", ind, canonical)
                    resolved_industries.append(canonical)
                else:
                    logger.warning("[OpenClaw] Unknown industry '%s' — skipping", ind)
            industries = resolved_industries or None
        mode_cfg = get_mode_config(agent_mode)

        self._session = ClawSession(
            region=region, model=self.model, mode=agent_mode.value, goal=goal,
        )

        # Build system prompt context — filtered by healthy endpoints
        industries_compact, corps_compact = self._build_dynamic_context(
            region=region,
            industries_filter=industries,
        )

        context = f"Region: {region}"
        if goal:
            context += f"\nGoal: {goal}"
        if industries:
            context += f"\nFocus industries: {industries}"

        # ── Pilot briefing ──────────────────────────────────────────
        # Run discovery + freshness before the loop so the agent reads a
        # ranked collection agenda instead of guessing from raw timestamps.
        self._session_terms = {}  # reset session term pool for new session
        context += self._build_pilot_briefing(region, agent_mode, industries_filter=industries)

        # ── Mode context ────────────────────────────────────────────
        context += f"\n\n## Operational Mode: {agent_mode.value.upper()}"
        context += f"\n{mode_cfg.description}"
        context += f"\nAllowed intents: {sorted(mode_cfg.allowed_intents)}"
        if mode_cfg.bypass_freshness:
            context += "\nFreshness gates: BYPASSED — all queries proceed regardless of data age"
        else:
            context += "\nFreshness gates: ACTIVE — stale data will be re-collected, fresh data skipped"
        if mode_cfg.require_new_data:
            context += "\nSuccess criteria: STRICT — must collect new records from external APIs"
        if not mode_cfg.allow_db_fallback:
            context += "\nDB fallback: DISABLED — cached data is NOT returned as results"
        if not mode_cfg.allow_collection:
            context += "\nExternal APIs: DISABLED — no external collection in this mode"

        system = SYSTEM_PROMPT.format(
            industries=industries_compact,
            mega_corps=corps_compact,
            context=context,
        )

        self._session.messages = [{"role": "system", "content": system}]

        # Start the live thought log
        sid = f"session-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        session_log.start(sid)
        session_log.append("system", f"Session started — model={self.model}  region={region}  mode={agent_mode.value}", {
            "model": self.model, "region": region, "goal": goal,
            "mode": agent_mode.value,
            "industries": industries or list(INDUSTRY_REGISTRY.keys()),
        })

        # Initial instruction
        initial = (
            f"Begin research for {region} in {agent_mode.value.upper()} mode. "
        )
        if agent_mode == AgentMode.COLLECT:
            initial += "Focus on collecting data where existing records are STALE or missing. Queries for already-fresh data will be automatically rejected. "
        elif agent_mode == AgentMode.ANALYZE:
            initial += "Focus on computing insights from existing data. No external API calls. "
        elif agent_mode == AgentMode.MONITOR:
            initial += "Run a lightweight health check. Read-only. "
        else:
            initial += "Start with a data_quality_audit to understand current data state. "
        if goal:
            initial += f"Goal: {goal}"

        self._session.messages.append({"role": "user", "content": initial})
        session_log.append("system", initial)

        logger.info("[OpenClaw] Starting session: model=%s region=%s mode=%s goal=%s",
                     self.model, region, agent_mode.value, goal)

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

        # Persist full conversation log (entries + message history) to disk
        try:
            log_path = session_log.save_to_file(
                messages=self._session.messages,
                session_meta=self._session.to_dict(),
            )
            logger.info("[OpenClaw] Full session transcript → %s", log_path)
        except Exception as e:
            logger.warning("[OpenClaw] Could not save session log: %s", e)

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
                        "num_predict": 1024,
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
            return {
                "error": "No valid JSON found in your response.",
                "recovery": (
                    "RETRY with JSON only — no prose, no markdown fences, no explanation. "
                    'Minimal valid example: {"action": "status"} '
                    'or {"action": "propose", "queries": [{"intent": "poi_chain_locations", '
                    '"region": "austin_tx", "brand": "starbucks", "industry": "coffee_cafe", '
                    '"search_terms": ["coffee"], "reasoning": "why", "reason": "label"}]}'
                ),
            }

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {
                "error": f"Malformed JSON: {e}",
                "recovery": (
                    "RETRY — fix the JSON syntax error above. "
                    "Ensure all strings are quoted, no trailing commas, no comments. "
                    'Minimal valid example: {"action": "status"}'
                ),
            }

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
        elif action == "discovery":
            # Alias: model wrote {"action":"discovery"} instead of {"action":"query","intent":"discovery_scan"}
            data.setdefault("intent", "discovery_scan")
            data["action"] = "query"
            return self._handle_query(data)
        else:
            return {
                "error": f"Unknown action '{action}'. "
                "Valid actions: propose, query, wish, status, done. "
                "NOTE: to run discovery_scan use {\"action\":\"query\",\"intent\":\"discovery_scan\"}"
            }

    def _build_dynamic_context(
        self,
        region: str,
        industries_filter: Optional[list[str]],
    ) -> tuple[str, str]:
        """Query the endpoint catalog and return (industries_compact, corps_compact).

        Only industries and brands backed by at least one healthy endpoint are
        included in the system prompt.  Falls back to the full hardcoded
        INDUSTRY_REGISTRY if the catalog is empty or unavailable.

        Returns:
            (industries_compact_json, corps_compact_json)
        """
        try:
            from backend.endpoint_catalog import get_healthy_endpoints, derive_available_capabilities

            endpoints = get_healthy_endpoints(industries=industries_filter)
            if not endpoints:
                raise RuntimeError("endpoint catalog returned zero healthy rows")

            caps = derive_available_capabilities(endpoints)
            available_industries = caps["available_industries"]  # None = all
            available_brands     = caps["available_brands"]      # None = all

            industry_data = get_all_industries()
            if industries_filter:
                industry_data = [i for i in industry_data if i["key"] in industries_filter]
            if available_industries:
                industry_data = [i for i in industry_data if i["key"] in available_industries]

            mega_corps = get_all_mega_corps()
            if industries_filter:
                mega_corps = [m for m in mega_corps if m["industry"] in industries_filter]
            if available_brands:
                mega_corps = [m for m in mega_corps if m["key"] in available_brands]

            logger.info(
                "[OpenClaw] Dynamic context from catalog: %d industries, %d brands (%d healthy endpoints)",
                len(industry_data), len(mega_corps), len(endpoints),
            )

        except Exception as exc:
            logger.warning(
                "[OpenClaw] Endpoint catalog unavailable (%s) — using full hardcoded registry",
                exc,
            )
            industry_data = get_all_industries()
            if industries_filter:
                industry_data = [i for i in industry_data if i["key"] in industries_filter]
            mega_corps = get_all_mega_corps()
            if industries_filter:
                mega_corps = [m for m in mega_corps if m["industry"] in industries_filter]

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

        return industries_compact, corps_compact

    def _build_pilot_briefing(self, region: str, mode: AgentMode, industries_filter: Optional[list[str]] = None) -> str:
        """Run discovery + freshness checks before the agent loop begins.

        Returns a formatted string to append to {context} in the system prompt.
        The agent reads a ranked collection agenda instead of raw timestamps so
        it doesn't have to guess what to collect first.
        """
        from agent_interface.schemas import FRESHNESS_THRESHOLDS
        from backend.database import get_all_freshness

        lines: list[str] = []
        lines.append("\n\n## Collection Agenda (auto-generated from discovery scan)")

        # ── Discovery leads (ranked) ──────────────────────────────
        try:
            from backend.discovery import run_discovery
            scan = run_discovery(region=region)
            leads = getattr(scan, "leads", [])
            # Filter to focus industries if specified
            if industries_filter:
                leads = [
                    l for l in leads
                    if not getattr(l, "industry", None) or l.industry in industries_filter
                ]
            if leads:
                lines.append("Follow this priority order:")
                for i, lead in enumerate(leads[:10], 1):
                    proposal = lead.to_agent_proposal() if hasattr(lead, "to_agent_proposal") else {}
                    brand_str = f" brand={proposal.get('brand')}" if proposal.get("brand") else ""
                    ind_str = f" industry={proposal.get('industry')}" if proposal.get("industry") else ""
                    lines.append(
                        f"  {i}. [{getattr(lead, 'lead_type', '?')}] "
                        f"{proposal.get('intent', '?')}{brand_str}{ind_str}"
                        f" — {getattr(lead, 'description', '')} "
                        f"(priority={getattr(lead, 'priority', 0)})"
                    )
                # Surface key anomalies
                anomalies = getattr(scan, "anomalies", [])
                if anomalies:
                    lines.append("\nKey data gaps detected:")
                    for a in anomalies[:5]:
                        lines.append(f"  ! {a}")
            else:
                lines.append("  (no discovery leads — DB may be empty or fully fresh)")
        except Exception as e:
            logger.warning("[OpenClaw] Pilot briefing: discovery scan failed: %s", e)
            lines.append(f"  (discovery unavailable: {e})")

        # ── Already-collected (do NOT re-collect) ────────────────
        try:
            freshness_records = get_all_freshness()
            fresh = [r for r in freshness_records if not r.get("is_stale", True)]
            if fresh:
                lines.append("\nAlready collected — do NOT re-collect (marked ✓):")
                for r in fresh[:20]:
                    brand_str = f" brand={r['brand']}" if r.get("brand") else ""
                    ind_str = f" industry={r['industry']}" if r.get("industry") else ""
                    lines.append(
                        f"  ✓ {r['intent']}{brand_str}{ind_str}: "
                        f"{r['records_collected']} records, {r['age_days']:.0f}d old"
                    )
        except Exception as e:
            logger.warning("[OpenClaw] Pilot briefing: freshness load failed: %s", e)

        lines.append(f"\nFreshness thresholds (days): {json.dumps(FRESHNESS_THRESHOLDS)}")
        return "\n".join(lines)

    def _handle_propose(self, data: dict) -> dict:
        """Pre-validate a batch of proposed queries, then execute valid ones."""
        raw_queries = data.get("queries", [])
        if not raw_queries:
            return {"error": "No queries in proposal. Provide 'queries' list."}

        self._session.queries_proposed += len(raw_queries)
        session_mode = self._session.mode

        # Pre-validate (mode-aware, with session-local terms)
        validation = prevalidate_agent_plan(raw_queries, mode=session_mode, session_terms=self._session_terms)

        # Execute valid ones, skip invalid
        executed_results = []
        for i, raw in enumerate(raw_queries):
            pv = validation.results[i] if i < len(validation.results) else None

            if pv and not pv.is_valid:
                # Log the rejection
                self._session.queries_rejected += 1
                is_freshness = pv.rejection_reason and "still fresh" in pv.rejection_reason
                if is_freshness:
                    self._session.consecutive_freshness_rejections += 1
                request_tracker.log_prevalidation_rejection(
                    intent=raw.get("intent", ""),
                    industry=raw.get("industry", ""),
                    brand=raw.get("brand", ""),
                    search_term=str(raw.get("search_terms", "")),
                    rejection_reason=pv.rejection_reason or "pre-validation failed",
                )
                result_entry: dict = {
                    "status": "rejected",
                    "reason": pv.rejection_reason,
                    "suggestions": pv.suggestions,
                }
                # After 2+ consecutive freshness rejections, tell the agent to wrap up
                if self._session.consecutive_freshness_rejections >= 2:
                    result_entry["session_hint"] = (
                        "All remaining agenda items appear to have fresh data. "
                        "Use the 'done' action to end the session with a summary and wishlist_reflection."
                    )
                executed_results.append(result_entry)
                continue

            # Build agent_interface query from raw
            query_data = {
                "intent": raw.get("intent", ""),
                "region": raw.get("region", self._session.region),
                "mode": session_mode,
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

            # Dedup check — skip queries already run this session
            _SKIP_DEDUP = {"discovery_scan", "data_quality_audit", "score_refresh", "campaign_status"}
            dedup_key = (
                raw.get("intent", ""),
                raw.get("brand", ""),
                raw.get("industry", ""),
            )
            if dedup_key[0] not in _SKIP_DEDUP and dedup_key in self._session.executed_queries:
                prev_count = next(
                    (r.get("records_found", 0) for r in self._session.results
                     if r.get("intent") == dedup_key[0]
                        and r.get("brand") == dedup_key[1]
                        and r.get("industry") == dedup_key[2]),
                    0,
                )
                executed_results.append({
                    "status": "duplicate",
                    "message": (
                        f"DUPLICATE — already ran {dedup_key[0]} / {dedup_key[1]} / {dedup_key[2]} "
                        f"this session and got {prev_count} records. "
                        "Move to the next agenda item."
                    ),
                })
                continue

            if dedup_key[0] not in _SKIP_DEDUP:
                self._session.executed_queries.add(dedup_key)

            # Execute via the agent queue
            self._session.queries_validated += 1
            t0 = time.time()
            result = agent_queue.submit(query)
            latency_ms = int((time.time() - t0) * 1000)

            self._session.queries_executed += 1
            self._session.consecutive_freshness_rejections = 0  # reset on any successful execute
            result_dict = result.to_dict()
            if result_dict.get("status") == "completed" and result_dict.get("records_found", -1) == 0:
                result_dict["zero_records_note"] = (
                    "No data found for this target. "
                    "Move to the next agenda item rather than retrying the same query."
                )
            self._session.results.append(result_dict)
            executed_results.append(result_dict)

            # Mode-aware success logging
            mode_cfg = get_mode_config(session_mode)
            status_val = result.status.value
            is_success = status_val == "completed"
            is_partial = status_val == "partial"
            # In modes that accept partial, treat it as success
            effective_success = is_success or (is_partial and mode_cfg.success_on_partial)
            error_msg = "; ".join(result.errors) if result.errors else None
            if is_partial and not mode_cfg.success_on_partial:
                error_msg = (error_msg + "; " if error_msg else "") + f"MODE={session_mode}: PARTIAL not accepted as success"
            request_tracker.log_request(
                intent=raw.get("intent", ""),
                source="agent_queue",
                success=effective_success,
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
        # Inject session mode — but force analyze for DB-internal intents so they
        # never fail due to COLLECT mode's require_new_data constraint.
        _ANALYSIS_ONLY_INTENTS = {
            "score_refresh", "data_quality_audit",
            "discovery_scan", "campaign_status",
        }
        if query_data.get("intent") in _ANALYSIS_ONLY_INTENTS:
            query_data["mode"] = "analyze"
        else:
            query_data["mode"] = self._session.mode

        self._session.queries_proposed += 1

        query, errors = parse_agent_query(query_data)
        if errors:
            self._session.queries_rejected += 1
            return {"status": "rejected", "errors": errors}

        # Dedup check for single-query path
        _SKIP_DEDUP = {"discovery_scan", "data_quality_audit", "score_refresh", "campaign_status"}
        dedup_key = (
            data.get("intent", ""),
            data.get("brand", ""),
            data.get("industry", ""),
        )
        if dedup_key[0] not in _SKIP_DEDUP and dedup_key in self._session.executed_queries:
            prev_count = next(
                (r.get("records_found", 0) for r in self._session.results
                 if r.get("intent") == dedup_key[0]
                    and r.get("brand") == dedup_key[1]
                    and r.get("industry") == dedup_key[2]),
                0,
            )
            return {
                "status": "duplicate",
                "message": (
                    f"DUPLICATE — already ran {dedup_key[0]} / {dedup_key[1]} / {dedup_key[2]} "
                    f"this session and got {prev_count} records. "
                    "Move to the next agenda item."
                ),
            }

        if dedup_key[0] not in _SKIP_DEDUP:
            self._session.executed_queries.add(dedup_key)

        self._session.queries_validated += 1
        t0 = time.time()
        result = agent_queue.submit(query)
        latency_ms = int((time.time() - t0) * 1000)

        self._session.queries_executed += 1
        result_dict = result.to_dict()
        if result_dict.get("status") == "completed" and result_dict.get("records_found", -1) == 0:
            result_dict["zero_records_note"] = (
                "No data found for this target. "
                "Move to the next agenda item rather than retrying the same query."
            )
        self._session.results.append(result_dict)

        # Mode-aware success logging
        mode_cfg = get_mode_config(self._session.mode)
        status_val = result.status.value
        is_success = status_val == "completed"
        is_partial = status_val == "partial"
        effective_success = is_success or (is_partial and mode_cfg.success_on_partial)
        error_msg = "; ".join(result.errors) if result.errors else None
        if is_partial and not mode_cfg.success_on_partial:
            error_msg = (error_msg + "; " if error_msg else "") + f"MODE={self._session.mode}: PARTIAL not accepted"
        request_tracker.log_request(
            intent=data.get("intent", ""),
            source="agent_queue",
            success=effective_success,
            industry=data.get("industry", ""),
            brand=data.get("brand", ""),
            records_returned=result.records_found,
            latency_ms=latency_ms,
            error_message=error_msg,
        )

        return result_dict

    def _handle_wish(self, data: dict) -> dict:
        """Add one or more wish items to today's wishlist.

        Accepts either:
          - Single wish: top-level fields (category, title, description, ...)
          - Batch wish:  {"action":"wish", "wishes":[{...}, {...}]}
        """
        wish_items: list[dict] = data.get("wishes") or []
        if not wish_items:
            # Single-wish form: treat the data dict itself as the wish
            wish_items = [data]

        added: list[dict] = []
        session_terms_added: list[str] = []

        for item in wish_items:
            category      = item.get("category", "tool_request")
            title         = item.get("title", "")
            description   = item.get("description", "")
            suggested_value = item.get("suggested_value", "")

            if not title:
                added.append({"status": "skipped", "reason": "missing title"})
                continue

            context = {}
            if item.get("industry"):
                context["industry"] = item["industry"]
            if item.get("brand"):
                context["brand"] = item["brand"]

            wish = wishlist_manager.add_wish(
                category=category,
                title=title,
                description=description,
                suggested_value=suggested_value,
                context=context,
                model=self.model,
            )
            self._session.wishes_added += 1
            entry = {"status": "wish_added", "wish": wish.to_dict()}

            # Immediately add new_term wishes to session-local term pool
            if category == "new_term" and suggested_value and context.get("industry"):
                term = suggested_value.strip()
                industry = context["industry"]
                self._session_terms.setdefault(industry, []).append(term)
                entry["session_term_added"] = True
                session_terms_added.append(f"'{term}' → {industry}")

            added.append(entry)

        result: dict = {"status": "wishes_added", "count": len(added), "wishes": added}
        if session_terms_added:
            result["message"] = (
                f"Terms added to this session's pool and usable immediately: "
                + ", ".join(session_terms_added)
            )
        return result

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
        """Extract the first valid JSON object from an LLM response.

        Handles:
        - Pure JSON responses (ideal)
        - Markdown-fenced JSON (``` json ... ```)
        - Multiple JSON objects separated by whitespace — takes the FIRST valid one
          so that batch outputs like three separate wish objects don't hard-fail
        """
        import re
        text = text.strip()

        # Fast path: response is already a single JSON object/array
        if text.startswith("{") or text.startswith("["):
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError:
                # May be multiple objects — fall through to first-object extraction
                pass

        # Try markdown fences first
        for pattern in [r"```json\s*([\s\S]*?)```", r"```\s*([\s\S]*?)```"]:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1).strip()
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    continue

        # Extract the FIRST complete {...} block using a brace-counting scan.
        # This handles the case where the model outputs multiple JSON objects
        # separated by whitespace (e.g. three wish objects on consecutive lines).
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        # This brace pair didn't produce valid JSON; keep scanning
                        start = None

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
