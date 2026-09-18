BEGIN;

-- Running downgrade b72e6a90c431 -> 91f4c2a7d6e8

DROP FUNCTION identity.require_resolved_scopes(bigint[], bigint[], bigint[]);

DROP FUNCTION identity.lock_scope_inputs(bigint[], bigint[]);

DROP FUNCTION identity.has_pending_lineage(bigint[]);

DROP FUNCTION identity.subject_feature_ready(bigint);

DROP FUNCTION identity.scope_dependencies(bigint[]);

DROP FUNCTION bronze.evidence_supports_version(bigint, bigint);

DROP FUNCTION bronze.evidence_info(bigint);

DROP FUNCTION bronze.record_version_info(bigint);

DROP FUNCTION bronze.capture_business_key(bigint);

UPDATE public.alembic_version SET version_num='91f4c2a7d6e8' WHERE public.alembic_version.version_num = 'b72e6a90c431';

COMMIT;
