"""Authenticated user profile HTTP controller."""

from fastapi import APIRouter, HTTPException, status

from app.infra.context import UserContext
from app.models.user import UserUpdate
from app.resources.user_resource import UserResource, UserUpdateResource
from app.services import user_service
from app.services.user_service import UserPreferenceError

router = APIRouter(prefix='/me', tags=['ME'])


@router.get('', response_model=UserResource)
async def read_me(ctx: UserContext) -> UserResource:
    """Return the authenticated user with their preferences.

    Returns
    -------
    UserResource
        The authenticated user.
    """
    return UserResource.model_validate(user_service.read_profile(ctx))


@router.patch('', response_model=UserResource)
async def update_me(payload: UserUpdateResource, ctx: UserContext) -> UserResource:
    """Update the name and preferences of the authenticated user.

    Returns
    -------
    UserResource
        The updated user.

    Raises
    ------
    HTTPException
        With status 422 when the template does not exist.
    """
    try:
        user = await user_service.update_profile(
            ctx,
            entity=UserUpdate.model_construct(**payload.model_dump(exclude_unset=True)),
        )
    except UserPreferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return UserResource.model_validate(user)


__all__ = ('router',)
