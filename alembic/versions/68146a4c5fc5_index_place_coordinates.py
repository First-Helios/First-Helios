"""Index Place coordinates for the venue list's area filter.

ADR-0018 §A3, owner decision Q2. One btree on ``identity.place (latitude,
longitude)``, so ``GET /v1/venues?area=...`` (a 0.01° cell range on the Place
point) is index-backed. Index only: no column, constraint or data change.

Revision ID: 68146a4c5fc5
Revises: db40e9424cba
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "68146a4c5fc5"
down_revision: str | Sequence[str] | None = "db40e9424cba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_place_latitude_longitude",
        "place",
        ["latitude", "longitude"],
        unique=False,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("ix_place_latitude_longitude", table_name="place", schema="identity")
