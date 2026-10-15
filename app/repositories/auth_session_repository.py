"""Authenticated-session repository."""

from datetime import datetime

from sqlmodel import col, func, null, select

from app.infra.context import IContext
from app.models.auth_session import (
    AuthSession,
    AuthSessionCreate,
    AuthSessionFilter,
    AuthSessionUpdate,
)
from app.repositories.pagination import Page, PageRequest
from app.utils import get_current_time


async def read_auth_session(
    ctx: IContext,
    *,
    auth_session_id: int,
) -> AuthSession | None:
    """Retrieve an active device session by ID.

    Returns
    -------
    AuthSession | None
        The matching non-deleted session, if it exists.
    """
    statement = select(AuthSession).where(
        AuthSession.auth_session_id == auth_session_id,
        AuthSession.deleted_at == null(),
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def read_for_update(
    ctx: IContext,
    *,
    auth_session_id: int,
) -> AuthSession | None:
    """Lock and retrieve a device session by ID.

    Returns
    -------
    AuthSession | None
        The locked non-deleted session, if it exists.
    """
    statement = (
        select(AuthSession)
        .where(
            AuthSession.auth_session_id == auth_session_id,
            AuthSession.deleted_at == null(),
        )
        .with_for_update()
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def read_by_access_token_digest(
    ctx: IContext,
    *,
    access_token_digest: str,
) -> AuthSession | None:
    """Retrieve a device session by its current access-token digest.

    Returns
    -------
    AuthSession | None
        The matching non-deleted session, if it exists.
    """
    statement = select(AuthSession).where(
        AuthSession.access_token_digest == access_token_digest,
        AuthSession.deleted_at == null(),
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def read_active_for_user(
    ctx: IContext,
    *,
    user_id: int,
    now: datetime,
) -> list[AuthSession]:
    """Retrieve non-revoked, non-expired sessions for one user.

    Returns
    -------
    list[AuthSession]
        Active sessions ordered from most recently used.
    """
    statement = (
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at == null(),
            AuthSession.absolute_expires_at > now,
            AuthSession.deleted_at == null(),
        )
        .order_by(col(AuthSession.last_used_at).desc())
    )
    result = await ctx.postgres.exec(statement)
    return list(result.all())


async def count_auth_sessions(
    ctx: IContext,
    filters: AuthSessionFilter,
) -> int:
    """Count non-deleted device sessions matching filters.

    Returns
    -------
    int
        Number of matching sessions.
    """
    statement = (
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.deleted_at == null())
    )
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(AuthSession, column) == value)

    result = await ctx.postgres.exec(statement)
    return result.one()


async def read_auth_sessions(
    ctx: IContext,
    filters: AuthSessionFilter,
    page: PageRequest,
) -> Page[AuthSession]:
    """Retrieve non-deleted device sessions with pagination.

    Returns
    -------
    Page[AuthSession]
        A page of matching sessions.
    """
    statement = select(AuthSession).where(AuthSession.deleted_at == null())
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(AuthSession, column) == value)

    statement = (
        statement.order_by(col(AuthSession.auth_session_id))
        .offset(page.offset)
        .limit(page.limit)
    )
    result = await ctx.postgres.exec(statement)
    return Page(
        items=result.all(),
        total=await count_auth_sessions(ctx, filters),
        offset=page.offset,
        limit=page.limit,
    )


async def create(ctx: IContext, *, entity: AuthSessionCreate) -> AuthSession:
    """Create an authenticated device session.

    Returns
    -------
    AuthSession
        The created session.
    """
    session = AuthSession(**entity.model_dump())
    ctx.postgres.add(session)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(session)
    return session


async def update(
    ctx: IContext,
    *,
    auth_session_id: int,
    entity: AuthSessionUpdate,
) -> AuthSession | None:
    """Update a non-deleted device session.

    Returns
    -------
    AuthSession | None
        The updated session, if it exists.
    """
    session = await read_auth_session(ctx, auth_session_id=auth_session_id)
    if session is None:
        return None

    for key, value in entity.model_dump(exclude_unset=True).items():
        setattr(session, key, value)
    ctx.postgres.add(session)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(session)
    return session


async def delete(ctx: IContext, *, auth_session_id: int) -> bool:
    """Soft-delete an authenticated device session.

    Returns
    -------
    bool
        Whether a non-deleted session was found and deleted.
    """
    session = await read_auth_session(ctx, auth_session_id=auth_session_id)
    if session is None:
        return False

    session.deleted_at = get_current_time()
    ctx.postgres.add(session)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(session)
    return True


__all__ = (
    'count_auth_sessions',
    'create',
    'delete',
    'read_active_for_user',
    'read_auth_session',
    'read_auth_sessions',
    'read_by_access_token_digest',
    'read_for_update',
    'update',
)
