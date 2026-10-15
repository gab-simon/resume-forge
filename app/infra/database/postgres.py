"""Postgres database connection management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import cache
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import func, select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app import Settings, get_settings


@cache
def db_session_maker() -> async_sessionmaker[AsyncSession]:
    config: Settings = get_settings()

    return async_sessionmaker(
        bind=create_async_engine(
            url=config.db_conn_uri,
            echo=config.db_debug,
            pool_pre_ping=True,
            pool_recycle=config.db_pool_recycle_seconds,
            pool_size=config.db_pool_size,
            max_overflow=config.db_max_overflow,
        ),
        class_=AsyncSession,
        expire_on_commit=False,
    )


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, Any]:
    """Yield an async database session and manage transaction commit or rollback.

    Parameters
    ----------
    None

    Yields
    ------
    AsyncSession
        An active SQLModel asynchronous session bound to the configured Postgres engine.
    """
    session_local = db_session_maker()

    async with session_local() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def set_row_level_security_scope(
    session: AsyncSession,
    *,
    user_id: int | None,
) -> None:
    """Set the user that the row-level security policies let the session see.

    The value lasts until the current transaction ends, so a pooled connection
    never carries the user of a previous request. Without a user, the
    policies match no row of a user-owned table.

    Parameters
    ----------
    session : AsyncSession
        Session whose current transaction receives the scope.
    user_id : int | None
        User whose rows become visible and writable.
    """
    await session.exec(
        select(
            func.set_config(
                'app.user_id',
                '' if user_id is None else str(user_id),
                True,
            )
        )
    )


async def role_bypasses_row_level_security() -> bool:
    """Check whether the connected database role ignores the user policies.

    Superusers and roles with ``BYPASSRLS`` skip every policy, and a role that
    owns the tables skips them too. Connecting the application with such a
    role removes the isolation between users.

    Returns
    -------
    bool
        ``True`` when the application role is not restricted by the policies.
    """
    async with get_db_session() as session:
        result = await session.exec(
            select(
                text(
                    """
                    EXISTS (
                        SELECT 1
                        FROM pg_roles
                        WHERE rolname = current_user
                            AND (rolsuper OR rolbypassrls)
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM pg_tables
                        WHERE schemaname = 'resume_forge'
                            AND tablename = 'app_user'
                            AND tableowner = current_user
                    )
                    """
                )
            )
        )
        return bool(result.one())


async def ping_database() -> bool:
    """Check whether the database is reachable by executing a trivial query.

    Parameters
    ----------
    None

    Returns
    -------
    bool
        ``True`` if the database responds to a ``SELECT 1`` query.
    """
    async with get_db_session() as session:
        statement = select(text('1'))
        result = await session.exec(statement=statement)
        return result.one() == 1


__all__ = (
    'AsyncSession',
    'get_db_session',
    'ping_database',
    'role_bypasses_row_level_security',
    'set_row_level_security_scope',
)
