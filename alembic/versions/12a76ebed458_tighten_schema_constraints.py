"""Tighten Bronze, Identity and Gold constraints to match the Python contracts.

One batch of low-risk constraints from the 2026-09-22 review (S14: R53, R54,
R56, R60, R63, R69). Nothing is dropped or retyped and no row is rewritten:

- Bronze rejects TRUNCATE and every UPDATE, not just the listed key columns.
- Text CHECKs trim the whitespace Python's ``str.strip()`` trims instead of
  ASCII spaces only (``bronze.whitespace()``, the same set as
  ``menu.whitespace()``; Bronze and Identity sit below Menu, so they get their
  own copy rather than depend on it).
- ``source.kind``, ``endpoint_kind`` and ``capture.outcome`` must be nonblank
  and trimmed; Bronze timestamps must be finite.
- An Organization name must contain something other than whitespace and
  zero-width characters.
- Gold ``staleness_seconds`` cannot be negative.

Every new or replaced CHECK validates existing rows when it is added; run
``docs/reviews/sql/2026-09-22-s14-schema-tightening-precheck.sql`` against a
database with data first. Downgrade restores the previous definitions.

Revision ID: 12a76ebed458
Revises: 5f3a9c1e7b24
Create Date: 2026-09-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "12a76ebed458"
down_revision: str | Sequence[str] | None = "5f3a9c1e7b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BRONZE_TABLES = (
    "source",
    "source_endpoint",
    "source_record",
    "capture",
    "source_record_version",
    "evidence",
)

# Triggers that pinned only some columns before this revision.
PINNED_COLUMNS = {
    "source": ("namespace",),
    "source_endpoint": ("source_id", "canonical_uri"),
    "source_record": ("source_id", "external_key"),
}

WS = "bronze.whitespace()"
INVISIBLE = "U&'\\200B\\200C\\200D\\2060\\FEFF'"

# (table, constraint, previous definition, new definition). Names are kept so a
# reviewer sees the same constraint with a Unicode-aware trim.
REPLACED_CHECKS = (
    (
        "bronze.source",
        "ck_source_namespace_canonical",
        "namespace = btrim(namespace) AND length(namespace) > 0",
        f"namespace = btrim(namespace, {WS}) AND length(namespace) > 0",
    ),
    (
        "bronze.source_endpoint",
        "ck_source_endpoint_uri_canonical",
        "canonical_uri = btrim(canonical_uri) AND length(canonical_uri) > 0",
        f"canonical_uri = btrim(canonical_uri, {WS}) AND length(canonical_uri) > 0",
    ),
    (
        "bronze.source_record",
        "ck_source_record_external_key_canonical",
        "external_key = btrim(external_key) AND length(external_key) > 0",
        f"external_key = btrim(external_key, {WS}) AND length(external_key) > 0",
    ),
    (
        "bronze.capture",
        "ck_capture_content_hash_not_blank",
        "content_hash IS NULL OR length(btrim(content_hash)) > 0",
        f"content_hash IS NULL OR length(btrim(content_hash, {WS})) > 0",
    ),
    (
        "bronze.capture",
        "ck_capture_bundle_path_not_blank",
        "bundle_path IS NULL OR length(btrim(bundle_path)) > 0",
        f"bundle_path IS NULL OR length(btrim(bundle_path, {WS})) > 0",
    ),
    (
        "bronze.source_record_version",
        "ck_source_record_version_content_hash_not_blank",
        "length(btrim(content_hash)) > 0",
        f"length(btrim(content_hash, {WS})) > 0",
    ),
    (
        "bronze.evidence",
        "ck_evidence_locator_not_blank",
        "length(btrim(locator)) > 0",
        f"length(btrim(locator, {WS})) > 0",
    ),
    (
        "bronze.evidence",
        "ck_evidence_excerpt_hash_not_blank",
        "length(btrim(excerpt_hash)) > 0",
        f"length(btrim(excerpt_hash, {WS})) > 0",
    ),
    (
        "identity.organization",
        "ck_organization_name_not_blank",
        "canonical_name IS NULL OR length(btrim(canonical_name)) > 0",
        f"canonical_name IS NULL OR length(btrim(canonical_name, {WS} || {INVISIBLE})) > 0",
    ),
    (
        "identity.organization",
        "ck_organization_fingerprint_not_blank",
        "name_fingerprint IS NULL OR length(btrim(name_fingerprint)) > 0",
        f"name_fingerprint IS NULL OR length(btrim(name_fingerprint, {WS})) > 0",
    ),
    (
        "identity.organization",
        "ck_organization_kind_not_blank",
        "organization_kind = btrim(organization_kind) AND length(organization_kind) > 0",
        f"organization_kind = btrim(organization_kind, {WS}) AND length(organization_kind) > 0",
    ),
    (
        "identity.subject_name",
        "ck_subject_name_not_blank",
        "name = btrim(name) AND length(name) > 0",
        f"name = btrim(name, {WS}) AND length(name) > 0",
    ),
    (
        "identity.subject_name",
        "ck_subject_name_fingerprint_not_blank",
        "name_fingerprint = btrim(name_fingerprint) AND length(name_fingerprint) > 0",
        f"name_fingerprint = btrim(name_fingerprint, {WS}) AND length(name_fingerprint) > 0",
    ),
    (
        "identity.adjudication",
        "ck_adjudication_actor_not_blank",
        "actor = btrim(actor) AND length(actor) > 0",
        f"actor = btrim(actor, {WS}) AND length(actor) > 0",
    ),
    (
        "identity.adjudication",
        "ck_adjudication_rationale_bounds",
        "rationale = btrim(rationale) AND length(rationale) > 0 AND length(rationale) <= 4000",
        f"rationale = btrim(rationale, {WS}) AND length(rationale) > 0"
        " AND length(rationale) <= 4000",
    ),
    *(
        (
            f"identity.{table}",
            f"ck_{table}_{column}_not_blank",
            f"{column} = btrim({column}) AND length({column}) > 0",
            f"{column} = btrim({column}, {WS}) AND length({column}) > 0",
        )
        for table in ("resolution_event", "subject_change")
        for column in ("method", "method_version")
    ),
)

ADDED_CHECKS = (
    ("bronze.source", "ck_source_kind_canonical", f"kind = btrim(kind, {WS}) AND length(kind) > 0"),
    (
        "bronze.source_endpoint",
        "ck_source_endpoint_kind_canonical",
        f"endpoint_kind = btrim(endpoint_kind, {WS}) AND length(endpoint_kind) > 0",
    ),
    (
        "bronze.capture",
        "ck_capture_outcome_canonical",
        f"outcome = btrim(outcome, {WS}) AND length(outcome) > 0",
    ),
    ("bronze.source_record", "ck_source_record_first_seen_finite", "isfinite(first_seen_at)"),
    ("bronze.capture", "ck_capture_fetched_at_finite", "isfinite(fetched_at)"),
    (
        "bronze.source_record_version",
        "ck_source_record_version_observed_at_finite",
        "isfinite(observed_at)",
    ),
    (
        "gold.current_menu",
        "ck_gold_staleness",
        "staleness_seconds IS NULL OR staleness_seconds >= 0",
    ),
)

PREVIOUS_MUTATION_FUNCTION = """
CREATE OR REPLACE FUNCTION bronze.reject_provenance_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    immutable_column text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '%.% is immutable and cannot be deleted',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;

    IF TG_NARGS = 0 THEN
        RAISE EXCEPTION '%.% is immutable and cannot be updated',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;

    FOREACH immutable_column IN ARRAY TG_ARGV LOOP
        IF to_jsonb(NEW) -> immutable_column
            IS DISTINCT FROM to_jsonb(OLD) -> immutable_column THEN
            RAISE EXCEPTION '%.%.% is immutable',
                TG_TABLE_SCHEMA, TG_TABLE_NAME, immutable_column
                USING ERRCODE = '55000';
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$
"""


def _row_trigger(table: str, *arguments: str) -> None:
    quoted = ", ".join(f"'{argument}'" for argument in arguments)
    op.execute(f"DROP TRIGGER trg_{table}_provenance_immutable ON bronze.{table}")
    op.execute(f"""
