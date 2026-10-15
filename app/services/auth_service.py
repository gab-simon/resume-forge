"""Passwordless email authentication service.

Ported from the WhatsApp login of Bolei. A code is sent to any email, and the
account is created when the first code for that email is verified, so the
API never tells whether an email has an account.
"""

import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.infra.auth import require_user
from app.infra.context import IContext
from app.infra.email import EmailMessage, EmailSender
from app.models.auth_challenge import AuthChallengeCreate, AuthChallengeUpdate
from app.models.auth_refresh_token import (
    AuthRefreshTokenCreate,
    AuthRefreshTokenUpdate,
)
from app.models.auth_session import AuthSession, AuthSessionCreate, AuthSessionUpdate
from app.models.user import UI_LANGUAGES, UiLanguage, User, UserCreate
from app.repositories import (
    auth_challenge_repository,
    auth_refresh_token_repository,
    auth_session_repository,
    user_repository,
)
from app.utils import get_current_time

_OTP_DIGITS = 6
# Code of every login in development without an SMTP server. See
# Settings.uses_dev_login_code.
DEV_LOGIN_CODE = '123456'
_TOKEN_BYTES = 48
_MAX_EMAIL_LENGTH = 320
# Platforms a client may declare when it verifies a code.
_SUPPORTED_PLATFORMS = frozenset({'android', 'ios', 'web'})
# A new account writes its resumes in the language of its interface.
_RESUME_LANGUAGE_BY_UI_LANGUAGE: dict[UiLanguage, str] = {'pt-BR': 'pt', 'en-US': 'en'}

_CODE_EMAIL: dict[UiLanguage, tuple[str, str]] = {
    'pt-BR': (
        'Seu código de acesso ao Resume Forge: {code}',
        (
            'Seu código de acesso ao Resume Forge é {code}.\n\n'
            'Ele vale por {minutes} minutos e só pode ser usado uma vez.\n'
            'Se você não pediu este código, ignore este e-mail.\n'
        ),
    ),
    'en-US': (
        'Your Resume Forge sign-in code: {code}',
        (
            'Your Resume Forge sign-in code is {code}.\n\n'
            'It is valid for {minutes} minutes and can be used only once.\n'
            'If you did not request this code, ignore this email.\n'
        ),
    ),
}


class AuthenticationError(PermissionError):
    """Raised when a session cannot authenticate a user."""


class AuthenticationRequestError(ValueError):
    """Raised when an authentication request contains invalid domain data."""


class AuthenticationUnavailableError(RuntimeError):
    """Raised when authentication is not configured on this server."""


class AuthenticationRateLimitError(RuntimeError):
    """Raised when authentication-code requests exceed a configured limit."""

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__('Too many authentication-code requests.')
        self.retry_after_seconds = max(1, retry_after_seconds)


