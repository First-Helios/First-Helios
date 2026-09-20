"""Gold read models: rebuildable consumer projections over accepted Silver.

Gold is never an authoritative write target (ADR-0004). The first projection,
``gold.current_menu``, materializes the accepted Menu selector's result for a
bounded set of scopes so reads do not recompute selection per request; it is
rebuilt from Identity + Menu (+ Bronze provenance) without mutating them
(ADR-0006).
"""

from __future__ import annotations

from packages.helios_core.gold.models import CurrentMenu
from packages.helios_core.gold.refresh import refresh_current_menu

__all__ = ["CurrentMenu", "refresh_current_menu"]
