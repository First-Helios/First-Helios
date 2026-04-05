"""
tests/HeliosDeployment/test_metadata_quality.py — Dev Req §5: Data Quality Requirements

Validates:
    §5.1 — All 5 SpiritPool tables registered in meta_table_catalog
    §5.1 — All columns registered in meta_column_catalog
    §5.1 — Data lineage entries exist for all new flows
    §5.2 — Data contracts exist in docs/contracts/
"""

import os
from pathlib import Path

from core.metadata import MetaColumnCatalog, MetaDataLineage, MetaTableCatalog

_PROJECT_ROOT = Path(__file__).parent.parent.parent

# The 5 SpiritPool tables that must be fully registered
_SPIRITPOOL_TABLES = {"sp_events", "quarantine", "session_epochs", "burn_pool", "contributors"}


class TestMetadataRegistration:
    """Dev Req §5.1 — Every SpiritPool table has metadata entries."""

    def test_all_tables_in_meta_table_catalog(self, db):
        """All 5 tables registered in meta_table_catalog."""
        registered = {
            row.table_name
            for row in db.query(MetaTableCatalog).filter(
                MetaTableCatalog.table_name.in_(_SPIRITPOOL_TABLES)
            ).all()
        }
        missing = _SPIRITPOOL_TABLES - registered
        assert not missing, f"Tables missing from meta_table_catalog: {missing}"

    def test_all_tables_have_layer(self, db):
        """Every registered table has a non-empty layer assignment."""
        for row in db.query(MetaTableCatalog).filter(
            MetaTableCatalog.table_name.in_(_SPIRITPOOL_TABLES)
        ).all():
            assert row.layer, f"{row.table_name} has no layer"

    def test_all_tables_have_purpose(self, db):
        """Every registered table has a non-empty purpose."""
        for row in db.query(MetaTableCatalog).filter(
            MetaTableCatalog.table_name.in_(_SPIRITPOOL_TABLES)
        ).all():
            assert row.purpose, f"{row.table_name} has no purpose"

    def test_sp_events_columns_documented(self, db):
        """sp_events: all columns have meta_column_catalog entries."""
        from core.models.spiritpool import SpEvent

        orm_columns = {c.name for c in SpEvent.__table__.columns}
        documented = {
            row.column_name
            for row in db.query(MetaColumnCatalog).filter_by(table_name="sp_events").all()
        }
        missing = orm_columns - documented
        assert not missing, f"sp_events columns missing from catalog: {missing}"

    def test_quarantine_columns_documented(self, db):
        """quarantine: all columns have meta_column_catalog entries."""
        from core.models.spiritpool import Quarantine

        orm_columns = {c.name for c in Quarantine.__table__.columns}
        documented = {
            row.column_name
            for row in db.query(MetaColumnCatalog).filter_by(table_name="quarantine").all()
        }
        missing = orm_columns - documented
        assert not missing, f"quarantine columns missing from catalog: {missing}"

    def test_session_epochs_columns_documented(self, db):
        """session_epochs: all columns have meta_column_catalog entries."""
        from core.models.spiritpool import SessionEpoch

        orm_columns = {c.name for c in SessionEpoch.__table__.columns}
        documented = {
            row.column_name
            for row in db.query(MetaColumnCatalog).filter_by(table_name="session_epochs").all()
        }
        missing = orm_columns - documented
        assert not missing, f"session_epochs columns missing from catalog: {missing}"

    def test_burn_pool_columns_documented(self, db):
        """burn_pool: all columns have meta_column_catalog entries."""
        from core.models.spiritpool import BurnPool

        orm_columns = {c.name for c in BurnPool.__table__.columns}
        documented = {
            row.column_name
            for row in db.query(MetaColumnCatalog).filter_by(table_name="burn_pool").all()
        }
        missing = orm_columns - documented
        assert not missing, f"burn_pool columns missing from catalog: {missing}"

    def test_contributors_columns_documented(self, db):
        """contributors: all columns have meta_column_catalog entries."""
        from core.models.spiritpool import Contributor

        orm_columns = {c.name for c in Contributor.__table__.columns}
        documented = {
            row.column_name
            for row in db.query(MetaColumnCatalog).filter_by(table_name="contributors").all()
        }
        missing = orm_columns - documented
        assert not missing, f"contributors columns missing from catalog: {missing}"


class TestDataLineage:
    """Dev Req §5.1 — Data lineage entries exist for all SpiritPool flows."""

    _EXPECTED_FLOWS = [
        ("spiritpool_post", "sp_events"),
        ("spiritpool_post", "quarantine"),
        ("sp_events", "session_epochs"),
        ("session_epochs", "contributors"),
        ("burn_endpoint", "burn_pool"),
        ("sp_events", "scores"),
    ]

    def test_all_lineage_entries_exist(self, db):
        """All expected source→target lineage entries are registered."""
        for source, target in self._EXPECTED_FLOWS:
            row = db.query(MetaDataLineage).filter_by(
                source_table=source, target_table=target
            ).filter(MetaDataLineage.deprecated_at.is_(None)).first()
            assert row is not None, f"Missing lineage: {source} → {target}"

    def test_lineage_has_description(self, db):
        """All lineage entries have a non-empty description."""
        for source, target in self._EXPECTED_FLOWS:
            row = db.query(MetaDataLineage).filter_by(
                source_table=source, target_table=target
            ).filter(MetaDataLineage.deprecated_at.is_(None)).first()
            if row:
                assert row.description, f"Lineage {source}→{target} has no description"


class TestDataContracts:
    """Dev Req §5.2 — Data contracts exist in docs/contracts/."""

    _EXPECTED_CONTRACTS = [
        "sp_events_contract.md",
        "quarantine_contract.md",
        "session_epochs_contract.md",
        "burn_pool_contract.md",
    ]

    def test_contract_files_exist(self):
        """All required data contract files exist."""
        contracts_dir = _PROJECT_ROOT / "docs" / "contracts"
        for filename in self._EXPECTED_CONTRACTS:
            path = contracts_dir / filename
            assert path.exists(), f"Missing contract: {path}"

    def test_contracts_not_empty(self):
        """All contract files have content (> 100 bytes)."""
        contracts_dir = _PROJECT_ROOT / "docs" / "contracts"
        for filename in self._EXPECTED_CONTRACTS:
            path = contracts_dir / filename
            if path.exists():
                size = path.stat().st_size
                assert size > 100, f"Contract {filename} is too small ({size} bytes)"
