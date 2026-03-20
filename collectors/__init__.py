"""
collectors — Stateless data collection functions.

Each collector takes a config dict and returns a list of typed dataclasses
from collectors.schema. No database imports. No SQLAlchemy. No side effects.

Import rules:
  - collectors/ may NOT import from backend/, storage/, or agent_interface/
"""
