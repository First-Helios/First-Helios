"""
agent_interface/ollama_agent.py — Local LLM agent powered by Ollama.

Connects a local Ollama model to the First-Helios agent interface.
The LLM plans research queries, interprets results, and iterates.

Architecture:
  ┌─────────────┐     HTTP/JSON      ┌─────────────────┐
  │  Ollama LLM │ ←─────────────────→ │  OllamaAgent    │
  │  (local)    │  /api/generate      │  (this file)    │
  └─────────────┘                     └────────┬────────┘
                                               │ calls
                                      ┌────────▼────────┐
                                      │ agent_interface/ │
                                      │ queue_manager    │
                                      └─────────────────┘

Supported models (tested):
  - openclaw (research/planning agent)
  - llama3.2 (general purpose, fast)
  - mistral (good at structured JSON)
  - deepseek-r1 (reasoning)

Usage:
    from agent_interface.ollama_agent import OllamaAgent

    agent = OllamaAgent(model="openclaw")  # or any Ollama model
    agent.run_research_session("austin_tx")
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from agent_interface.queue_manager import agent_queue
from agent_interface.schemas import (
    AgentQuery,
    ConciseResult,
    Intent,
    Region,
    get_all_options,
    parse_agent_query,
)

# ══════════════════════════════════════════════════════════════════════
# Agent config document path
# ══════════════════════════════════════════════════════════════════════

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_CONFIG_PATH = _PROJECT_ROOT / "config" / "agent_config.yaml"

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "openclaw"
MAX_ITERATIONS = 10         # Safety limit on agent loop iterations
MAX_CONTEXT_TOKENS = 4096   # Context window for model

# ══════════════════════════════════════════════════════════════════════
# System prompt — teaches the LLM how to use the agent interface
# ══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a research planning agent for First-Helios, a labor market intelligence platform focused on chain staffing analysis.

Your complete configuration reference (enums, constraints, output schemas, rules) is loaded below from config/agent_config.yaml.  Use it as your single source of truth for valid inputs, expected outputs, and behavioral rules.

## AGENT CONFIG REFERENCE
{agent_config}

## Current Session Context
{context}

## Reminder
- Output ONLY valid JSON — one JSON object per response, no markdown fences.
- ALWAYS begin with data_quality_audit.
- Follow suggested_next from results unless you have a justified alternative.
- End with {{"action":"done","summary":"..."}}.
"""


# ══════════════════════════════════════════════════════════════════════
# Agent Implementation
# ══════════════════════════════════════════════════════════════════════


@dataclass
class AgentSession:
    """Tracks state across a research session."""
    region: str
    model: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    iterations: int = 0
    queries_submitted: int = 0
    results: list[dict] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)
    is_complete: bool = False
    final_summary: str = ""


