"""add_menu_graph_tables

Revision ID: a1b2c3d4e5f6
Revises: c6f1e2a7b934
Create Date: 2026-04-20 00:00:00.000000

Creates the 5 menu graph tables for FPI-1 (Food Price Index tab):
  menu_pages, menu_sections, menu_items, menu_price_points, menu_modifiers
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "c6f1e2a7b934"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "menu_pages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("renderer", sa.String(), nullable=True),
        sa.Column("source_bundle", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["restaurant_id"], ["local_employers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_menu_pages_restaurant_id"), "menu_pages", ["restaurant_id"], unique=False)

    op.create_table(
        "menu_sections",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("page_id", sa.String(), nullable=True),
        sa.Column("parent_section_id", sa.String(), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("path", sa.JSON(), nullable=True),
        sa.Column("service_period", sa.String(), nullable=True),
        sa.Column("course", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["page_id"], ["menu_pages.id"]),
        sa.ForeignKeyConstraint(["parent_section_id"], ["menu_sections.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["local_employers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_menu_sections_page_id"), "menu_sections", ["page_id"], unique=False)
    op.create_index(op.f("ix_menu_sections_restaurant_id"), "menu_sections", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_menu_sections_service_period"), "menu_sections", ["service_period"], unique=False)

    op.create_table(
        "menu_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("course", sa.String(), nullable=True),
        sa.Column("calories", sa.Integer(), nullable=True),
        sa.Column("dietary_tags", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["section_id"], ["menu_sections.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["local_employers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_menu_items_name"), "menu_items", ["name"], unique=False)
    op.create_index(op.f("ix_menu_items_course"), "menu_items", ["course"], unique=False)
    op.create_index(op.f("ix_menu_items_restaurant_id"), "menu_items", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_menu_items_section_id"), "menu_items", ["section_id"], unique=False)
    op.create_index("ix_menu_items_restaurant_course", "menu_items", ["restaurant_id", "course"], unique=False)

    op.create_table(
        "menu_price_points",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=True),
        sa.Column("section_id", sa.String(), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("variant", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["menu_items.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["menu_sections.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["local_employers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_menu_price_points_item_id"), "menu_price_points", ["item_id"], unique=False)
    op.create_index(op.f("ix_menu_price_points_price"), "menu_price_points", ["price"], unique=False)
    op.create_index(op.f("ix_menu_price_points_restaurant_id"), "menu_price_points", ["restaurant_id"], unique=False)
    op.create_index("ix_menu_price_points_restaurant_price", "menu_price_points", ["restaurant_id", "price"], unique=False)

    op.create_table(
        "menu_modifiers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=True),
        sa.Column("section_id", sa.String(), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("price_delta", sa.Float(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["menu_items.id"]),
        sa.ForeignKeyConstraint(["section_id"], ["menu_sections.id"]),
        sa.ForeignKeyConstraint(["restaurant_id"], ["local_employers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_menu_modifiers_restaurant_id"), "menu_modifiers", ["restaurant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_menu_modifiers_restaurant_id"), table_name="menu_modifiers")
    op.drop_table("menu_modifiers")

    op.drop_index("ix_menu_price_points_restaurant_price", table_name="menu_price_points")
    op.drop_index(op.f("ix_menu_price_points_restaurant_id"), table_name="menu_price_points")
    op.drop_index(op.f("ix_menu_price_points_price"), table_name="menu_price_points")
    op.drop_index(op.f("ix_menu_price_points_item_id"), table_name="menu_price_points")
    op.drop_table("menu_price_points")

    op.drop_index("ix_menu_items_restaurant_course", table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_section_id"), table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_restaurant_id"), table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_course"), table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_name"), table_name="menu_items")
    op.drop_table("menu_items")

    op.drop_index(op.f("ix_menu_sections_service_period"), table_name="menu_sections")
    op.drop_index(op.f("ix_menu_sections_restaurant_id"), table_name="menu_sections")
    op.drop_index(op.f("ix_menu_sections_page_id"), table_name="menu_sections")
    op.drop_table("menu_sections")

    op.drop_index(op.f("ix_menu_pages_restaurant_id"), table_name="menu_pages")
    op.drop_table("menu_pages")
