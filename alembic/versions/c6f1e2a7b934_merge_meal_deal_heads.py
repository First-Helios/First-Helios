"""merge meal deal heads

Revision ID: c6f1e2a7b934
Revises: b3d2e1f0a9c8, 9ac3d7b5f112
Create Date: 2026-04-16 23:55:00.000000
"""

from typing import Sequence, Union


revision: str = "c6f1e2a7b934"
down_revision: Union[str, Sequence[str], None] = ("b3d2e1f0a9c8", "9ac3d7b5f112")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass