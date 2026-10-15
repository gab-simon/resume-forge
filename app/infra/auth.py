"""Authorization helpers."""

from app.infra.context import IContext


class AuthorizationError(PermissionError):
    """Raised when a protected operation lacks the required authorization."""


def require_user(ctx: IContext) -> int:
    """Require an authenticated active user in the application context.

    Parameters
    ----------
    ctx : IContext
        Application context containing the authenticated user.

    Returns
    -------
    int
        Identifier of the authenticated user.

    Raises
    ------
    AuthorizationError
        If no active user is authenticated.
    """
    try:
        user = ctx.user
    except ValueError as exc:
        raise AuthorizationError(
            'An authenticated user is required for this operation.'
        ) from exc

    if user.deleted_at is not None:
        raise AuthorizationError(
            'An active authenticated user is required for this operation.'
        )
    return user.user_id


__all__ = ('AuthorizationError', 'require_user')
