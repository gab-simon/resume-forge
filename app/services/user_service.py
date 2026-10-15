"""User profile service functions."""

from app.infra.auth import require_user
from app.infra.context import IContext
from app.models.resume import LANGUAGES
from app.models.user import UI_LANGUAGES, User, UserUpdate
from app.repositories import user_repository
from app.services import render_service


class UserPreferenceError(ValueError):
    """Raised when a preference names a language or template that does not exist."""


def read_profile(ctx: IContext) -> User:
    """Return the authenticated user.

    Parameters
    ----------
    ctx : IContext
        Application context containing the authenticated user.

    Returns
    -------
    User
        The authenticated user, as loaded for this request.
    """
    require_user(ctx)
    return ctx.user


async def update_profile(ctx: IContext, *, entity: UserUpdate) -> User:
    """Update the name and preferences of the authenticated user.

    The email is not changed here: it identifies the account at login.

    Parameters
    ----------
    ctx : IContext
        Application context containing the authenticated user.
    entity : UserUpdate
        Fields to update. ``email`` is ignored.

    Returns
    -------
    User
        The updated user.

    Raises
    ------
    UserPreferenceError
        If a language or the template is not supported.
    RuntimeError
        If the authenticated user disappeared during the request.
    """
    user_id = require_user(ctx)
    changes = entity.model_dump(exclude_unset=True, exclude={'email'})

    if 'ui_language' in changes and changes['ui_language'] not in UI_LANGUAGES:
        raise UserPreferenceError(
            f'Unsupported interface language: {changes["ui_language"]}.'
        )
    if 'resume_language' in changes and changes['resume_language'] not in LANGUAGES:
        raise UserPreferenceError(
            f'Unsupported resume language: {changes["resume_language"]}.'
        )
    if 'default_template' in changes and changes['default_template'] not in {
        template.name for template in render_service.list_templates(ctx)
    }:
        raise UserPreferenceError(f'Template not found: {changes["default_template"]}.')
    if 'name' in changes and changes['name'] is not None:
        changes['name'] = changes['name'].strip() or None

    user = await user_repository.update(
        ctx,
        user_id=user_id,
        entity=UserUpdate.model_construct(**changes),
    )
    if user is None:
        raise RuntimeError('The authenticated user disappeared during the request.')
    return user


__all__ = ('UserPreferenceError', 'read_profile', 'update_profile')
