"""
storage — Single-point-of-write for each data type.

Accepts typed records from collectors/ and upserts to the database.
Knows schema. Doesn't know where data came from.

Import rules:
  - storage/ imports from backend/database and collectors/schema only
  - Never called by agents directly — only by the orchestration layer
"""
