BEGIN;

-- Running upgrade 7c2e4b9d1f3a -> db40e9424cba

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
$$;

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
$$;

CREATE FUNCTION menu.bump_generation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM set_config('helios_menu.generation',
        (coalesce(nullif(current_setting('helios_menu.generation', true), ''), '0')::bigint + 1)::text,
        true);
    RETURN NEW;
END
$$;

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
$$;

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.menu_page FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.menu_applicability FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.menu_section FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.menu_item FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.menu_variant FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.menu_modifier FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.price_observation FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

CREATE TRIGGER trg_menu_generation BEFORE INSERT ON menu.evidence_link FOR EACH ROW EXECUTE FUNCTION menu.bump_generation();

UPDATE public.alembic_version SET version_num='db40e9424cba' WHERE public.alembic_version.version_num = '7c2e4b9d1f3a';

COMMIT;
