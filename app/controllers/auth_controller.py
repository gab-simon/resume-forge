"""Passwordless email authentication HTTP controller."""

from typing import Annotated, Never

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from fastapi.responses import JSONResponse

from app.infra.context import RequestContext, UserContext
from app.infra.email import EmailDeliveryError, get_email_sender
from app.resources.auth_resource import (
    AuthenticationChallengeRequestResource,
    AuthenticationChallengeResource,
    AuthenticationCodeResource,
    AuthenticationRefreshResource,
    AuthenticationSessionListResource,
    AuthenticationSessionResource,
    AuthenticationSessionSummaryResource,
)
from app.resources.user_resource import UserResource
from app.services import auth_service

router = APIRouter(prefix='/auth', tags=['AUTHENTICATION'])

ChallengeId = Annotated[
    str,
    Path(min_length=32, max_length=64, pattern=r'^[A-Za-z0-9_-]+$'),
]


def _raise_unavailable(exc: Exception) -> Never:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail='Authentication is not available on this server.',
    ) from exc


@router.post(
    '/challenges',
    response_model=AuthenticationChallengeResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_authentication_code(
    payload: AuthenticationChallengeRequestResource,
    request: Request,
    response: Response,
    ctx: RequestContext,
) -> AuthenticationChallengeResource:
    """Request a one-time login code delivered by email.

    Returns
    -------
    AuthenticationChallengeResource
        Public challenge information, the same for known and new emails.

    Raises
    ------
    HTTPException
        If the request is invalid, rate-limited, or the email cannot be sent.
    """
    try:
        sender = get_email_sender(ctx.settings)
        result = await auth_service.request_login_code(
            ctx,
            email=payload.email,
            language=payload.language,
            sender=sender,
            request_ip=_request_ip(request),
        )
    except auth_service.AuthenticationRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except auth_service.AuthenticationRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail='Too many authentication-code requests.',
            headers={'Retry-After': str(exc.retry_after_seconds)},
        ) from exc
    except auth_service.AuthenticationUnavailableError as exc:
        _raise_unavailable(exc)
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Could not deliver the authentication code.',
        ) from exc

    response.headers['Cache-Control'] = 'no-store'
    return AuthenticationChallengeResource(
        challenge_id=result.challenge_id,
        expires_at=result.expires_at,
        expires_in_seconds=result.expires_in_seconds,
    )


@router.post(
    '/challenges/{challenge_id}/verify',
    response_model=AuthenticationSessionResource,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            'description': 'Invalid, expired, consumed, or blocked code.'
        }
    },
)
async def verify_authentication_code(
    challenge_id: ChallengeId,
    payload: AuthenticationCodeResource,
    request: Request,
    response: Response,
    ctx: RequestContext,
) -> AuthenticationSessionResource | JSONResponse:
    """Verify a one-time code and issue access and refresh tokens.

    The first verified code of an email creates its account.

    Returns
    -------
    AuthenticationSessionResource | JSONResponse
        Issued token pair, or a generic unauthorized response.

    Raises
    ------
    HTTPException
        If the device metadata is invalid or authentication is not configured.
    """
    try:
        result = await auth_service.verify_login_code(
            ctx,
            challenge_id=challenge_id,
            code=payload.code,
            device_id=payload.device_id,
            platform=payload.platform,
            device_name=payload.device_name,
            request_ip=_request_ip(request),
            user_agent=_user_agent(request),
        )
    except auth_service.AuthenticationRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except auth_service.AuthenticationUnavailableError as exc:
        _raise_unavailable(exc)

    if result is None:
        return _authentication_failure('Invalid or expired authentication code.')

    response.headers['Cache-Control'] = 'no-store'
    return _authentication_session_resource(result)


@router.post(
    '/refresh',
    response_model=AuthenticationSessionResource,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            'description': 'Invalid, expired, consumed, or reused refresh token.'
        }
    },
)
async def refresh_authentication_session(
    payload: AuthenticationRefreshResource,
    request: Request,
    response: Response,
    ctx: RequestContext,
) -> AuthenticationSessionResource | JSONResponse:
    """Rotate a refresh token and return a new token pair.

    Returns
    -------
    AuthenticationSessionResource | JSONResponse
        Rotated token pair, or a generic unauthorized response.
    """
    result = await auth_service.refresh_session(
        ctx,
        refresh_token=payload.refresh_token,
        request_ip=_request_ip(request),
        user_agent=_user_agent(request),
    )
    if result is None:
        return _authentication_failure('Invalid or expired refresh token.')

    response.headers['Cache-Control'] = 'no-store'
    return _authentication_session_resource(result)


@router.get('/sessions', response_model=AuthenticationSessionListResource)
async def read_authenticated_sessions(
    ctx: UserContext,
) -> AuthenticationSessionListResource:
    """List active device sessions owned by the current user.

    Returns
    -------
    AuthenticationSessionListResource
        Active sessions without token digests.
    """
    sessions = await auth_service.read_user_sessions(ctx)
    return AuthenticationSessionListResource(
        items=[
            AuthenticationSessionSummaryResource.model_validate(session)
            for session in sessions
        ]
    )


@router.delete('/sessions/{auth_session_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_authenticated_session(
    auth_session_id: int,
    ctx: UserContext,
) -> None:
    """Revoke one device session owned by the current user.

    Raises
    ------
    HTTPException
        If the session does not exist or belongs to another user.
    """
    revoked = await auth_service.revoke_user_session(
        ctx,
        auth_session_id=auth_session_id,
    )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Authentication session not found.',
        )


@router.post('/logout', status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: AuthenticationRefreshResource,
    ctx: RequestContext,
) -> None:
    """Revoke a session using its long-lived refresh token."""
    await auth_service.revoke_session_by_refresh_token(
        ctx,
        refresh_token=payload.refresh_token,
    )


def _authentication_session_resource(
    result: auth_service.IssuedAuthenticationSession,
) -> AuthenticationSessionResource:
    return AuthenticationSessionResource(
        auth_session_id=result.auth_session_id,
        access_token=result.access_token,
        access_expires_at=result.access_expires_at,
        access_expires_in_seconds=result.access_expires_in_seconds,
        refresh_token=result.refresh_token,
        refresh_expires_at=result.refresh_expires_at,
        refresh_expires_in_seconds=result.refresh_expires_in_seconds,
        is_new_user=result.is_new_user,
        user=UserResource.model_validate(result.user),
    )


def _authentication_failure(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={'detail': detail},
        headers={
            'Cache-Control': 'no-store',
            'WWW-Authenticate': 'Bearer',
        },
    )


def _request_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host[:45]


def _user_agent(request: Request) -> str | None:
    user_agent = request.headers.get('User-Agent')
    return user_agent[:512] if user_agent else None


__all__ = ('router',)