class OllamaAgent:
    """LLM agent that plans and executes research via the agent interface.

    Uses local Ollama model to generate structured queries, interpret
    results, and iterate until the research question is answered.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        ollama_url: str = OLLAMA_BASE_URL,
        max_iterations: int = MAX_ITERATIONS,
        temperature: float = 0.3,
    ) -> None:
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.max_iterations = max_iterations
        self.temperature = temperature
        self._session: Optional[AgentSession] = None

    # ── Public API ───────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if Ollama server is running and model is available."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if not resp.ok:
                return False
            models = resp.json().get("models", [])
            model_names = [m.get("name", "").split(":")[0] for m in models]
            # Also check full name with tag (e.g. "deepseek-r1:8b")
            full_names = [m.get("name", "") for m in models]
            target = self.model.split(":")[0]
            return target in model_names or self.model in full_names
        except Exception:
            return False

    def server_running(self) -> bool:
        """Check if Ollama server is reachable (regardless of model)."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            return resp.ok
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """List available Ollama models."""
        try:
            resp = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if resp.ok:
                return [m.get("name", "") for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    def pull_model(self, model: Optional[str] = None) -> dict:
        """Pull a model from the Ollama registry."""
        model = model or self.model
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/pull",
                json={"name": model, "stream": False},
                timeout=600,  # Large models take time
            )
            return resp.json() if resp.ok else {"error": resp.text}
        except Exception as e:
            return {"error": str(e)}

    def run_research_session(
        self,
        region: str = "austin_tx",
        goal: Optional[str] = None,
    ) -> AgentSession:
        """Run an autonomous research session.

        The LLM agent will:
        1. Audit existing data quality
        2. Plan collection queries based on gaps
        3. Execute queries and interpret results
        4. Iterate until research goal is met or budget exhausted

        Args:
            region: Region to research.
            goal: Optional research goal description.

        Returns:
            AgentSession with full history and results.
        """
        self._session = AgentSession(region=region, model=self.model)

        # Load agent config document
        agent_config_text = ""
        try:
            if AGENT_CONFIG_PATH.exists():
                agent_config_text = AGENT_CONFIG_PATH.read_text(encoding="utf-8")
                logger.info("[OllamaAgent] Loaded agent config from %s", AGENT_CONFIG_PATH)
            else:
                logger.warning("[OllamaAgent] Agent config not found at %s — using fallback", AGENT_CONFIG_PATH)
                options = get_all_options()
                agent_config_text = json.dumps(options, indent=2)
        except Exception as e:
            logger.warning("[OllamaAgent] Failed to load agent config: %s — using fallback", e)
            options = get_all_options()
            agent_config_text = json.dumps(options, indent=2)

        # Build context
        context = f"Region: {region}"
        if goal:
            context += f"\nResearch goal: {goal}"

        system = SYSTEM_PROMPT.format(
            agent_config=agent_config_text,
            context=context,
        )

        self._session.messages = [{"role": "system", "content": system}]

        # Seed with initial instruction
        initial_prompt = (
            f"Begin researching the labor market in {region}. "
            f"Start with a data_quality_audit to understand current data state."
        )
        if goal:
            initial_prompt += f" Research goal: {goal}"

        self._session.messages.append({"role": "user", "content": initial_prompt})

        logger.info(
            "[OllamaAgent] Starting research session: model=%s region=%s",
            self.model, region,
        )

        # Agent loop
        while (
            self._session.iterations < self.max_iterations
            and not self._session.is_complete
        ):
            self._session.iterations += 1
            logger.info("[OllamaAgent] Iteration %d", self._session.iterations)

            try:
                # Get LLM response
                llm_response = self._generate(self._session.messages)
                if not llm_response:
                    logger.warning("[OllamaAgent] Empty LLM response — stopping")
                    break

                self._session.messages.append(
                    {"role": "assistant", "content": llm_response}
                )

                # Parse and execute the action
                action_result = self._execute_action(llm_response)

                # Feed result back to LLM
                self._session.messages.append(
                    {"role": "user", "content": f"Result:\n{json.dumps(action_result, indent=2)}"}
                )

            except Exception as e:
                logger.error("[OllamaAgent] Iteration error: %s", e)
                self._session.messages.append(
                    {"role": "user", "content": f"Error: {str(e)}. Try a different approach."}
                )

        if not self._session.is_complete:
            self._session.final_summary = (
                f"Session ended after {self._session.iterations} iterations. "
                f"Submitted {self._session.queries_submitted} queries."
            )

        logger.info(
            "[OllamaAgent] Session complete: iterations=%d queries=%d",
            self._session.iterations,
            self._session.queries_submitted,
        )
        return self._session

    def run_single_query(self, intent: str, **kwargs) -> ConciseResult:
        """Execute a single query without LLM involvement.

        Convenience method for programmatic use.
        """
        query_data = {"intent": intent, "region": kwargs.pop("region", "austin_tx")}
        query_data.update(kwargs)

        query, errors = parse_agent_query(query_data)
        if errors:
            return ConciseResult(
                query_id="manual",
                status="rejected",
                intent=intent,
                errors=errors,
            )

        return agent_queue.submit(query)

    # ── Ollama API ───────────────────────────────────────────────

    def _generate(self, messages: list[dict]) -> str:
        """Call Ollama /api/chat endpoint."""
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": self.temperature,
                        "num_predict": 512,
                    },
                },
                timeout=120,
            )
            if resp.ok:
                return resp.json().get("message", {}).get("content", "")
            else:
                logger.error("[OllamaAgent] API error: %s", resp.text[:200])
                return ""
        except requests.exceptions.ConnectionError:
            logger.error(
                "[OllamaAgent] Cannot connect to Ollama at %s. "
                "Is 'ollama serve' running?",
                self.ollama_url,
            )
            return ""
        except Exception as e:
            logger.error("[OllamaAgent] Generate error: %s", e)
            return ""

    # ── Action parsing and execution ─────────────────────────────

    def _execute_action(self, llm_response: str) -> dict:
        """Parse the LLM's JSON output and execute the action."""
        # Extract JSON from the response (may have markdown fences)
        json_str = self._extract_json(llm_response)
        if not json_str:
            return {"error": "No valid JSON found in response. Output ONLY JSON."}

        try:
            action_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {e}. Output ONLY valid JSON."}

        action = action_data.get("action", "")

        if action == "query":
            return self._handle_query(action_data)
        elif action == "batch":
            return self._handle_batch(action_data)
        elif action == "pause":
            return agent_queue.pause(action_data.get("reason", ""))
        elif action == "resume":
            return agent_queue.resume()
        elif action == "status":
            return agent_queue.status().to_dict()
        elif action == "done":
            self._session.is_complete = True
            self._session.final_summary = action_data.get("summary", "")
            return {"status": "session_complete", "summary": self._session.final_summary}
        else:
            return {
                "error": f"Unknown action '{action}'. "
                "Valid actions: query, batch, pause, resume, status, done"
            }

    def _handle_query(self, data: dict) -> dict:
        """Parse and submit a single query."""
        # Remove the 'action' key before parsing as AgentQuery
        query_data = {k: v for k, v in data.items() if k != "action"}

        # Default region from session
        if "region" not in query_data and self._session:
            query_data["region"] = self._session.region

        query, errors = parse_agent_query(query_data)
        if errors:
            return {"status": "rejected", "errors": errors}

        result = agent_queue.submit(query)
        self._session.queries_submitted += 1
        result_dict = result.to_dict()
        self._session.results.append(result_dict)
        return result_dict

    def _handle_batch(self, data: dict) -> dict:
        """Parse and submit a batch of queries."""
        raw_queries = data.get("queries", [])
        results = []

        for raw in raw_queries:
            if "region" not in raw and self._session:
                raw["region"] = self._session.region

            query, errors = parse_agent_query(raw)
            if errors:
                results.append({"status": "rejected", "errors": errors})
                continue

            result = agent_queue.submit(query)
            self._session.queries_submitted += 1
            result_dict = result.to_dict()
            self._session.results.append(result_dict)
            results.append(result_dict)

        return {"count": len(results), "results": results}

    @staticmethod
    def _extract_json(text: str) -> Optional[str]:
        """Extract JSON from LLM response, handling markdown fences."""
        # Try the whole text first
        text = text.strip()
        if text.startswith("{") or text.startswith("["):
            return text

        # Try to find JSON in markdown code blocks
        import re
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
# Server endpoints for Ollama agent management
# ══════════════════════════════════════════════════════════════════════

