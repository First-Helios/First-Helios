BEGIN;

-- Running downgrade 5a91ef3ff9d8 -> c91a6f02de73

DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM bronze.discovery_release_completion)
         OR EXISTS (SELECT 1 FROM bronze.discovery_lifecycle_state) THEN
        RAISE EXCEPTION 'ADR-0012: populated lifecycle history cannot be downgraded';
      END IF;
    END $$;

DROP INDEX bronze.ix_discovery_lifecycle_subject;

DROP INDEX bronze.ix_discovery_lifecycle_record;

DROP TABLE bronze.discovery_lifecycle_state;

DROP INDEX bronze.ix_discovery_completion_coverage_release;

DROP TABLE bronze.discovery_release_completion;

DROP FUNCTION bronze.reject_discovery_truncate();

UPDATE public.alembic_version SET version_num='c91a6f02de73' WHERE public.alembic_version.version_num = '5a91ef3ff9d8';

COMMIT;
