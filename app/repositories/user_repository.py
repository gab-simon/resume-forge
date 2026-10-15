"""User repository module."""

from sqlmodel import col, func, null, select

from app.infra.context import IContext
from app.models.user import User, UserCreate, UserFilter, UserUpdate
from app.repositories.pagination import Page, PageRequest
from app.utils import get_current_time


async def read_user(ctx: IContext, *, user_id: int) -> User | None:
    """Retrieve an active user by ID.

    Parameters
    ----------
    ctx : IContext
        The application context providing database access.
    user_id : int
        The unique identifier of the user.

    Returns
    -------
    User | None
        The matching active user, if it exists.
    """
    statement = select(User).where(
        User.user_id == user_id,
        User.deleted_at == null(),
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def read_user_by_email_for_update(ctx: IContext, *, email: str) -> User | None:
    """Lock and retrieve an active user by email.

    Parameters
    ----------
    ctx : IContext
        The application context providing database access.
    email : str
        Email in lowercase.

    Returns
    -------
    User | None
        The locked active user, if it exists.
    """
    statement = (
        select(User)
        .where(User.email == email, User.deleted_at == null())
        .with_for_update()
    )
    result = await ctx.postgres.exec(statement)
    return result.one_or_none()


async def count_users(ctx: IContext, filters: UserFilter) -> int:
    """Count active users matching the given filters.

    Parameters
    ----------
    ctx : IContext
        The application context providing database access.
    filters : UserFilter
        The user filters to apply.

    Returns
    -------
    int
        The number of matching users.
    """
    statement = select(func.count()).select_from(User).where(User.deleted_at == null())
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(User, column) == value)

    result = await ctx.postgres.exec(statement)
    return result.one()


async def read_users(
    ctx: IContext, filters: UserFilter, page: PageRequest
) -> Page[User]:
    """Retrieve active users matching the given filters with pagination.

    Parameters
    ----------
    ctx : IContext
        The application context providing database access.
    filters : UserFilter
        The user filters to apply.
    page : PageRequest
        The pagination request containing the offset and limit.

    Returns
    -------
    Page[User]
        A page of matching users.
    """
    statement = select(User).where(User.deleted_at == null())
    for column, value in filters.model_dump(exclude_unset=True).items():
        statement = statement.where(getattr(User, column) == value)

    statement = (
        statement.order_by(col(User.user_id)).offset(page.offset).limit(page.limit)
    )
    result = await ctx.postgres.exec(statement)
    return Page(
        items=result.all(),
        total=await count_users(ctx, filters),
        offset=page.offset,
        limit=page.limit,
    )


async def create(ctx: IContext, *, entity: UserCreate) -> User:
    """Create a user.

    Parameters
    ----------
    ctx : IContext
        The application context providing database access.
    entity : UserCreate
        The user data to create.

    Returns
    -------
    User
        The created user.
    """
    user = User(**entity.model_dump())
    ctx.postgres.add(user)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(user)
    return user


async def update(ctx: IContext, *, user_id: int, entity: UserUpdate) -> User | None:
    """Update an active user.

    Parameters
    ----------
    ctx : IContext
        The application context providing database access.
    user_id : int
        The unique identifier of the user.
    entity : UserUpdate
        The fields to update.

    Returns
    -------
    User | None
        The updated user, if it exists.
    """
    user = await read_user(ctx, user_id=user_id)
    if user is None:
        return None

    for key, value in entity.model_dump(exclude_unset=True).items():
        setattr(user, key, value)
    ctx.postgres.add(user)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(user)
    return user


async def delete(ctx: IContext, *, user_id: int) -> bool:
    """Soft-delete a user.

    Parameters
    ----------
    ctx : IContext
        The application context providing database access.
    user_id : int
        The unique identifier of the user.

    Returns
    -------
    bool
        Whether an active user was deleted.
    """
    user = await read_user(ctx, user_id=user_id)
    if user is None:
        return False

    user.deleted_at = get_current_time()
    ctx.postgres.add(user)
    await ctx.postgres.flush()
    await ctx.postgres.refresh(user)
    return True


__all__ = (
    'count_users',
    'create',
    'delete',
    'read_user',
    'read_user_by_email_for_update',
    'read_users',
    'update',
)