# These are registered in server.py as /api/agent/ollama/*
# They allow the frontend or operator to manage the Ollama agent.

_active_agent: Optional[OllamaAgent] = None


def get_or_create_agent(model: str = DEFAULT_MODEL) -> OllamaAgent:
    """Get or create the singleton Ollama agent instance."""
    global _active_agent
    if _active_agent is None or _active_agent.model != model:
        _active_agent = OllamaAgent(model=model)
    return _active_agent


def get_agent_status() -> dict:
    """Return agent status for the API."""
    agent = get_or_create_agent()
    model_ready = agent.is_available()
    server_up = agent.server_running()
    models = agent.list_models()

    status = {
        "ollama_server_running": server_up,
        "ollama_url": agent.ollama_url,
        "configured_model": agent.model,
        "model_ready": model_ready,
        "available_models": models,
    }

    if agent._session:
        status["session"] = {
            "region": agent._session.region,
            "iterations": agent._session.iterations,
            "queries_submitted": agent._session.queries_submitted,
            "is_complete": agent._session.is_complete,
            "started_at": agent._session.started_at.isoformat(),
        }

    if not model_ready:
        # Show which models ARE ready to use
        ready_alternatives = [m for m in models if m] if models else []
        status["setup_instructions"] = {
            "step_1": "Install Ollama: curl -fsSL https://ollama.com/install.sh | sh",
            "step_2": "Start server: ollama serve",
            "step_3": f"Pull model: ollama pull {agent.model}",
            "step_4": "Retry this endpoint to verify",
            "already_available": ready_alternatives,
            "note": (
                f"You can use any available model by passing "
                f"'model' in your request body. "
                f"Currently available: {ready_alternatives}"
                if ready_alternatives else
                "No models pulled yet."
            ),
            "recommended_models": [
                {"name": "llama3.2", "size": "2GB", "speed": "fast", "quality": "good"},
                {"name": "mistral", "size": "4GB", "speed": "medium", "quality": "great for JSON"},
                {"name": "deepseek-r1:7b", "size": "4.5GB", "speed": "medium", "quality": "strong reasoning"},
                {"name": "openclaw", "size": "varies", "speed": "varies", "quality": "research-focused"},
            ],
        }

    return status
