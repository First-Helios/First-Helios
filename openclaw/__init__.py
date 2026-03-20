"""
openclaw/ — OpenClaw agent orchestration layer.

This package sits ABOVE agent_interface/ and provides:

  1. Industry exploration dimensions (healthcare, retail, food service, etc.)
  2. Query term pre-validation (LLM proposes → system validates before API spend)
  3. Per-request success/fail tracking with daily rollup
  4. Daily wishlist (agent requests tools/sources it thinks would help)
  5. Structured intake locations for each data source
  6. The main orchestrator that drives qwen2.5:7b-instruct via Ollama

Architecture:
  ┌──────────────┐     Ollama /api/chat     ┌──────────────────┐
  │ qwen2.5:7b   │ ←──────────────────────→ │  orchestrator.py │
  │ (local LLM)  │                          └────────┬─────────┘
  └──────────────┘                                   │
                                      ┌──────────────┼──────────────┐
                                      │              │              │
                                ┌─────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
                                │ prevalidate │ │ tracker  │ │ wishlist   │
                                │ .py         │ │ .py      │ │ .py        │
                                └─────┬──────┘ └────┬─────┘ └────────────┘
                                      │              │
                                ┌─────▼──────────────▼─────┐
                                │    agent_interface/       │
                                │    queue_manager + exec   │
                                └───────────────────────────┘

Usage:
    from openclaw.orchestrator import OpenClawOrchestrator

    claw = OpenClawOrchestrator()
    session = claw.run("austin_tx", goal="Survey coffee & healthcare labor markets")
"""
