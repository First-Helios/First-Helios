import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.schema import SchemaItem

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Prefer DATABASE_URL from the environment over the static alembic.ini value so
# migrations target the same database as the app (CI, docker, future hosts).
_database_url = os.environ.get("DATABASE_URL")
if _database_url:
    # CI may provide a bare postgresql:// URL; pin the psycopg (v3) driver explicitly.
    if _database_url.startswith("postgresql://"):
        _database_url = _database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql+psycopg://", 1)
    config.set_main_option("sqlalchemy.url", _database_url)
# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from packages.helios_core.db import models  # noqa: F401 — registers models on Base.metadata
from packages.helios_core.db.base import Base

target_metadata = Base.metadata


def include_object(
    object: SchemaItem,  # noqa: A002
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    """Only let autogenerate manage objects defined in our own models.

    The dev database runs the postgis/postgis image, which ships PostGIS and the
    Tiger geocoder (spatial_ref_sys, topology, edges, faces, the tiger_* tables,
    ...). Those are reflected from the DB but absent from Base.metadata, so
    autogenerate would otherwise emit DROP statements for all of them. Ignoring
    any reflected table not in our metadata keeps migrations scoped to Helios.
    """
    is_unmanaged_table = type_ == "table" and reflected and name not in target_metadata.tables
    return not is_unmanaged_table


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
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
