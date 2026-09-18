BEGIN;

-- Running upgrade 91f4c2a7d6e8 -> b72e6a90c431

CREATE FUNCTION bronze.capture_business_key(p_id bigint)
        RETURNS jsonb LANGUAGE sql STABLE AS $$
            SELECT jsonb_build_array(
                'capture-v1', s.namespace, coalesce(e.canonical_uri, ''),
                to_char(c.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
                coalesce(c.content_hash, ''), c.outcome, coalesce(c.bundle_path, '')
            )
            FROM bronze.capture c
            JOIN bronze.source s ON s.id = c.source_id
            LEFT JOIN bronze.source_endpoint e ON e.id = c.source_endpoint_id
            WHERE c.id = p_id
        $$;

CREATE FUNCTION bronze.record_version_info(p_id bigint)
        RETURNS TABLE (
            id bigint, source_record_id bigint, capture_id bigint,
            observed_at timestamptz, content_hash text,
            source_namespace text, external_key text, canonical_key jsonb
        ) LANGUAGE sql STABLE AS $$
            SELECT v.id, v.source_record_id, v.capture_id, v.observed_at,
                   v.content_hash::text, s.namespace::text, r.external_key::text,
                   jsonb_build_array(
                       'version-v1', s.namespace, r.external_key,
                       to_char(v.observed_at AT TIME ZONE 'UTC',
                               'YYYY-MM-DD"T"HH24:MI:SS.US'),
                       v.content_hash,
                       coalesce(bronze.capture_business_key(v.capture_id), '[]'::jsonb)
                   )
            FROM bronze.source_record_version v
            JOIN bronze.source_record r ON r.id = v.source_record_id
            JOIN bronze.source s ON s.id = r.source_id
            WHERE v.id = p_id
        $$;

CREATE FUNCTION bronze.evidence_info(p_id bigint)
        RETURNS TABLE (
            id bigint, source_record_version_id bigint, capture_id bigint,
            locator text, excerpt_hash text, canonical_key jsonb
        ) LANGUAGE sql STABLE AS $$
            SELECT e.id, e.source_record_version_id, e.capture_id,
                   e.locator, e.excerpt_hash::text,
                   jsonb_build_array(
                       'evidence-v1',
                       CASE WHEN e.source_record_version_id IS NOT NULL
                            THEN (SELECT v.canonical_key
                                  FROM bronze.record_version_info(
                                      e.source_record_version_id) v)
                            ELSE bronze.capture_business_key(e.capture_id) END,
                       e.locator, e.excerpt_hash
                   )
            FROM bronze.evidence e WHERE e.id = p_id
        $$;

CREATE FUNCTION bronze.evidence_supports_version(p_evidence bigint, p_version bigint)
        RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT EXISTS (
                SELECT 1 FROM bronze.evidence e
                CROSS JOIN bronze.source_record_version v
                WHERE e.id = p_evidence AND v.id = p_version
                  AND (e.source_record_version_id = v.id
                       OR e.capture_id = v.capture_id)
            )
        $$;

CREATE FUNCTION identity.scope_dependencies(p_subjects bigint[])
        RETURNS bigint[] LANGUAGE sql STABLE AS $$
            SELECT coalesce(array_agg(d.id ORDER BY d.id), ARRAY[]::bigint[])
            FROM (
                SELECT unnest(p_subjects) AS id
                UNION
                SELECT e.organization_subject_id FROM identity.establishment e
                WHERE e.subject_id = ANY(p_subjects)
                UNION
                SELECT e.place_subject_id FROM identity.establishment e
                WHERE e.subject_id = ANY(p_subjects)
            ) d
        $$;

CREATE FUNCTION identity.subject_feature_ready(p_subject bigint)
        RETURNS boolean LANGUAGE plpgsql STABLE AS $$
        DECLARE
            subject_kind text;
            parent record;
        BEGIN
            SELECT s.kind INTO subject_kind
            FROM identity.subject s
            JOIN identity.subject_currentness c ON c.subject_id = s.id
            WHERE s.id = p_subject AND c.is_current;
            IF subject_kind = 'place' THEN
                -- Exactly Python str.strip() whitespace, including Unicode.
                -- Root readiness is intentionally absent: promotion starts provisional.
                RETURN EXISTS (
                    SELECT 1 FROM identity.place p WHERE p.subject_id = p_subject
                    AND (length(btrim(p.address,
                        U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000')) > 0
                         OR (p.latitude IS NOT NULL AND p.longitude IS NOT NULL))
                );
            ELSIF subject_kind = 'organization' THEN
                RETURN EXISTS (
                    SELECT 1 FROM identity.organization o
                    WHERE o.subject_id = p_subject
                      AND o.canonical_name IS NOT NULL AND o.name_fingerprint IS NOT NULL
                      AND EXISTS (SELECT 1 FROM identity.current_resolution r
                                  WHERE r.subject_id = p_subject AND r.state = 'resolved')
                );
            ELSIF subject_kind = 'establishment' THEN
                SELECT e.organization_subject_id AS organization_id,
                       e.place_subject_id AS place_id INTO parent
                FROM identity.establishment e WHERE e.subject_id = p_subject;
                IF NOT FOUND THEN RETURN false; END IF;
                RETURN (SELECT count(*) = 2 FROM identity.subject s
                        WHERE s.id IN (parent.organization_id, parent.place_id)
                          AND s.readiness = 'eligible')
                    AND identity.subject_feature_ready(parent.organization_id)
                    AND identity.subject_feature_ready(parent.place_id);
            END IF;
            RETURN false;
        END
        $$;

CREATE FUNCTION identity.has_pending_lineage(p_subjects bigint[])
        RETURNS boolean LANGUAGE sql STABLE AS $$
            SELECT EXISTS (
                SELECT 1 FROM identity.subject_change_member m
                WHERE m.subject_id = ANY(p_subjects) AND m.role = 'input'
                  AND NOT EXISTS (SELECT 1 FROM identity.applied_subject_change a
                                  WHERE a.subject_change_id = m.subject_change_id)
            )
        $$;

CREATE FUNCTION identity.lock_scope_inputs(p_subjects bigint[], p_records bigint[])
        RETURNS bigint[] LANGUAGE plpgsql VOLATILE AS $$
        DECLARE
            dependencies bigint[];
            records bigint[];
            member record;
        BEGIN
            IF p_subjects IS NULL OR p_records IS NULL
               OR array_ndims(p_subjects) > 1 OR array_ndims(p_records) > 1
               OR EXISTS (SELECT 1 FROM unnest(p_subjects || p_records) i
                          WHERE i IS NULL OR i <= 0) THEN
                RAISE EXCEPTION 'scope lock inputs must be one-dimensional positive IDs'
                    USING ERRCODE = '22023';
            END IF;
            PERFORM pg_advisory_xact_lock_shared(48454, 2);
            dependencies := identity.scope_dependencies(p_subjects);
            PERFORM s.id FROM identity.subject s WHERE s.id = ANY(dependencies)
                ORDER BY s.id FOR NO KEY UPDATE;
            PERFORM c.subject_id FROM identity.subject_currentness c
                WHERE c.subject_id = ANY(dependencies)
                ORDER BY c.subject_id FOR NO KEY UPDATE;
            FOR member IN SELECT s.id, s.kind FROM identity.subject s
                          WHERE s.id = ANY(dependencies) ORDER BY s.id
            LOOP
                CASE member.kind
                    WHEN 'place' THEN
                        PERFORM p.subject_id FROM identity.place p
                            WHERE p.subject_id = member.id FOR NO KEY UPDATE;
                    WHEN 'organization' THEN
                        PERFORM o.subject_id FROM identity.organization o
                            WHERE o.subject_id = member.id FOR NO KEY UPDATE;
                    WHEN 'establishment' THEN
                        PERFORM e.subject_id FROM identity.establishment e
                            WHERE e.subject_id = member.id FOR NO KEY UPDATE;
                END CASE;
            END LOOP;
            IF dependencies IS DISTINCT FROM identity.scope_dependencies(p_subjects) THEN
                RAISE EXCEPTION 'scope dependencies changed; retry the whole transaction'
                    USING ERRCODE = '40001';
            END IF;
            SELECT coalesce(array_agg(r.id ORDER BY r.id), ARRAY[]::bigint[])
            INTO records FROM (
                SELECT unnest(p_records) AS id
                UNION
                SELECT c.source_record_id FROM identity.current_resolution c
                JOIN identity.organization o ON o.subject_id = c.subject_id
                WHERE c.subject_id = ANY(dependencies) AND c.state = 'resolved'
            ) r;
            PERFORM r.id FROM bronze.source_record r WHERE r.id = ANY(records)
                ORDER BY r.id FOR NO KEY UPDATE;
            -- Resolution transitions lock Subjects/Records without necessarily
            -- updating them. Lock the mutable proofs too so REPEATABLE READ and
            -- SERIALIZABLE abort on a projection changed since their snapshot.
            PERFORM c.source_record_id FROM identity.current_resolution c
                WHERE c.source_record_id = ANY(records)
                ORDER BY c.source_record_id FOR NO KEY UPDATE;
            -- Subject locks fence new/remapped readiness proofs. Revalidate the
            -- chosen proof set instead of acquiring additional out-of-order locks.
            IF EXISTS (
                SELECT 1 FROM identity.current_resolution c
                JOIN identity.organization o ON o.subject_id = c.subject_id
                WHERE c.subject_id = ANY(dependencies) AND c.state = 'resolved'
                  AND NOT c.source_record_id = ANY(records)
            ) THEN
                RAISE EXCEPTION 'scope proof set changed; retry the whole transaction'
                    USING ERRCODE = '40001';
            END IF;
            RETURN dependencies;
        END
        $$;

CREATE FUNCTION identity.require_resolved_scopes(
            p_subjects bigint[], p_records bigint[], p_events bigint[])
        RETURNS TABLE (
            subject_id bigint, kind text, source_record_id bigint, resolution_event_id bigint,
            organization_subject_id bigint, place_subject_id bigint,
            valid_from timestamptz, valid_to timestamptz, operating_status text
        ) LANGUAGE plpgsql VOLATILE AS $$
        DECLARE
            dependencies bigint[];
            request record;
        BEGIN
            IF p_subjects IS NULL OR p_records IS NULL OR p_events IS NULL
               OR cardinality(p_subjects) = 0
               OR cardinality(p_subjects) <> cardinality(p_records)
               OR cardinality(p_subjects) <> cardinality(p_events)
               OR array_ndims(p_subjects) <> 1 OR array_ndims(p_records) <> 1
               OR array_ndims(p_events) <> 1
               OR EXISTS (SELECT 1 FROM unnest(p_subjects || p_records || p_events) i
                          WHERE i IS NULL OR i <= 0) THEN
                RAISE EXCEPTION 'scope requests require equally sized nonempty positive ID arrays'
                    USING ERRCODE = '22023';
            END IF;
            dependencies := identity.lock_scope_inputs(p_subjects, p_records);
            IF identity.has_pending_lineage(dependencies) THEN
                RAISE EXCEPTION 'scope has unapplied lineage input membership'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_resolved_scope_admission';
            END IF;
            FOR request IN SELECT * FROM unnest(p_subjects, p_records, p_events)
                           AS r(subject_id, record_id, event_id)
            LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM identity.subject s
                    JOIN identity.current_resolution c ON c.subject_id = s.id
                    JOIN identity.resolution_event e ON e.id = c.last_event_id
                    WHERE s.id = request.subject_id
                      AND s.kind IN ('organization', 'establishment')
                      AND s.readiness = 'eligible'
                      AND identity.subject_feature_ready(s.id)
                      AND c.source_record_id = request.record_id AND c.state = 'resolved'
                      AND c.last_event_id = request.event_id
                      AND e.source_record_id = request.record_id
                      AND e.to_subject_id = request.subject_id
                      AND e.created_transaction_id <> txid_current()
                ) THEN
                    RAISE EXCEPTION 'scope is not eligible with the exact current record/event'
                        USING ERRCODE = '23514', CONSTRAINT = 'ck_resolved_scope_admission';
                END IF;
            END LOOP;
            RETURN QUERY
                SELECT s.id, s.kind::text, r.record_id, r.event_id,
                       e.organization_subject_id, e.place_subject_id,
                       e.valid_from, e.valid_to, e.operating_status::text
                FROM unnest(p_subjects, p_records, p_events) WITH ORDINALITY
                     AS r(subject_id, record_id, event_id, ordinal)
                JOIN identity.subject s ON s.id = r.subject_id
                LEFT JOIN identity.establishment e ON e.subject_id = s.id
                ORDER BY r.ordinal;
        END
        $$;

UPDATE public.alembic_version SET version_num='b72e6a90c431' WHERE public.alembic_version.version_num = '91f4c2a7d6e8';

COMMIT;
