"""Gold read models: rebuildable consumer projections over accepted Silver.

Gold is never an authoritative write target (ADR-0004). The projection
``gold.current_menu`` materializes the accepted Menu selector's result so reads
do not recompute selection per request; it is rebuilt from Identity + Menu
(+ Bronze provenance) without mutating them (ADR-0006).

This package exports the model (``CurrentMenu``) and the bounded per-scope
rebuild (``refresh_current_menu``). The whole-catalog rebuild,
``refresh_full_catalog``, is imported from :mod:`packages.helios_core.gold.catalog`.
"""

from __future__ import annotations

from packages.helios_core.gold.models import CurrentMenu
from packages.helios_core.gold.refresh import refresh_current_menu

__all__ = ["CurrentMenu", "refresh_current_menu"]
