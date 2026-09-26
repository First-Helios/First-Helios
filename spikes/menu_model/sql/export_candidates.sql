-- Menu-model spike, step A: export ~150 candidate venues as CSV. READ-ONLY.
--
-- Runs inside a READ ONLY transaction that is rolled back; it cannot write.
-- Output columns:
--   gers_id, name, primary_category, alternate_categories, overture_confidence,
--   website, website_source, menu_url, menu_url_signal
--
-- Selection (deterministic, seeded by a fixed string so a re-run gives the same rows):
--   * current, resolved Establishments seeded from Overture (latest Overture version),
--   * with a website (resolved `website-resolution` record, else Overture's first website),
--   * at most 2 venues per website host (so one chain or one platform can't dominate),
--   * at most 12 venues per Overture primary category (spread across cuisines/formats),
--   * then 150 rows in a stable pseudo-random order.
-- menu_url is filled only where a `menu-url-discovery` record exists (likely none yet).

BEGIN TRANSACTION READ ONLY;

WITH overture_latest AS (
    SELECT DISTINCT ON (sr.external_key)
        sr.external_key AS gers_id,
        srv.source_payload AS p
    FROM bronze.source AS s
    JOIN bronze.source_record AS sr ON sr.source_id = s.id
    JOIN bronze.source_record_version AS srv ON srv.source_record_id = sr.id
    JOIN identity.current_resolution AS cr
        ON cr.source_record_id = sr.id AND cr.state = 'resolved'
    JOIN identity.establishment AS e ON e.subject_id = cr.subject_id
    JOIN identity.subject_currentness AS sc
        ON sc.subject_id = e.subject_id AND sc.is_current
    WHERE s.namespace = 'overture'
    ORDER BY sr.external_key, srv.observed_at DESC, srv.id DESC
),

website_latest AS (
    SELECT DISTINCT ON (sr.external_key)
        sr.external_key AS gers_id,
        srv.source_payload ->> 'website' AS website
    FROM bronze.source AS s
    JOIN bronze.source_record AS sr ON sr.source_id = s.id
    JOIN bronze.source_record_version AS srv ON srv.source_record_id = sr.id
    JOIN identity.current_resolution AS cr
        ON cr.source_record_id = sr.id AND cr.state = 'resolved'
    WHERE s.namespace = 'website-resolution'
    ORDER BY sr.external_key, srv.observed_at DESC, srv.id DESC
),

menu_latest AS (
    SELECT DISTINCT ON (sr.external_key)
        sr.external_key AS gers_id,
        srv.source_payload ->> 'menu_url' AS menu_url,
        srv.source_payload ->> 'signal' AS menu_url_signal
    FROM bronze.source AS s
    JOIN bronze.source_record AS sr ON sr.source_id = s.id
    JOIN bronze.source_record_version AS srv ON srv.source_record_id = sr.id
    JOIN identity.current_resolution AS cr
        ON cr.source_record_id = sr.id AND cr.state = 'resolved'
    WHERE s.namespace = 'menu-url-discovery'
    ORDER BY sr.external_key, srv.observed_at DESC, srv.id DESC
),

venues AS (
    SELECT
        o.gers_id,
        o.p ->> 'name' AS name,
        o.p ->> 'primary_category' AS primary_category,
        CASE
            WHEN jsonb_typeof(o.p -> 'alternate_categories') = 'array'
                THEN (
                    SELECT string_agg(c, '|')
                    FROM jsonb_array_elements_text(o.p -> 'alternate_categories') AS c
                )
        END AS alternate_categories,
        o.p ->> 'confidence' AS overture_confidence,
        COALESCE(
            w.website,
            CASE
                WHEN jsonb_typeof(o.p -> 'websites') = 'array' THEN o.p -> 'websites' ->> 0
            END
        ) AS website,
        CASE WHEN w.website IS NOT NULL THEN 'website-resolution' ELSE 'overture' END
            AS website_source,
        m.menu_url,
        m.menu_url_signal
    FROM overture_latest AS o
    LEFT JOIN website_latest AS w ON w.gers_id = o.gers_id
    LEFT JOIN menu_latest AS m ON m.gers_id = o.gers_id
),

ranked AS (
    SELECT
        v.*,
        md5(v.gers_id || ':menu-model-spike') AS sort_key,
        lower(regexp_replace(
            substring(v.website FROM '^[A-Za-z][A-Za-z0-9+.-]*://([^/:?#]+)'),
            '^www\.', ''
        )) AS host
    FROM venues AS v
    WHERE v.website IS NOT NULL AND v.website <> ''
),

host_capped AS (
    SELECT
        r.*,
        row_number() OVER (PARTITION BY r.host ORDER BY r.sort_key) AS host_rank
    FROM ranked AS r
    WHERE r.host IS NOT NULL
),

capped AS (
    SELECT
        h.*,
        row_number() OVER (PARTITION BY h.primary_category ORDER BY h.sort_key) AS category_rank
    FROM host_capped AS h
    WHERE h.host_rank <= 2
)

SELECT
    gers_id,
    name,
    primary_category,
    alternate_categories,
    overture_confidence,
    website,
    website_source,
    menu_url,
    menu_url_signal
FROM capped
WHERE category_rank <= 12
ORDER BY sort_key
LIMIT 150;

ROLLBACK;