CREATE TRIGGER trg_{table}_provenance_immutable
BEFORE UPDATE OR DELETE ON bronze.{table}
FOR EACH ROW
EXECUTE FUNCTION bronze.reject_provenance_mutation({quoted})
    """)


def upgrade() -> None:
    op.execute("""
CREATE FUNCTION bronze.whitespace()
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT U&'\\0009\\000A\\000B\\000C\\000D\\001C\\001D\\001E\\001F\\0020\\0085\\00A0\\1680\\2000\\2001\\2002\\2003\\2004\\2005\\2006\\2007\\2008\\2009\\200A\\2028\\2029\\202F\\205F\\3000'
$$
    """)
    op.execute("""
CREATE OR REPLACE FUNCTION bronze.reject_provenance_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '%.% is immutable and cannot be %',
        TG_TABLE_SCHEMA, TG_TABLE_NAME,
        CASE TG_OP WHEN 'UPDATE' THEN 'updated' WHEN 'DELETE' THEN 'deleted' ELSE 'truncated' END
        USING ERRCODE = '55000';
END;
$$
    """)
    for table in PINNED_COLUMNS:
        _row_trigger(table)
    for table in BRONZE_TABLES:
        op.execute(f"""
CREATE TRIGGER trg_{table}_provenance_no_truncate
BEFORE TRUNCATE ON bronze.{table}
FOR EACH STATEMENT
EXECUTE FUNCTION bronze.reject_provenance_mutation()
        """)
    for table, name, _, definition in REPLACED_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({definition})")
    for table, name, definition in ADDED_CHECKS:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({definition})")


def downgrade() -> None:
    for table, name, _ in reversed(ADDED_CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    for table, name, previous, _ in reversed(REPLACED_CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({previous})")
    for table in reversed(BRONZE_TABLES):
        op.execute(f"DROP TRIGGER trg_{table}_provenance_no_truncate ON bronze.{table}")
    for table, columns in PINNED_COLUMNS.items():
        _row_trigger(table, *columns)
    op.execute(PREVIOUS_MUTATION_FUNCTION)
    op.execute("DROP FUNCTION bronze.whitespace()")
