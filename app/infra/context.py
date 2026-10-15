"""Context object for the application."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Never,
    Protocol,
    Self,
    runtime_checkable,
)

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.infra import Settings, get_settings
from app.infra.database.postgres import AsyncSession as PostgresSession
from app.infra.database.postgres import get_db_session, set_row_level_security_scope

if TYPE_CHECKING:
    from app.models.user import User


@runtime_checkable
class IContext(Protocol):
    """Protocol for the context object."""

    @property
    def postgres(self: Self) -> PostgresSession:
        """The active PostgreSQL session."""
        ...

    @property
    def user(self: Self) -> User:
        """The authenticated user."""
        ...

    @property
    def request(self: Self) -> Request:
        """The current request."""
        ...

    @property
    def settings(self: Self) -> Settings:
        """The application settings."""
        ...


class Context(IContext):
    """The context object for the application."""

    _settings: Settings | None = None
    _postgres: PostgresSession | None = None
    _user: User | None = None
    _request: Request | None = None

    def __init__(
        self: Self,
        *,
        postgres: PostgresSession | None = None,
        user: User | None = None,
        request: Request | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._postgres = postgres
        self._user = user
        self._request = request
        self._settings = settings

    @property
    def postgres(self: Self) -> PostgresSession:
        """Active PostgreSQL session.

        Returns
        -------
        PostgresSession
            The active PostgreSQL session.

        Raises
        ------
        ValueError
            If the PostgreSQL session is not available.
        """
        if not self._postgres:
            raise ValueError('postgres not found')

        return self._postgres

    @property
    def user(self: Self) -> User:
        """Authenticated user.

        Returns
        -------
        User
            The authenticated user associated with the context.

        Raises
        ------
        ValueError
            If the context does not have an authenticated user.
        """
        if self._user is None:
            raise ValueError('user not found')

        return self._user

    @property
    def settings(self: Self) -> Settings:
        """Application settings.

        Returns
        -------
        Settings
            Typed settings used by the current operation.
        """
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def request(self: Self) -> Request:
        """Current request.

        Returns
        -------
        Request
            The current request object.

        Raises
        ------
        ValueError
            If the request is not available.
        """
        if not self._request:
            raise ValueError('request not found')

        return self._request


@asynccontextmanager
async def get_context(
    request: Request | None = None,
) -> AsyncGenerator[Context, Any]:
    """Provide a context with a database session and no user.

    Row-level security hides every user-owned row from this context. Use it
    only for work that belongs to no user, such as health probes.

    Parameters
    ----------
    request : Request | None, optional
        The current request object, if available.

    Yields
    ------
    Context
        A context instance containing a PostgreSQL session and the request.
    """
    async with get_db_session() as postgres:
        yield Context(postgres=postgres, request=request)


def get_file_context() -> Context:
    """Build a context without a database session.

    The master resume of the CLI lives in files, so building and checking it
    does not need PostgreSQL. Reading ``postgres`` raises ``ValueError``.

    Returns
    -------
    Context
        A context holding only the application settings.
    """
    return Context(settings=get_settings())


async def get_context_with_request(request: Request) -> AsyncGenerator[Context]:
    """Provide a database context for an unauthenticated HTTP request.

    Parameters
    ----------
    request : Request
        The current HTTP request.

    Yields
    ------
    Context
        A context containing the database session and request.
    """
    settings = get_settings()
    async with get_db_session() as postgres:
        yield Context(postgres=postgres, request=request, settings=settings)  # ruff: ignore[yield-in-context-manager-in-async-generator]


def get_file_context_with_request(request: Request) -> Context:
    """Provide a context without a database session for an HTTP request.

    Parameters
    ----------
    request : Request
        The current HTTP request.

    Returns
    -------
    Context
        A context containing the request and the settings.
    """
    return Context(request=request, settings=get_settings())


_bearer_scheme = HTTPBearer(auto_error=False)


def get_authentication_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> str:
    """Read one opaque access token from the Bearer authorization header.

    Parameters
    ----------
    credentials : HTTPAuthorizationCredentials | None
        Optional Bearer credentials parsed by FastAPI.

    Returns
    -------
    str
        Opaque access token.
    """
    if credentials is None or not credentials.credentials.strip():
        _raise_unauthorized()
    return credentials.credentials


async def get_authenticated_context(
    request: Request,
    token: Annotated[str, Depends(get_authentication_token)],
) -> AsyncGenerator[Context]:
    """Provide an HTTP context authenticated by a revocable session token.

    The session is scoped to the user with row-level security before the
    route runs, so it reads and writes only that user's rows.

    Parameters
    ----------
    request : Request
        Current HTTP request.
    token : str
        Opaque session token extracted from the request.

    Yields
    ------
    Context
        Context containing the active session's user.
    """
    from app.services.auth_service import AuthenticationError, authenticate_session

    settings = get_settings()
    async with get_db_session() as postgres:
        lookup_context = Context(postgres=postgres, request=request, settings=settings)
        try:
            authenticated = await authenticate_session(
                lookup_context,
                access_token=token,
            )
        except AuthenticationError:
            _raise_unauthorized()
        await set_row_level_security_scope(
            postgres,
            user_id=authenticated.user.user_id,
        )
        yield Context(  # ruff: ignore[yield-in-context-manager-in-async-generator]
            postgres=postgres,
            user=authenticated.user,
            request=request,
            settings=settings,
        )


def _raise_unauthorized() -> Never:
    """Raise the generic HTTP authentication failure.

    Raises
    ------
    HTTPException
        Always raised without exposing token or account details.
    """
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Invalid or expired authentication session.',
        headers={'WWW-Authenticate': 'Bearer'},
    )


@asynccontextmanager
async def get_user_context(
    user_id: int,
    request: Request | None = None,
) -> AsyncGenerator[Context, Any]:
    """Provide a context scoped to one user, for CLI commands and scripts.

    Parameters
    ----------
    user_id : int
        User whose rows the session can read and write.
    request : Request | None, optional
        The current request object, if available.

    Yields
    ------
    Context
        A context holding the user, or ``ValueError`` on entry when the user
        does not exist.

    Raises
    ------
    ValueError
        If the user does not exist.
    """
    from app.repositories import user_repository

    async with get_db_session() as postgres:
        await set_row_level_security_scope(postgres, user_id=user_id)
        user = await user_repository.read_user(
            Context(postgres=postgres), user_id=user_id
        )
        if user is None:
            raise ValueError(f'user {user_id} not found')
        yield Context(postgres=postgres, user=user, request=request)


# scope='function' makes FastAPI close the dependency, and therefore commit the
# database session, before it sends the response. With the default scope the
# commit runs after the response, so a client that reads right after a write can
# receive the previous value.
RequestContext = Annotated[
    Context,
    Depends(get_context_with_request, scope='function'),
]
UserContext = Annotated[
    Context,
    Depends(get_authenticated_context, scope='function'),
]
# Routes that only read and render the resume files use this alias, so they
# work without PostgreSQL.
FileContext = Annotated[
    Context,
    Depends(get_file_context_with_request),
]


__all__ = (
    'Context',
    'FileContext',
    'IContext',
    'RequestContext',
    'UserContext',
    'get_authenticated_context',
    'get_authentication_token',
    'get_context',
    'get_context_with_request',
    'get_file_context',
    'get_file_context_with_request',
    'get_user_context',
)
