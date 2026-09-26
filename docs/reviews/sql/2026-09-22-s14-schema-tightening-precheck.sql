-- S14 precheck: rows that would violate a CHECK added or tightened by
-- migration 12a76ebed458. Read-only; run before `alembic upgrade head` on any
-- database that has data (the Pi). Every count must be 0, or the upgrade
-- fails and rolls back without changing anything.
--
--   docker compose -f infra/docker-compose.yml exec -T postgres \
--     psql -U helios -d helios -f - < docs/reviews/sql/2026-09-22-s14-schema-tightening-precheck.sql
--
-- `ws` is Python's str.strip() whitespace, identical to bronze.whitespace();
-- the function doesn't exist until the migration runs, so it is inlined here.

WITH chars AS (
    SELECT
        U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000' AS ws,
        U&'\200B\200C\200D\2060\FEFF' AS invisible
)
SELECT check_name, violations FROM (
    SELECT 'bronze.source namespace/kind' AS check_name, count(*) AS violations
    FROM bronze.source, chars
    WHERE namespace <> btrim(namespace, ws) OR length(namespace) = 0
       OR kind <> btrim(kind, ws) OR length(kind) = 0
    UNION ALL
    SELECT 'bronze.source_endpoint canonical_uri/endpoint_kind', count(*)
    FROM bronze.source_endpoint, chars
    WHERE canonical_uri <> btrim(canonical_uri, ws) OR length(canonical_uri) = 0
       OR endpoint_kind <> btrim(endpoint_kind, ws) OR length(endpoint_kind) = 0
    UNION ALL
    SELECT 'bronze.source_record external_key/first_seen_at', count(*)
    FROM bronze.source_record, chars
    WHERE external_key <> btrim(external_key, ws) OR length(external_key) = 0
       OR NOT isfinite(first_seen_at)
    UNION ALL
    SELECT 'bronze.capture hash/path/outcome/fetched_at', count(*)
    FROM bronze.capture, chars
    WHERE (content_hash IS NOT NULL AND length(btrim(content_hash, ws)) = 0)
       OR (bundle_path IS NOT NULL AND length(btrim(bundle_path, ws)) = 0)
       OR outcome <> btrim(outcome, ws) OR length(outcome) = 0
       OR NOT isfinite(fetched_at)
    UNION ALL
    SELECT 'bronze.source_record_version content_hash/observed_at', count(*)
    FROM bronze.source_record_version, chars
    WHERE length(btrim(content_hash, ws)) = 0 OR NOT isfinite(observed_at)
    UNION ALL
    SELECT 'bronze.evidence locator/excerpt_hash', count(*)
    FROM bronze.evidence, chars
    WHERE length(btrim(locator, ws)) = 0 OR length(btrim(excerpt_hash, ws)) = 0
    UNION ALL
    SELECT 'identity.organization name/fingerprint/kind', count(*)
    FROM identity.organization, chars
    WHERE (canonical_name IS NOT NULL AND length(btrim(canonical_name, ws || invisible)) = 0)
       OR (name_fingerprint IS NOT NULL AND length(btrim(name_fingerprint, ws)) = 0)
       OR organization_kind <> btrim(organization_kind, ws) OR length(organization_kind) = 0
    UNION ALL
    SELECT 'identity.subject_name name/fingerprint', count(*)
    FROM identity.subject_name, chars
    WHERE name <> btrim(name, ws) OR length(name) = 0
       OR name_fingerprint <> btrim(name_fingerprint, ws) OR length(name_fingerprint) = 0
    UNION ALL
    SELECT 'identity.adjudication actor/rationale', count(*)
    FROM identity.adjudication, chars
    WHERE actor <> btrim(actor, ws) OR rationale <> btrim(rationale, ws)
    UNION ALL
    SELECT 'identity.resolution_event method/method_version', count(*)
    FROM identity.resolution_event, chars
    WHERE method <> btrim(method, ws) OR method_version <> btrim(method_version, ws)
    UNION ALL
    SELECT 'identity.subject_change method/method_version', count(*)
    FROM identity.subject_change, chars
    WHERE method <> btrim(method, ws) OR method_version <> btrim(method_version, ws)
    UNION ALL
    SELECT 'gold.current_menu staleness_seconds', count(*)
    FROM gold.current_menu
    WHERE staleness_seconds < 0
) AS results
ORDER BY check_name;