@dataclass(frozen=True, slots=True)
class AuthenticationChallengeResult:
    """Public information returned after requesting an authentication code."""

    challenge_id: str
    expires_at: datetime
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class IssuedAuthenticationSession:
    """Access and rotating refresh tokens issued for one device."""

    auth_session_id: int
    access_token: str
    access_expires_at: datetime
    access_expires_in_seconds: int
    refresh_token: str
    refresh_expires_at: datetime
    refresh_expires_in_seconds: int
    user: User
    is_new_user: bool = False


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Persisted session and user resolved from an access token."""

    session: AuthSession
    user: User


async def request_login_code(
    ctx: IContext,
    *,
    email: str,
    language: str,
    sender: EmailSender,
    request_ip: str | None = None,
) -> AuthenticationChallengeResult:
    """Create a one-time login challenge and email its code.

    Every email receives a code, whether it has an account or not, so the
    response does not reveal which emails are registered.

    Parameters
    ----------
    ctx : IContext
        Application context containing one database transaction and settings.
    email : str
        Email that receives the code.
    language : str
        Interface language (``pt-BR`` or ``en-US``) of the email, and of the
        account if the verification creates one.
    sender : EmailSender
        Gateway used to deliver the code.
    request_ip : str | None, optional
        Network address used for request throttling.

    Returns
    -------
    AuthenticationChallengeResult
        Public challenge identifier and expiry.

    Raises
    ------
    AuthenticationRequestError
        If the email or the language is invalid.
    """
    canonical_email = _canonical_email(email)
    if language not in UI_LANGUAGES:
        raise AuthenticationRequestError('Unsupported language.')
    ui_language: UiLanguage = language
    secret = _otp_secret(ctx)
    settings = ctx.settings
    now = get_current_time()

    await _enforce_request_limits(
        ctx,
        email=canonical_email,
        request_ip=request_ip,
        now=now,
    )

    public_id = secrets.token_urlsafe(32)
    expires_at = now + timedelta(seconds=settings.auth_otp_ttl_seconds)
    code = (
        DEV_LOGIN_CODE
        if settings.uses_dev_login_code
        else f'{secrets.randbelow(10**_OTP_DIGITS):0{_OTP_DIGITS}d}'
    )

    await auth_challenge_repository.invalidate_open_for_email(
        ctx,
        email=canonical_email,
        consumed_at=now,
    )
    await auth_challenge_repository.create(
        ctx,
        entity=AuthChallengeCreate(
            email=canonical_email,
            language=ui_language,
            public_id=public_id,
            code_digest=_authentication_code_digest(
                public_id=public_id, code=code, secret=secret
            ),
            request_ip=request_ip,
            expires_at=expires_at,
            attempt_count=0,
            consumed_at=None,
        ),
    )
    subject, text = _CODE_EMAIL[ui_language]
    minutes = math.ceil(settings.auth_otp_ttl_seconds / 60)
    await sender.send(
        EmailMessage(
            to=canonical_email,
            subject=subject.format(code=code),
            text=text.format(code=code, minutes=minutes),
        )
    )

    return AuthenticationChallengeResult(
        challenge_id=public_id,
        expires_at=expires_at,
        expires_in_seconds=settings.auth_otp_ttl_seconds,
    )


async def verify_login_code(
    ctx: IContext,
    *,
    challenge_id: str,
    code: str,
    device_id: str,
    platform: str,
    device_name: str | None = None,
    request_ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedAuthenticationSession | None:
    """Consume a valid code, create the account if needed, and issue tokens.

    Invalid attempts return ``None`` rather than raising so their incremented
    counters can be committed by the request transaction.

    Returns
    -------
    IssuedAuthenticationSession | None
        New session when verification succeeds; otherwise, ``None``.
    """
    normalized_device_id, normalized_platform, normalized_device_name = (
        _validate_device(
            device_id=device_id,
            platform=platform,
            device_name=device_name,
        )
    )
    verified = await _consume_login_code(ctx, challenge_id=challenge_id, code=code)
    if verified is None:
        return None
    email, language, now = verified

    user = await user_repository.read_user_by_email_for_update(ctx, email=email)
    is_new_user = user is None
    if user is None:
        user = await user_repository.create(
            ctx,
            entity=UserCreate(
                email=email,
                ui_language=language,
                resume_language=_RESUME_LANGUAGE_BY_UI_LANGUAGE[language],
            ),
        )

    return await _create_session(
        ctx,
        user=user,
        is_new_user=is_new_user,
        device_id=normalized_device_id,
        platform=normalized_platform,
        device_name=normalized_device_name,
        request_ip=request_ip,
        user_agent=user_agent,
        now=now,
    )


async def refresh_session(
    ctx: IContext,
    *,
    refresh_token: str,
    request_ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedAuthenticationSession | None:
    """Rotate a single-use refresh token and issue a new access token.

    Reuse of a consumed refresh token revokes the complete device session.
    Invalid results return ``None`` so revocation updates can be committed.

    Returns
    -------
    IssuedAuthenticationSession | None
        Rotated token pair, or ``None`` when refresh authentication fails.

    Raises
    ------
    RuntimeError
        If a row locked for rotation unexpectedly disappears.
    """
    raw_refresh_token = refresh_token.strip()
    if not raw_refresh_token:
        return None

    stored_refresh_token = (
        await auth_refresh_token_repository.read_by_token_digest_for_update(
            ctx,
            token_digest=_token_digest(raw_refresh_token),
        )
    )
    if stored_refresh_token is None:
        return None

    session = await auth_session_repository.read_for_update(
        ctx,
        auth_session_id=stored_refresh_token.auth_session_id,
    )
    if session is None:
        return None

    now = get_current_time()
    if (
        stored_refresh_token.consumed_at is not None
        or stored_refresh_token.revoked_at is not None
    ):
        await _revoke_session(ctx, session=session, revoked_at=now)
        return None

    if (
        now >= stored_refresh_token.expires_at
        or session.revoked_at is not None
        or now >= session.absolute_expires_at
    ):
        await _revoke_refresh_token(
            ctx,
            auth_refresh_token_id=stored_refresh_token.auth_refresh_token_id,
            revoked_at=now,
        )
        if session.revoked_at is None:
            await _revoke_session(ctx, session=session, revoked_at=now)
        return None

    user = await user_repository.read_user(ctx, user_id=session.user_id)
    if user is None:
        await _revoke_session(ctx, session=session, revoked_at=now)
        return None

    access_token = _new_opaque_token()
    new_refresh_token = _new_opaque_token()
    access_expires_at = min(
        now + timedelta(minutes=ctx.settings.auth_access_token_ttl_minutes),
        session.absolute_expires_at,
    )
    refresh_expires_at = min(
        now + timedelta(days=ctx.settings.auth_refresh_token_idle_ttl_days),
        session.absolute_expires_at,
    )
    new_stored_refresh_token = await auth_refresh_token_repository.create(
        ctx,
        entity=AuthRefreshTokenCreate(
            auth_session_id=session.auth_session_id,
            token_digest=_token_digest(new_refresh_token),
            expires_at=refresh_expires_at,
            consumed_at=None,
            replaced_by_auth_refresh_token_id=None,
            revoked_at=None,
        ),
    )
    consumed_refresh_token = await auth_refresh_token_repository.update(
        ctx,
        auth_refresh_token_id=stored_refresh_token.auth_refresh_token_id,
        entity=AuthRefreshTokenUpdate.model_construct(
            consumed_at=now,
            replaced_by_auth_refresh_token_id=(
                new_stored_refresh_token.auth_refresh_token_id
            ),
        ),
    )
    if consumed_refresh_token is None:
        raise RuntimeError('Locked refresh token disappeared during rotation.')
    updated_session = await auth_session_repository.update(
        ctx,
        auth_session_id=session.auth_session_id,
        entity=AuthSessionUpdate.model_construct(
            access_token_digest=_token_digest(access_token),
            access_expires_at=access_expires_at,
            request_ip=request_ip,
            user_agent=user_agent,
            last_used_at=now,
        ),
    )
    if updated_session is None:
        raise RuntimeError('Locked authentication session disappeared during rotation.')

    return _issued_session_result(
        session=updated_session,
        user=user,
        access_token=access_token,
        refresh_token=new_refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        now=now,
    )


async def authenticate_session(
    ctx: IContext,
    *,
    access_token: str,
) -> AuthenticatedSession:
    """Authenticate an API session from a Bearer access token.

    Returns
    -------
    AuthenticatedSession
        Active session and user.

    Raises
    ------
    AuthenticationError
        If the token is invalid, expired or revoked, or its user is inactive.
    """
    token = access_token.strip()
    if not token:
        raise AuthenticationError('Authentication token is missing.')

    session = await auth_session_repository.read_by_access_token_digest(
        ctx,
        access_token_digest=_token_digest(token),
    )
    now = get_current_time()
    if (
        session is None
        or session.revoked_at is not None
        or now >= session.access_expires_at
        or now >= session.absolute_expires_at
    ):
        raise AuthenticationError('Authentication session is invalid.')

    user = await user_repository.read_user(ctx, user_id=session.user_id)
    if user is None:
        raise AuthenticationError('Authentication user is inactive.')

    updated_session = await auth_session_repository.update(
        ctx,
        auth_session_id=session.auth_session_id,
        entity=AuthSessionUpdate.model_construct(last_used_at=now),
    )
    return AuthenticatedSession(session=updated_session or session, user=user)


async def revoke_session_by_refresh_token(
    ctx: IContext,
    *,
    refresh_token: str,
) -> bool:
    """Revoke a device session using any refresh token from its family.

    Returns
    -------
    bool
        Whether the supplied token identified a persisted device session.
    """
    raw_refresh_token = refresh_token.strip()
    if not raw_refresh_token:
        return False

    stored_refresh_token = (
        await auth_refresh_token_repository.read_by_token_digest_for_update(
            ctx,
            token_digest=_token_digest(raw_refresh_token),
        )
    )
    if stored_refresh_token is None:
        return False

    session = await auth_session_repository.read_for_update(
        ctx,
        auth_session_id=stored_refresh_token.auth_session_id,
    )
    if session is None:
        return False

    now = get_current_time()
    if stored_refresh_token.revoked_at is None:
        await _revoke_refresh_token(
            ctx,
            auth_refresh_token_id=stored_refresh_token.auth_refresh_token_id,
            revoked_at=now,
        )
    if session.revoked_at is None:
        await _revoke_session(ctx, session=session, revoked_at=now)
    return True


async def read_user_sessions(ctx: IContext) -> list[AuthSession]:
    """List active device sessions of the authenticated user.

    Returns
    -------
    list[AuthSession]
        Active sessions ordered by recent use.
    """
    require_user(ctx)
    return await auth_session_repository.read_active_for_user(
        ctx,
        user_id=ctx.user.user_id,
        now=get_current_time(),
    )


async def revoke_user_session(ctx: IContext, *, auth_session_id: int) -> bool:
    """Revoke one device session owned by the authenticated user.

    Returns
    -------
    bool
        Whether an owned active session was found and revoked.
    """
    require_user(ctx)
    session = await auth_session_repository.read_for_update(
        ctx,
        auth_session_id=auth_session_id,
    )
    if (
        session is None
        or session.user_id != ctx.user.user_id
        or session.revoked_at is not None
    ):
        return False

    await _revoke_session(ctx, session=session, revoked_at=get_current_time())
    return True


async def _consume_login_code(
    ctx: IContext,
    *,
    challenge_id: str,
    code: str,
) -> tuple[str, UiLanguage, datetime] | None:
    if not challenge_id.strip() or not _is_authentication_code(code):
        return None
    secret = _otp_secret(ctx)

    challenge = await auth_challenge_repository.read_for_verification(
        ctx,
        public_id=challenge_id,
    )
    if challenge is None:
        return None

    now = get_current_time()
    settings = ctx.settings
    if challenge.consumed_at is not None:
        return None
    if challenge.attempt_count >= settings.auth_otp_max_attempts:
        return None
    if now >= challenge.expires_at:
        await auth_challenge_repository.update(
            ctx,
            auth_challenge_id=challenge.auth_challenge_id,
            entity=AuthChallengeUpdate.model_construct(consumed_at=now),
        )
        return None

    expected_digest = _authentication_code_digest(
        public_id=challenge.public_id,
        code=code,
        secret=secret,
    )
    if not hmac.compare_digest(challenge.code_digest, expected_digest):
        attempt_count = challenge.attempt_count + 1
        await auth_challenge_repository.update(
            ctx,
            auth_challenge_id=challenge.auth_challenge_id,
            entity=AuthChallengeUpdate.model_construct(
                attempt_count=attempt_count,
                consumed_at=(
                    now if attempt_count >= settings.auth_otp_max_attempts else None
                ),
            ),
        )
        return None

    await auth_challenge_repository.update(
        ctx,
        auth_challenge_id=challenge.auth_challenge_id,
        entity=AuthChallengeUpdate.model_construct(consumed_at=now),
    )
    language: UiLanguage = (
        challenge.language if challenge.language in UI_LANGUAGES else 'pt-BR'
    )
    return challenge.email, language, now


async def _create_session(
    ctx: IContext,
    *,
    user: User,
    is_new_user: bool,
    device_id: str,
    platform: str,
    device_name: str | None,
    request_ip: str | None,
    user_agent: str | None,
    now: datetime,
) -> IssuedAuthenticationSession:
    access_token = _new_opaque_token()
    refresh_token = _new_opaque_token()
    absolute_expires_at = now + timedelta(
        days=ctx.settings.auth_session_absolute_ttl_days
    )
    access_expires_at = min(
        now + timedelta(minutes=ctx.settings.auth_access_token_ttl_minutes),
        absolute_expires_at,
    )
    refresh_expires_at = min(
        now + timedelta(days=ctx.settings.auth_refresh_token_idle_ttl_days),
        absolute_expires_at,
    )
    session = await auth_session_repository.create(
        ctx,
        entity=AuthSessionCreate(
            user_id=user.user_id,
            access_token_digest=_token_digest(access_token),
            device_id=device_id,
            device_name=device_name,
            platform=platform,
            request_ip=request_ip,
            user_agent=user_agent,
            access_expires_at=access_expires_at,
            absolute_expires_at=absolute_expires_at,
            authenticated_at=now,
            last_used_at=now,
            revoked_at=None,
        ),
    )
    await auth_refresh_token_repository.create(
        ctx,
        entity=AuthRefreshTokenCreate(
            auth_session_id=session.auth_session_id,
            token_digest=_token_digest(refresh_token),
            expires_at=refresh_expires_at,
            consumed_at=None,
            replaced_by_auth_refresh_token_id=None,
            revoked_at=None,
        ),
    )
    return _issued_session_result(
        session=session,
        user=user,
        is_new_user=is_new_user,
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        now=now,
    )


async def _revoke_session(
    ctx: IContext,
    *,
    session: AuthSession,
    revoked_at: datetime,
) -> None:
    await auth_session_repository.update(
        ctx,
        auth_session_id=session.auth_session_id,
        entity=AuthSessionUpdate.model_construct(revoked_at=revoked_at),
    )


async def _revoke_refresh_token(
    ctx: IContext,
    *,
    auth_refresh_token_id: int,
    revoked_at: datetime,
) -> None:
    await auth_refresh_token_repository.update(
        ctx,
        auth_refresh_token_id=auth_refresh_token_id,
        entity=AuthRefreshTokenUpdate.model_construct(revoked_at=revoked_at),
    )


async def _enforce_request_limits(
    ctx: IContext,
    *,
    email: str,
    request_ip: str | None,
    now: datetime,
) -> None:
    settings = ctx.settings
    window_start = now - timedelta(seconds=settings.auth_otp_request_window_seconds)
    email_requests = await auth_challenge_repository.count_recent_for_email(
        ctx,
        email=email,
        since=window_start,
    )
    if email_requests >= settings.auth_otp_max_requests_per_email:
        raise AuthenticationRateLimitError(
            retry_after_seconds=settings.auth_otp_request_window_seconds,
        )

    if request_ip is not None:
        ip_requests = await auth_challenge_repository.count_recent_for_ip(
            ctx,
            request_ip=request_ip,
            since=window_start,
        )
        if ip_requests >= settings.auth_otp_max_requests_per_ip:
            raise AuthenticationRateLimitError(
                retry_after_seconds=settings.auth_otp_request_window_seconds,
            )

    latest = await auth_challenge_repository.read_latest_for_email(ctx, email=email)
    if latest is None:
        return

    elapsed_seconds = (now - latest.created_at).total_seconds()
    cooldown = settings.auth_otp_resend_cooldown_seconds
    if elapsed_seconds < cooldown:
        raise AuthenticationRateLimitError(
            retry_after_seconds=math.ceil(cooldown - elapsed_seconds),
        )


def _issued_session_result(
    *,
    session: AuthSession,
    user: User,
    access_token: str,
    refresh_token: str,
    access_expires_at: datetime,
    refresh_expires_at: datetime,
    now: datetime,
    is_new_user: bool = False,
) -> IssuedAuthenticationSession:
    return IssuedAuthenticationSession(
        auth_session_id=session.auth_session_id,
        access_token=access_token,
        access_expires_at=access_expires_at,
        access_expires_in_seconds=max(
            1,
            math.ceil((access_expires_at - now).total_seconds()),
        ),
        refresh_token=refresh_token,
        refresh_expires_at=refresh_expires_at,
        refresh_expires_in_seconds=max(
            1,
            math.ceil((refresh_expires_at - now).total_seconds()),
        ),
        user=user,
        is_new_user=is_new_user,
    )


def _validate_device(
    *,
    device_id: str,
    platform: str,
    device_name: str | None,
) -> tuple[str, str, str | None]:
    normalized_device_id = device_id.strip()
    normalized_platform = platform.strip().casefold()
    normalized_device_name = device_name.strip() if device_name else None
    if not 8 <= len(normalized_device_id) <= 128:
        raise AuthenticationRequestError(
            'Device identifier must contain between 8 and 128 characters.'
        )
    if normalized_platform not in _SUPPORTED_PLATFORMS:
        raise AuthenticationRequestError('Unsupported authentication platform.')
    if normalized_device_name is not None and len(normalized_device_name) > 255:
        raise AuthenticationRequestError('Device name is too long.')
    return normalized_device_id, normalized_platform, normalized_device_name


def _canonical_email(email: str) -> str:
    canonical = email.strip().lower()
    local, _, domain = canonical.rpartition('@')
    if (
        not local
        or '.' not in domain
        or len(canonical) > _MAX_EMAIL_LENGTH
        or any(character.isspace() for character in canonical)
    ):
        raise AuthenticationRequestError('Invalid email address.')
    return canonical


def _otp_secret(ctx: IContext) -> str:
    secret = ctx.settings.auth_otp_secret
    if secret is None:
        raise AuthenticationUnavailableError('AUTH_OTP_SECRET is not configured.')
    return secret.get_secret_value()


def _is_authentication_code(code: str) -> bool:
    return len(code) == _OTP_DIGITS and code.isascii() and code.isdigit()


def _authentication_code_digest(*, public_id: str, code: str, secret: str) -> str:
    payload = f'{public_id}:{code}'.encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _new_opaque_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


__all__ = (
    'DEV_LOGIN_CODE',
    'AuthenticatedSession',
    'AuthenticationChallengeResult',
    'AuthenticationError',
    'AuthenticationRateLimitError',
    'AuthenticationRequestError',
    'AuthenticationUnavailableError',
    'IssuedAuthenticationSession',
    'authenticate_session',
    'read_user_sessions',
    'refresh_session',
    'request_login_code',
    'revoke_session_by_refresh_token',
    'revoke_user_session',
    'verify_login_code',
)
