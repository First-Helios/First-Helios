"""Add the Gold price-index aggregate.

Creates ``gold.price_index`` (ADR-0007, Amendment 1): venue-weighted price
percentiles per lat/lon grid cell, category and currency, rebuilt from
``gold.current_menu``. Gold is rebuildable: downgrade drops the table and never
touches Bronze, Identity, Menu or ``gold.current_menu``. The only FK references
``menu.currency`` with ``RESTRICT``; no authoritative table references Gold.

Revision ID: 7c2e4b9d1f3a
Revises: 5a91ef3ff9d8
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c2e4b9d1f3a"
down_revision: str | Sequence[str] | None = "5a91ef3ff9d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE gold.price_index (
    id BIGSERIAL NOT NULL,
    area_kind VARCHAR(32) NOT NULL,
    area_key VARCHAR(64) NOT NULL,
    cell_lat NUMERIC(9, 6) NOT NULL,
    cell_lon NUMERIC(9, 6) NOT NULL,
    category_kind VARCHAR(32) NOT NULL,
    category_key VARCHAR(128) NOT NULL,
    currency_code VARCHAR(3) NOT NULL,
    effective_instant TIMESTAMP WITH TIME ZONE NOT NULL,
    venue_count INTEGER NOT NULL,
    organization_venue_count INTEGER NOT NULL,
    priced_count INTEGER NOT NULL,
    unpriced_count INTEGER NOT NULL,
    min_venues INTEGER NOT NULL,
    low_sample BOOLEAN NOT NULL,
    p25_minor BIGINT,
    median_minor BIGINT,
    p75_minor BIGINT,
    min_minor BIGINT,
    max_minor BIGINT,
    oldest_observed_at TIMESTAMP WITH TIME ZONE,
    newest_observed_at TIMESTAMP WITH TIME ZONE,
    refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_gold_price_index UNIQUE (area_kind, area_key, category_kind, category_key, currency_code),
    CONSTRAINT fk_gold_price_index_currency FOREIGN KEY(currency_code) REFERENCES menu.currency (code) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_gold_price_index_area_kind CHECK (area_kind IN ('latlon_grid_0p01')),
    CONSTRAINT ck_gold_price_index_category_kind CHECK (category_kind IN ('all')),
    CONSTRAINT ck_gold_price_index_cell CHECK (cell_lat BETWEEN -90 AND 90 AND cell_lon BETWEEN -180 AND 180),
    CONSTRAINT ck_gold_price_index_currency CHECK (currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_gold_price_index_counts CHECK (venue_count >= 0 AND organization_venue_count BETWEEN 0 AND venue_count AND priced_count >= venue_count AND unpriced_count >= 0 AND priced_count + unpriced_count > 0 AND min_venues >= 1),
    CONSTRAINT ck_gold_price_index_stats CHECK ((venue_count = 0 AND num_nulls(p25_minor, median_minor, p75_minor, min_minor, max_minor, oldest_observed_at, newest_observed_at) = 7) OR (venue_count > 0 AND num_nulls(p25_minor, median_minor, p75_minor, min_minor, max_minor, oldest_observed_at, newest_observed_at) = 0 AND 0 <= min_minor AND min_minor <= p25_minor AND p25_minor <= median_minor AND median_minor <= p75_minor AND p75_minor <= max_minor AND oldest_observed_at <= newest_observed_at)),
    CONSTRAINT ck_gold_price_index_low CHECK (low_sample = (venue_count < min_venues)),
    CONSTRAINT ck_gold_price_index_times CHECK (isfinite(effective_instant) AND isfinite(refreshed_at) AND (oldest_observed_at IS NULL OR isfinite(oldest_observed_at)) AND (newest_observed_at IS NULL OR isfinite(newest_observed_at)))
)
    """)
    op.execute("""
CREATE INDEX ix_gold_price_index_currency ON gold.price_index (currency_code)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE gold.price_index")
