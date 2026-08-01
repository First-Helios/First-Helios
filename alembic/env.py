from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.schema import SchemaItem

from alembic import context
from packages.helios_core.config import get_settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Use the same DATABASE_URL the app resolves, rather than alembic.ini's
# static value, so migrations target the same database as the app (CI,
# docker, future hosts).
config.set_main_option("sqlalchemy.url", get_settings().database_url)
# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from packages.helios_core.db import models  # noqa: F401 — registers models on Base.metadata
from packages.helios_core.db.base import MANAGED_SCHEMAS, VERSION_TABLE_SCHEMA, Base

target_metadata = Base.metadata


def include_object(
    schema_item: SchemaItem,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Only let autogenerate manage objects in Helios' own schemas.

    Two separate hazards make this filter necessary, and the second one is
    created by the fix for the first:

    1. The dev/CI database runs a PostGIS image, which ships PostGIS and the
       Tiger geocoder (`spatial_ref_sys` in `public`, plus the `topology` and
       `tiger` schemas). Those are reflected from the database but absent from
       `Base.metadata`, so autogenerate would emit `DROP` statements for them.

    2. The three-layer split (ADR-0003) requires `include_schemas=True` so
       Alembic looks outside the default schema at all. That flag is precisely
       what makes it reflect `topology` and `tiger` — reintroducing hazard 1.

    So the filter is a schema allowlist rather than a "not in metadata" check:
    an object is ours if it lives in one of `MANAGED_SCHEMAS`, and everything
    else is invisible to autogenerate no matter which side it came from.

    **Footgun, deliberately documented:** an unlisted schema's objects are
    *silently ignored* rather than raising. If a future layer is added and its
    tables mysteriously never appear in a migration, the cause is almost
    certainly that it was never added to `MANAGED_SCHEMAS` in
    `packages/helios_core/db/base.py`, which is the only place that list lives.
    """
    # Columns, indexes and constraints carry no schema of their own; they
    # belong to whichever table owns them, so defer to the parent's verdict.
    parent_table = getattr(schema_item, "table", None)
    schema = (
        parent_table.schema if parent_table is not None else getattr(schema_item, "schema", None)
    )
    return schema in MANAGED_SCHEMAS


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        include_schemas=True,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            include_schemas=True,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
