"""Rotating refresh-token repository."""

from sqlmodel import col, func, null, select

from app.infra.context import IContext
from app.models.auth_refresh_token import (
    AuthRefreshToken,
    AuthRefreshTokenCreate,
    AuthRefreshTokenFilter,
    AuthRefreshTokenUpdate,
)
from app.repositories.pagination import Page, PageRequest
from app.utils import get_current_time


async def read_auth_refresh_token(
    ctx: IContext,
    *,
    auth_refresh_token_id: int,
) -> AuthRefreshToken | None:
    """Retrieve a non-deleted refresh token by ID.

    Returns
    -------
    AuthRefreshToken | None
        The matching token, if it exists.
    """
    statement = select(AuthRefreshToken).where(
        AuthRefreshToken.auth_refresh_token_id == auth_refresh_token_id,
        AuthRefreshToken.deleted_at == null(),
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def read_by_token_digest_for_update(
    ctx: IContext,
    *,
    token_digest: str,
) -> AuthRefreshToken | None:
    """Lock and retrieve a refresh token by digest, including consumed tokens.

    Returns
    -------
    AuthRefreshToken | None
        The locked non-deleted token, if it exists.
    """
    statement = (
        select(AuthRefreshToken)
        .where(
            AuthRefreshToken.token_digest == token_digest,
            AuthRefreshToken.deleted_at == null(),
        )
        .with_for_update()
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def count_auth_refresh_tokens(
    ctx: IContext,
    filters: AuthRefreshTokenFilter,
) -> int:
    """Count non-deleted refresh tokens matching filters.

    Returns
    -------
    int
        Number of matching tokens.
    """
    statement = (
        select(func.count())
        .select_from(AuthRefreshToken)
        .where(AuthRefreshToken.deleted_at == null())
    )
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(AuthRefreshToken, column) == value)

    result = await ctx.postgres.exec(statement)
    return result.one()


async def read_auth_refresh_tokens(
    ctx: IContext,
    filters: AuthRefreshTokenFilter,
    page: PageRequest,
) -> Page[AuthRefreshToken]:
    """Retrieve non-deleted refresh tokens with pagination.

    Returns
    -------
    Page[AuthRefreshToken]
        A page of matching tokens.
    """
    statement = select(AuthRefreshToken).where(AuthRefreshToken.deleted_at == null())
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(AuthRefreshToken, column) == value)

    statement = (
        statement.order_by(col(AuthRefreshToken.auth_refresh_token_id))
        .offset(page.offset)
        .limit(page.limit)
    )
    result = await ctx.postgres.exec(statement)
    return Page(
        items=result.all(),
        total=await count_auth_refresh_tokens(ctx, filters),
        offset=page.offset,
        limit=page.limit,
    )


async def create(
    ctx: IContext,
    *,
    entity: AuthRefreshTokenCreate,
) -> AuthRefreshToken:
    """Create a rotating refresh token.

    Returns
    -------
    AuthRefreshToken
        The created token.
    """
    token = AuthRefreshToken(**entity.model_dump())
    ctx.postgres.add(token)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(token)
    return token


async def update(
    ctx: IContext,
    *,
    auth_refresh_token_id: int,
    entity: AuthRefreshTokenUpdate,
) -> AuthRefreshToken | None:
    """Update a non-deleted refresh token.

    Returns
    -------
    AuthRefreshToken | None
        The updated token, if it exists.
    """
    token = await read_auth_refresh_token(
        ctx,
        auth_refresh_token_id=auth_refresh_token_id,
    )
    if token is None:
        return None

    for key, value in entity.model_dump(exclude_unset=True).items():
        setattr(token, key, value)
    ctx.postgres.add(token)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(token)
    return token


async def delete(ctx: IContext, *, auth_refresh_token_id: int) -> bool:
    """Soft-delete a rotating refresh token.

    Returns
    -------
    bool
        Whether a non-deleted token was found and deleted.
    """
    token = await read_auth_refresh_token(
        ctx,
        auth_refresh_token_id=auth_refresh_token_id,
    )
    if token is None:
        return False

    token.deleted_at = get_current_time()
    ctx.postgres.add(token)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(token)
    return True


__all__ = (
    'count_auth_refresh_tokens',
    'create',
    'delete',
    'read_auth_refresh_token',
    'read_auth_refresh_tokens',
    'read_by_token_digest_for_update',
    'update',
)
