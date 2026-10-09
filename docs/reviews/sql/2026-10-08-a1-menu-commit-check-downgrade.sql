BEGIN;

-- Running downgrade db40e9424cba -> 7c2e4b9d1f3a

DROP TRIGGER trg_menu_generation ON menu.menu_page;

DROP TRIGGER trg_menu_generation ON menu.menu_applicability;

DROP TRIGGER trg_menu_generation ON menu.menu_section;

DROP TRIGGER trg_menu_generation ON menu.menu_item;

DROP TRIGGER trg_menu_generation ON menu.menu_variant;

DROP TRIGGER trg_menu_generation ON menu.menu_modifier;

DROP TRIGGER trg_menu_generation ON menu.price_observation;

DROP TRIGGER trg_menu_generation ON menu.evidence_link;

CREATE OR REPLACE FUNCTION menu.check_integrity()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'menu_page' THEN PERFORM menu.check_aggregate(NEW.id);
    ELSE PERFORM menu.check_aggregate(NEW.page_id); END IF;
    RETURN NULL;
END
$$;

DROP FUNCTION menu.bump_generation();

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
$$;

DROP FUNCTION menu.node(text, bigint);

UPDATE public.alembic_version SET version_num='7c2e4b9d1f3a' WHERE public.alembic_version.version_num = 'db40e9424cba';

COMMIT;
