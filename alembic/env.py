# ruff:file-ignore[implicit-namespace-package]

"""Alembic environment configuration."""

import asyncio
from logging.config import fileConfig

from alembic.runtime.environment import (
    IncludeNameFn,
    NameFilterParentNames,
    NameFilterType,
)
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context
from app.infra import get_settings

# Import every table model module here so autogeneration sees its table.
# ruff:file-ignore[unused-import]
from app.models import auth_challenge, auth_refresh_token, auth_session, user
from app.models.base import SQLBaseModel

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Set the SQLAlchemy URL from the environment settings. Migrations use the
# role that owns the tables, not the application role restricted by RLS.
config.set_main_option(
    'sqlalchemy.url',
    get_settings().db_migration_conn_uri.replace('%', '%%'),
)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLBaseModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def include_only_app_schema(connection: Connection) -> IncludeNameFn:
    """Build the filter that limits autogeneration to the application schema.

    Without the filter, autogeneration compares every schema of the database
    and proposes to drop tables that have no model. That includes
    ``alembic_version`` when the database user has the same name as the
    application schema. PostgreSQL then uses the application schema as the
    default one, and Alembic no longer recognizes its own table in ``public``.

    Parameters
    ----------
    connection : Connection
        Connection used by the migration run.

    Returns
    -------
    IncludeNameFn
        Filter that accepts only the schema of ``SQLBaseModel``. A project
        that adds tables in another schema must accept that schema here.
    """
    app_schema = target_metadata.schema
    # Alembic passes the default schema of the connection as ``None``.
    if connection.dialect.default_schema_name == app_schema:
        app_schema = None

    def include_name(
        name: str | None,
        type_: NameFilterType,
        _parent_names: NameFilterParentNames,
    ) -> bool:
        return type_ != 'schema' or name == app_schema

    return include_name


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option('sqlalchemy.url')
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations for the given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_only_app_schema(connection),
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
