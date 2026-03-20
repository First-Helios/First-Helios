"""
agent_interface — LLM-facing structured query interface.

Everything an agent submits goes through schema validation.
Everything it receives back is a concise, structured response.

Design principles:
  1. Enum-constrained inputs — agent picks from fixed lists
  2. Pre-flight validation — schema → budget → freshness → dedup
  3. Concise outputs — counts, anomalies, and suggested_next actions
  4. Pausable queue — agent or operator can pause/resume
  5. Self-correcting — on rejection, response includes valid_options

Import rules:
  - agent_interface/ imports from collectors/, storage/, and backend/
"""
