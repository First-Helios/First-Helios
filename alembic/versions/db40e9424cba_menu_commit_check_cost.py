"""Make the Menu commit-time integrity check linear in page size.

ADR-0005 Amendment 1. Two function-level changes; no table, column or data
change:

1. ``menu.node(kind, id)`` reads one node by primary key, and ``menu.node_path``
   follows parent and base edges through it instead of joining every Menu node
   (``menu.nodes(NULL)``). Same signature and rows.
2. A ``BEFORE INSERT`` trigger on the eight Menu tables bumps a transaction-local
   generation counter. ``menu.check_integrity`` skips a page already checked at
   the current generation and records the generation after a successful check,
   so a page is checked once per aggregate state instead of once per row.

The check itself (``menu.check_aggregate``) is unchanged. Downgrade restores
the original ``node_path`` and ``check_integrity`` text from d83f0a21c592.

Revision ID: db40e9424cba
Revises: 7c2e4b9d1f3a
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "db40e9424cba"
down_revision: str | Sequence[str] | None = "7c2e4b9d1f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "menu_page",
    "menu_applicability",
    "menu_section",
    "menu_item",
    "menu_variant",
    "menu_modifier",
    "price_observation",
    "evidence_link",
)


def upgrade() -> None:
    op.execute("""
CREATE FUNCTION menu.node(p_kind text, p_id bigint)
RETURNS TABLE(kind text, id bigint, page_id bigint, parent_kind text, parent_id bigint,
              base_id bigint, applicability_id bigint, native_key text, effect text, support_kind text)
LANGUAGE sql STABLE AS $$
    SELECT 'section', id, page_id, 'section', parent_section_id, base_section_id,
           applicability_id, source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_section WHERE p_kind = 'section' AND id = p_id
    UNION ALL
    SELECT 'item', id, page_id, 'section', section_id, base_item_id,
           applicability_id, source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_item WHERE p_kind = 'item' AND id = p_id
    UNION ALL
    SELECT 'variant', id, page_id, 'item', item_id, base_variant_id,
           applicability_id, source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_variant WHERE p_kind = 'variant' AND id = p_id
    UNION ALL
    SELECT 'modifier', id, page_id, CASE WHEN item_id IS NOT NULL THEN 'item' ELSE 'section' END,
           coalesce(item_id, section_id), base_modifier_id, applicability_id,
           source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_modifier WHERE p_kind = 'modifier' AND id = p_id
$$
    """)
    # UNION (not UNION ALL) keeps one row when the parent and base edges name the
    # same node, as the original OR join did.
    op.execute("""
CREATE OR REPLACE FUNCTION menu.node_path(p_kind text, p_id bigint)
RETURNS TABLE(kind text, id bigint, page_id bigint, applicability_id bigint,
              native_key text, base_id bigint, effect text, depth integer, cycle boolean)
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE path AS (
        SELECT n.*, 0 AS depth, ARRAY[n.kind || ':' || n.id] AS visited, false AS cycle
        FROM menu.node(p_kind, p_id) n
        UNION ALL
        SELECT n.*, p.depth + 1, p.visited || (n.kind || ':' || n.id),
               (n.kind || ':' || n.id) = ANY(p.visited)
        FROM path p
        CROSS JOIN LATERAL (
            SELECT * FROM menu.node(p.parent_kind, p.parent_id)
            UNION
            SELECT * FROM menu.node(p.kind, p.base_id)
        ) n
        WHERE NOT p.cycle
    ) SELECT kind, id, page_id, applicability_id, native_key, base_id, effect, depth, cycle FROM path
$$
    """)
    # Any Menu insert in this transaction invalidates every page's memo, so a
    # skipped check always covers the complete aggregate. A savepoint rollback
    # restores both settings, which can only force an extra check.
    op.execute("""
CREATE FUNCTION menu.bump_generation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM set_config('helios_menu.generation',
        (coalesce(nullif(current_setting('helios_menu.generation', true), ''), '0')::bigint + 1)::text,
        true);
    RETURN NEW;
END
$$
    """)
    op.execute("""
CREATE OR REPLACE FUNCTION menu.check_integrity()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE page bigint; generation text;
BEGIN
    IF TG_TABLE_NAME = 'menu_page' THEN page := NEW.id; ELSE page := NEW.page_id; END IF;
    generation := coalesce(nullif(current_setting('helios_menu.generation', true), ''), '0');
    IF current_setting('helios_menu.checked_' || page, true) = generation THEN
        RETURN NULL;
    END IF;
    PERFORM menu.check_aggregate(page);
    PERFORM set_config('helios_menu.checked_' || page, generation, true);
    RETURN NULL;
END
$$
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.{table} "
            "FOR EACH ROW EXECUTE FUNCTION menu.bump_generation()"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TRIGGER trg_menu_generation ON menu.{table}")
    op.execute("""
CREATE OR REPLACE FUNCTION menu.check_integrity()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'menu_page' THEN PERFORM menu.check_aggregate(NEW.id);
    ELSE PERFORM menu.check_aggregate(NEW.page_id); END IF;
    RETURN NULL;
END
$$
    """)
    op.execute("DROP FUNCTION menu.bump_generation()")
    op.execute("""
CREATE OR REPLACE FUNCTION menu.node_path(p_kind text, p_id bigint)
RETURNS TABLE(kind text, id bigint, page_id bigint, applicability_id bigint,
              native_key text, base_id bigint, effect text, depth integer, cycle boolean)
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE path AS (
        SELECT n.*, 0 AS depth, ARRAY[n.kind || ':' || n.id] AS visited, false AS cycle
        FROM menu.nodes(NULL) n WHERE n.kind = p_kind AND n.id = p_id
        UNION ALL
        SELECT n.*, p.depth + 1, p.visited || (n.kind || ':' || n.id),
               (n.kind || ':' || n.id) = ANY(p.visited)
        FROM path p
        JOIN menu.nodes(NULL) n ON
            (n.kind = p.parent_kind AND n.id = p.parent_id)
            OR (n.kind = p.kind AND n.id = p.base_id)
        WHERE NOT p.cycle
    ) SELECT kind, id, page_id, applicability_id, native_key, base_id, effect, depth, cycle FROM path
$$
    """)
    op.execute("DROP FUNCTION menu.node(text, bigint)")
