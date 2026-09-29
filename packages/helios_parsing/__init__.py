"""Pure menu-page parsing stages (ADR-0013 §2): text in, plain data out.

No SQLAlchemy and no ``helios_core`` imports (enforced by the import-boundary
test). Ported from the menu-model spike as ADR-0013 slices land; the page
classifier's features came first (ADR-0013 Amendment 1).
"""
