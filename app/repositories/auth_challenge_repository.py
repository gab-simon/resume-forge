"""Authentication challenge repository."""

from datetime import datetime

from sqlmodel import col, func, null, select

from app.infra.context import IContext
from app.models.auth_challenge import (
    AuthChallenge,
    AuthChallengeCreate,
    AuthChallengeFilter,
    AuthChallengeUpdate,
)
from app.repositories.pagination import Page, PageRequest
from app.utils import get_current_time


async def read_auth_challenge(
    ctx: IContext,
    *,
    auth_challenge_id: int,
) -> AuthChallenge | None:
    """Retrieve an active authentication challenge by ID.

    Returns
    -------
    AuthChallenge | None
        The matching active challenge, if it exists.
    """
    statement = select(AuthChallenge).where(
        AuthChallenge.auth_challenge_id == auth_challenge_id,
        AuthChallenge.deleted_at == null(),
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def read_for_verification(
    ctx: IContext,
    *,
    public_id: str,
) -> AuthChallenge | None:
    """Lock and retrieve an active challenge by its public identifier.

    Returns
    -------
    AuthChallenge | None
        The locked active challenge, if it exists.
    """
    statement = (
        select(AuthChallenge)
        .where(
            AuthChallenge.public_id == public_id,
            AuthChallenge.deleted_at == null(),
        )
        .with_for_update()
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def read_latest_for_email(
    ctx: IContext,
    *,
    email: str,
) -> AuthChallenge | None:
    """Retrieve the most recently created active challenge for an email.

    Returns
    -------
    AuthChallenge | None
        The latest challenge, if one exists.
    """
    statement = (
        select(AuthChallenge)
        .where(
            AuthChallenge.email == email,
            AuthChallenge.deleted_at == null(),
        )
        .order_by(col(AuthChallenge.created_at).desc())
        .limit(1)
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def count_recent_for_email(
    ctx: IContext,
    *,
    email: str,
    since: datetime,
) -> int:
    """Count challenges recently created for one email.

    Returns
    -------
    int
        Number of matching challenges.
    """
    statement = (
        select(func.count())
        .select_from(AuthChallenge)
        .where(
            AuthChallenge.email == email,
            AuthChallenge.created_at >= since,
            AuthChallenge.deleted_at == null(),
        )
    )
    result = await ctx.postgres.exec(statement)
    return result.one()


async def count_recent_for_ip(
    ctx: IContext,
    *,
    request_ip: str,
    since: datetime,
) -> int:
    """Count challenges recently created from one network address.

    Returns
    -------
    int
        Number of matching challenges.
    """
    statement = (
        select(func.count())
        .select_from(AuthChallenge)
        .where(
            AuthChallenge.request_ip == request_ip,
            AuthChallenge.created_at >= since,
            AuthChallenge.deleted_at == null(),
        )
    )
    result = await ctx.postgres.exec(statement)
    return result.one()


async def count_auth_challenges(
    ctx: IContext,
    filters: AuthChallengeFilter,
) -> int:
    """Count active authentication challenges matching filters.

    Returns
    -------
    int
        Number of matching active challenges.
    """
    statement = (
        select(func.count())
        .select_from(AuthChallenge)
        .where(AuthChallenge.deleted_at == null())
    )
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(AuthChallenge, column) == value)

    result = await ctx.postgres.exec(statement)
    return result.one()


async def read_auth_challenges(
    ctx: IContext,
    filters: AuthChallengeFilter,
    page: PageRequest,
) -> Page[AuthChallenge]:
    """Retrieve active authentication challenges with pagination.

    Returns
    -------
    Page[AuthChallenge]
        A page of matching active challenges.
    """
    statement = select(AuthChallenge).where(AuthChallenge.deleted_at == null())
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(AuthChallenge, column) == value)

    statement = (
        statement.order_by(col(AuthChallenge.auth_challenge_id))
        .offset(page.offset)
        .limit(page.limit)
    )
    result = await ctx.postgres.exec(statement)
    return Page(
        items=result.all(),
        total=await count_auth_challenges(ctx, filters),
        offset=page.offset,
        limit=page.limit,
    )


async def create(
    ctx: IContext,
    *,
    entity: AuthChallengeCreate,
) -> AuthChallenge:
    """Create an authentication challenge.

    Returns
    -------
    AuthChallenge
        The created challenge.
    """
    challenge = AuthChallenge(**entity.model_dump())
    ctx.postgres.add(challenge)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(challenge)
    return challenge


async def update(
    ctx: IContext,
    *,
    auth_challenge_id: int,
    entity: AuthChallengeUpdate,
) -> AuthChallenge | None:
    """Update an active authentication challenge.

    Returns
    -------
    AuthChallenge | None
        The updated challenge, if it exists.
    """
    challenge = await read_auth_challenge(
        ctx,
        auth_challenge_id=auth_challenge_id,
    )
    if challenge is None:
        return None

    for key, value in entity.model_dump(exclude_unset=True).items():
        setattr(challenge, key, value)
    ctx.postgres.add(challenge)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(challenge)
    return challenge


async def invalidate_open_for_email(
    ctx: IContext,
    *,
    email: str,
    consumed_at: datetime,
) -> int:
    """Consume all open challenges for an email before issuing a new one.

    Returns
    -------
    int
        Number of challenges invalidated.
    """
    statement = select(AuthChallenge).where(
        AuthChallenge.email == email,
        AuthChallenge.consumed_at == null(),
        AuthChallenge.deleted_at == null(),
    )
    result = await ctx.postgres.exec(statement)
    challenges = result.all()
    for challenge in challenges:
        challenge.consumed_at = consumed_at
        ctx.postgres.add(challenge)
    if challenges:
        await ctx.postgres.flush()
    return len(challenges)


async def delete(ctx: IContext, *, auth_challenge_id: int) -> bool:
    """Soft-delete an authentication challenge.

    Returns
    -------
    bool
        Whether an active challenge was deleted.
    """
    challenge = await read_auth_challenge(
        ctx,
        auth_challenge_id=auth_challenge_id,
    )
    if challenge is None:
        return False

    challenge.deleted_at = get_current_time()
    ctx.postgres.add(challenge)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(challenge)
    return True


__all__ = (
    'count_auth_challenges',
    'count_recent_for_email',
    'count_recent_for_ip',
    'create',
    'delete',
    'invalidate_open_for_email',
    'read_auth_challenge',
    'read_auth_challenges',
    'read_for_verification',
    'read_latest_for_email',
    'update',
)
