"""Unit tests for the passwordless email authentication service."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.infra.auth import AuthorizationError
from app.models.auth_challenge import AuthChallenge
from app.models.auth_refresh_token import AuthRefreshToken
from app.models.auth_session import AuthSession
from app.providers.email_provider import EmailMessage
from app.services import auth_service
from app.services.auth_service import (
    AuthenticationError,
    AuthenticationRateLimitError,
    AuthenticationRequestError,
    AuthenticationUnavailableError,
)
from tests.unit.mocks.context import (
    TEST_OTP_SECRET,
    make_settings,
    make_user,
    mock_context,
)

_NOW = datetime(2026, 10, 14, 13, tzinfo=UTC)
_CODE = '482913'
_PUBLIC_ID = 'challenge-public-id-with-enough-randomness'
_ACCESS_TOKEN = 'access-token'  # ruff: ignore[hardcoded-password-string]
_REFRESH_TOKEN = 'refresh-token'  # ruff: ignore[hardcoded-password-string]


class CaptureSender:
    """Email sender that keeps the messages instead of sending them."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        """Keep one message."""
        self.messages.append(message)


@pytest.fixture(autouse=True)
def _fixed_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_service, 'get_current_time', lambda: _NOW)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _code_digest(code: str = _CODE) -> str:
    return hmac.new(
        TEST_OTP_SECRET.encode(),
        f'{_PUBLIC_ID}:{code}'.encode(),
        hashlib.sha256,
    ).hexdigest()


def _challenge(**overrides: Any) -> AuthChallenge:  # ruff: ignore[any-type]
    values: dict[str, Any] = {
        'auth_challenge_id': 11,
        'email': 'ana@example.com',
        'language': 'en-US',
        'public_id': _PUBLIC_ID,
        'code_digest': _code_digest(),
        'request_ip': '127.0.0.1',
        'expires_at': _NOW + timedelta(minutes=10),
        'attempt_count': 0,
        'consumed_at': None,
        'created_at': _NOW,
        'updated_at': _NOW,
    }
    values.update(overrides)
    return AuthChallenge(**values)


def _session(**overrides: Any) -> AuthSession:  # ruff: ignore[any-type]
    values: dict[str, Any] = {
        'auth_session_id': 13,
        'user_id': 1,
        'access_token_digest': _digest(_ACCESS_TOKEN),
        'device_id': 'browser-123',
        'device_name': None,
        'platform': 'web',
        'request_ip': '127.0.0.1',
        'user_agent': 'test',
        'access_expires_at': _NOW + timedelta(hours=1),
        'absolute_expires_at': _NOW + timedelta(days=90),
        'authenticated_at': _NOW,
        'last_used_at': _NOW,
        'revoked_at': None,
        'created_at': _NOW,
        'updated_at': _NOW,
    }
    values.update(overrides)
    return AuthSession(**values)


def _refresh_token(**overrides: Any) -> AuthRefreshToken:  # ruff: ignore[any-type]
    values: dict[str, Any] = {
        'auth_refresh_token_id': 17,
        'auth_session_id': 13,
        'token_digest': _digest(_REFRESH_TOKEN),
        'expires_at': _NOW + timedelta(days=30),
        'consumed_at': None,
        'replaced_by_auth_refresh_token_id': None,
        'revoked_at': None,
        'created_at': _NOW,
        'updated_at': _NOW,
    }
    values.update(overrides)
    return AuthRefreshToken(**values)


def _mock(monkeypatch: pytest.MonkeyPatch, target: object, **calls: object) -> None:
    for name, value in calls.items():
        mock = value if isinstance(value, AsyncMock) else AsyncMock(return_value=value)
        monkeypatch.setattr(target, name, mock)


def _mock_request_limits(
    monkeypatch: pytest.MonkeyPatch,
    *,
    email_count: int = 0,
    ip_count: int = 0,
    latest: AuthChallenge | None = None,
) -> None:
    _mock(
        monkeypatch,
        auth_service.auth_challenge_repository,
        count_recent_for_email=email_count,
        count_recent_for_ip=ip_count,
        read_latest_for_email=latest,
    )


# request_login_code


async def test_request_login_code_creates_challenge_and_sends_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Store only the code digest and email the code in the requested language."""
    _mock_request_limits(monkeypatch)
    repository = auth_service.auth_challenge_repository
    _mock(
        monkeypatch,
        repository,
        invalidate_open_for_email=0,
        create=_challenge(),
    )
    sender = CaptureSender()

    result = await auth_service.request_login_code(
        mock_context(),
        email='  Ana@Example.COM ',
        language='en-US',
        sender=sender,
        request_ip='10.0.0.1',
    )

    entity = repository.create.await_args.kwargs['entity']  # ty: ignore[unresolved-attribute]
    message = sender.messages[0]
    code = message.subject.rsplit(' ', 1)[-1]
    assert entity.email == 'ana@example.com'
    assert entity.language == 'en-US'
    assert entity.public_id == result.challenge_id
    assert (
        entity.code_digest
        == hmac.new(
            TEST_OTP_SECRET.encode(),
            f'{result.challenge_id}:{code}'.encode(),
            hashlib.sha256,
        ).hexdigest()
    )
    assert code not in entity.code_digest
    assert message.to == 'ana@example.com'
    assert message.subject.startswith('Your Resume Forge sign-in code')
    assert '10 minutes' in message.text
    assert result.expires_at == _NOW + timedelta(minutes=10)
    repository.invalidate_open_for_email.assert_awaited_once()  # ty: ignore[unresolved-attribute]


async def test_request_login_code_writes_portuguese_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Send the Portuguese text for pt-BR."""
    _mock_request_limits(monkeypatch)
    _mock(
        monkeypatch,
        auth_service.auth_challenge_repository,
        invalidate_open_for_email=0,
        create=_challenge(),
    )
    sender = CaptureSender()

    await auth_service.request_login_code(
        mock_context(), email='ana@example.com', language='pt-BR', sender=sender
    )

    assert sender.messages[0].subject.startswith('Seu código de acesso')


@pytest.mark.parametrize(
    ('settings', 'fixed'),
    [
        ({'app_env': 'development', 'smtp_host': None}, True),
        ({'app_env': 'development', 'smtp_host': 'smtp.example.com'}, False),
        ({'app_env': 'production', 'smtp_host': None}, False),
    ],
)
async def test_request_login_code_is_fixed_only_in_development_without_smtp(
    monkeypatch: pytest.MonkeyPatch, settings: dict[str, str | None], fixed: bool
) -> None:
    """Use 123456 only in development without SMTP, never in production."""
    _mock_request_limits(monkeypatch)
    _mock(
        monkeypatch,
        auth_service.auth_challenge_repository,
        invalidate_open_for_email=0,
        create=_challenge(),
    )
    monkeypatch.setattr(auth_service.secrets, 'randbelow', lambda _limit: 654321)
    sender = CaptureSender()

    await auth_service.request_login_code(
        mock_context(settings=make_settings(**settings)),
        email='ana@example.com',
        language='en-US',
        sender=sender,
    )

    code = sender.messages[0].subject.rsplit(' ', 1)[-1]
    assert code == (auth_service.DEV_LOGIN_CODE if fixed else '654321')


@pytest.mark.parametrize(
    'email',
    ['', 'ana', 'ana@', '@example.com', 'ana@localhost', 'a na@example.com'],
)
async def test_request_login_code_rejects_invalid_email(email: str) -> None:
    """Refuse an email without a local part, a domain or with spaces."""
    with pytest.raises(AuthenticationRequestError):
        await auth_service.request_login_code(
            mock_context(), email=email, language='pt-BR', sender=CaptureSender()
        )


async def test_request_login_code_rejects_unknown_language() -> None:
    """Refuse a language the interface does not have."""
    with pytest.raises(AuthenticationRequestError):
        await auth_service.request_login_code(
            mock_context(),
            email='ana@example.com',
            language='es-ES',
            sender=CaptureSender(),
        )


async def test_request_login_code_without_secret_is_unavailable() -> None:
    """Report the missing AUTH_OTP_SECRET instead of failing later."""
    ctx = mock_context(settings=make_settings(auth_otp_secret=None))

    with pytest.raises(AuthenticationUnavailableError):
        await auth_service.request_login_code(
            ctx, email='ana@example.com', language='pt-BR', sender=CaptureSender()
        )


async def test_request_login_code_enforces_the_email_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse a sixth code for the same email inside the window."""
    _mock_request_limits(monkeypatch, email_count=5)

    with pytest.raises(AuthenticationRateLimitError) as error:
        await auth_service.request_login_code(
            mock_context(),
            email='ana@example.com',
            language='pt-BR',
            sender=CaptureSender(),
        )

    assert error.value.retry_after_seconds == 3600


async def test_request_login_code_enforces_the_ip_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse more codes from one address than the IP limit."""
    _mock_request_limits(monkeypatch, ip_count=20)

    with pytest.raises(AuthenticationRateLimitError):
        await auth_service.request_login_code(
            mock_context(),
            email='ana@example.com',
            language='pt-BR',
            sender=CaptureSender(),
            request_ip='10.0.0.1',
        )


async def test_request_login_code_reports_the_remaining_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ask the client to wait the rest of the resend cooldown."""
    _mock_request_limits(
        monkeypatch, latest=_challenge(created_at=_NOW - timedelta(seconds=45))
    )

    with pytest.raises(AuthenticationRateLimitError) as error:
        await auth_service.request_login_code(
            mock_context(),
            email='ana@example.com',
            language='pt-BR',
            sender=CaptureSender(),
        )

    assert error.value.retry_after_seconds == 15


def test_rate_limit_error_keeps_retry_delay_at_least_one_second() -> None:
    """Never answer Retry-After 0."""
    assert AuthenticationRateLimitError(retry_after_seconds=0).retry_after_seconds == 1


# verify_login_code


def _mock_session_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(
        monkeypatch,
        auth_service.auth_session_repository,
        create=_session(),
    )
    _mock(
        monkeypatch,
        auth_service.auth_refresh_token_repository,
        create=_refresh_token(),
    )


async def _verify(code: str = _CODE, **kwargs: Any) -> object:  # ruff: ignore[any-type]
    return await auth_service.verify_login_code(
        mock_context(),
        challenge_id=_PUBLIC_ID,
        code=code,
        device_id=kwargs.get('device_id', 'browser-123'),
        platform=kwargs.get('platform', 'web'),
    )


async def test_verify_login_code_signs_in_an_existing_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consume the challenge and issue tokens for the account of the email."""
    user = make_user()
    challenges = auth_service.auth_challenge_repository
    _mock(monkeypatch, challenges, read_for_verification=_challenge(), update=None)
    _mock(
        monkeypatch,
        auth_service.user_repository,
        read_user_by_email_for_update=user,
        create=AsyncMock(),
    )
    _mock_session_creation(monkeypatch)

    result = await _verify()

    assert isinstance(result, auth_service.IssuedAuthenticationSession)
    assert result.user is user
    assert not result.is_new_user
    assert result.access_expires_in_seconds == 3600
    assert result.refresh_expires_in_seconds == 30 * 86400
    assert challenges.update.await_args.kwargs['entity'].consumed_at == _NOW  # ty: ignore[unresolved-attribute]
    session_entity = auth_service.auth_session_repository.create.await_args.kwargs[  # ty: ignore[unresolved-attribute]
        'entity'
    ]
    assert session_entity.access_token_digest == _digest(result.access_token)
    auth_service.user_repository.create.assert_not_awaited()  # ty: ignore[unresolved-attribute]


async def test_verify_login_code_creates_the_account_of_a_new_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create the user with the language of the challenge on its first login."""
    created = make_user(user_id=5, name=None)
    _mock(
        monkeypatch,
        auth_service.auth_challenge_repository,
        read_for_verification=_challenge(language='en-US'),
        update=None,
    )
    _mock(
        monkeypatch,
        auth_service.user_repository,
        read_user_by_email_for_update=None,
        create=created,
    )
    _mock_session_creation(monkeypatch)

    result = await _verify()

    entity = auth_service.user_repository.create.await_args.kwargs['entity']  # ty: ignore[unresolved-attribute]
    assert entity.email == 'ana@example.com'
    assert entity.ui_language == 'en-US'
    assert entity.resume_language == 'en'
    assert isinstance(result, auth_service.IssuedAuthenticationSession)
    assert result.is_new_user


@pytest.mark.parametrize('code', ['12345', '1234567', 'abcdef', '12 456'])
async def test_verify_login_code_rejects_malformed_codes_without_lookup(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """Return None before reading the database."""
    lookup = AsyncMock()
    monkeypatch.setattr(
        auth_service.auth_challenge_repository, 'read_for_verification', lookup
    )

    assert await _verify(code) is None
    lookup.assert_not_awaited()


@pytest.mark.parametrize(
    'challenge',
    [None, _challenge(consumed_at=_NOW), _challenge(attempt_count=5)],
)
async def test_verify_login_code_rejects_unusable_challenges(
    monkeypatch: pytest.MonkeyPatch, challenge: AuthChallenge | None
) -> None:
    """Return None for an unknown, consumed or blocked challenge."""
    update = AsyncMock()
    _mock(
        monkeypatch,
        auth_service.auth_challenge_repository,
        read_for_verification=challenge,
        update=update,
    )

    assert await _verify() is None
    update.assert_not_awaited()


async def test_verify_login_code_consumes_an_expired_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close an expired challenge so it cannot be tried again."""
    repository = auth_service.auth_challenge_repository
    _mock(
        monkeypatch,
        repository,
        read_for_verification=_challenge(expires_at=_NOW),
        update=None,
    )

    assert await _verify() is None
    assert repository.update.await_args.kwargs['entity'].consumed_at == _NOW  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    ('attempt_count', 'consumed_at'),
    [(0, None), (4, _NOW)],
)
async def test_verify_login_code_counts_wrong_codes(
    monkeypatch: pytest.MonkeyPatch,
    attempt_count: int,
    consumed_at: datetime | None,
) -> None:
    """Count a wrong code and close the challenge on the last attempt."""
    repository = auth_service.auth_challenge_repository
    _mock(
        monkeypatch,
        repository,
        read_for_verification=_challenge(attempt_count=attempt_count),
        update=None,
    )

    assert await _verify('000000') is None
    entity = repository.update.await_args.kwargs['entity']  # ty: ignore[unresolved-attribute]
    assert entity.attempt_count == attempt_count + 1
    assert entity.consumed_at == consumed_at


@pytest.mark.parametrize(
    'device',
    [{'device_id': 'short'}, {'platform': 'desktop'}],
)
async def test_verify_login_code_validates_the_device(device: dict[str, str]) -> None:
    """Refuse a short device identifier or an unknown platform."""
    with pytest.raises(AuthenticationRequestError):
        await _verify(**device)


# refresh_session


async def test_refresh_rotates_both_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """Consume the refresh token, link its successor and change the access token."""
    stored = _refresh_token()
    successor = _refresh_token(auth_refresh_token_id=18, token_digest='next')  # ruff: ignore[hardcoded-password-func-arg]
    refresh_tokens = auth_service.auth_refresh_token_repository
    sessions = auth_service.auth_session_repository
    _mock(
        monkeypatch,
        refresh_tokens,
        read_by_token_digest_for_update=stored,
        create=successor,
        update=stored,
    )
    _mock(monkeypatch, sessions, read_for_update=_session(), update=_session())
    _mock(monkeypatch, auth_service.user_repository, read_user=make_user())

    result = await auth_service.refresh_session(
        mock_context(), refresh_token=_REFRESH_TOKEN
    )

    assert result is not None
    assert result.refresh_token != _REFRESH_TOKEN
    consumed = refresh_tokens.update.await_args.kwargs['entity']  # ty: ignore[unresolved-attribute]
    assert consumed.consumed_at == _NOW
    assert consumed.replaced_by_auth_refresh_token_id == 18
    session_entity = sessions.update.await_args.kwargs['entity']  # ty: ignore[unresolved-attribute]
    assert session_entity.access_token_digest == _digest(result.access_token)


async def test_refresh_token_reuse_revokes_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat a consumed refresh token as stolen and revoke its whole session."""
    sessions = auth_service.auth_session_repository
    _mock(
        monkeypatch,
        auth_service.auth_refresh_token_repository,
        read_by_token_digest_for_update=_refresh_token(consumed_at=_NOW),
    )
    _mock(monkeypatch, sessions, read_for_update=_session(), update=None)

    assert (
        await auth_service.refresh_session(mock_context(), refresh_token=_REFRESH_TOKEN)
        is None
    )
    assert sessions.update.await_args.kwargs['entity'].revoked_at == _NOW  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    ('stored', 'session'),
    [
        (_refresh_token(expires_at=_NOW), _session()),
        (_refresh_token(), _session(revoked_at=_NOW)),
        (_refresh_token(), _session(absolute_expires_at=_NOW)),
    ],
)
async def test_refresh_rejects_an_unusable_session_and_revokes_the_token(
    monkeypatch: pytest.MonkeyPatch,
    stored: AuthRefreshToken,
    session: AuthSession,
) -> None:
    """Revoke the token of an expired token or session."""
    refresh_tokens = auth_service.auth_refresh_token_repository
    _mock(
        monkeypatch,
        refresh_tokens,
        read_by_token_digest_for_update=stored,
        update=None,
    )
    _mock(
        monkeypatch,
        auth_service.auth_session_repository,
        read_for_update=session,
        update=None,
    )

    assert (
        await auth_service.refresh_session(mock_context(), refresh_token=_REFRESH_TOKEN)
        is None
    )
    assert refresh_tokens.update.await_args.kwargs['entity'].revoked_at == _NOW  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    ('stored', 'session'),
    [(None, _session()), (_refresh_token(), None)],
)
async def test_refresh_returns_none_for_unknown_rows(
    monkeypatch: pytest.MonkeyPatch,
    stored: AuthRefreshToken | None,
    session: AuthSession | None,
) -> None:
    """Return None when the token or its session does not exist."""
    _mock(
        monkeypatch,
        auth_service.auth_refresh_token_repository,
        read_by_token_digest_for_update=stored,
    )
    _mock(monkeypatch, auth_service.auth_session_repository, read_for_update=session)

    assert (
        await auth_service.refresh_session(mock_context(), refresh_token=_REFRESH_TOKEN)
        is None
    )


async def test_refresh_returns_none_for_a_blank_token() -> None:
    """Do not look up an empty token."""
    assert (
        await auth_service.refresh_session(mock_context(), refresh_token='  ') is None  # ruff: ignore[hardcoded-password-func-arg]
    )


async def test_refresh_revokes_the_session_when_the_user_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close the session of a deleted account."""
    sessions = auth_service.auth_session_repository
    _mock(
        monkeypatch,
        auth_service.auth_refresh_token_repository,
        read_by_token_digest_for_update=_refresh_token(),
    )
    _mock(monkeypatch, sessions, read_for_update=_session(), update=None)
    _mock(monkeypatch, auth_service.user_repository, read_user=None)

    assert (
        await auth_service.refresh_session(mock_context(), refresh_token=_REFRESH_TOKEN)
        is None
    )
    sessions.update.assert_awaited_once()  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    ('token_update', 'session_update'),
    [(None, _session()), (_refresh_token(), None)],
)
async def test_refresh_fails_when_a_locked_row_disappears(
    monkeypatch: pytest.MonkeyPatch,
    token_update: AuthRefreshToken | None,
    session_update: AuthSession | None,
) -> None:
    """Fail the request instead of issuing tokens that were not stored."""
    _mock(
        monkeypatch,
        auth_service.auth_refresh_token_repository,
        read_by_token_digest_for_update=_refresh_token(),
        create=_refresh_token(auth_refresh_token_id=18),
        update=token_update,
    )
    _mock(
        monkeypatch,
        auth_service.auth_session_repository,
        read_for_update=_session(),
        update=session_update,
    )
    _mock(monkeypatch, auth_service.user_repository, read_user=make_user())

    with pytest.raises(RuntimeError):
        await auth_service.refresh_session(mock_context(), refresh_token=_REFRESH_TOKEN)


# authenticate_session


async def test_authenticate_session_reloads_the_user_and_updates_last_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the session and the current state of its user."""
    user = make_user()
    sessions = auth_service.auth_session_repository
    _mock(
        monkeypatch,
        sessions,
        read_by_access_token_digest=_session(),
        update=_session(),
    )
    _mock(monkeypatch, auth_service.user_repository, read_user=user)

    result = await auth_service.authenticate_session(
        mock_context(), access_token=_ACCESS_TOKEN
    )

    assert result.user is user
    assert sessions.update.await_args.kwargs['entity'].last_used_at == _NOW  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    'session',
    [
        None,
        _session(revoked_at=_NOW),
        _session(access_expires_at=_NOW),
        _session(absolute_expires_at=_NOW),
    ],
)
async def test_authenticate_session_rejects_unusable_sessions(
    monkeypatch: pytest.MonkeyPatch, session: AuthSession | None
) -> None:
    """Reject an unknown, revoked or expired token."""
    _mock(
        monkeypatch,
        auth_service.auth_session_repository,
        read_by_access_token_digest=session,
    )

    with pytest.raises(AuthenticationError):
        await auth_service.authenticate_session(
            mock_context(), access_token=_ACCESS_TOKEN
        )


async def test_authenticate_session_rejects_blank_token_and_missing_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an empty token and the session of a deleted account."""
    with pytest.raises(AuthenticationError):
        await auth_service.authenticate_session(mock_context(), access_token=' ')  # ruff: ignore[hardcoded-password-func-arg]

    _mock(
        monkeypatch,
        auth_service.auth_session_repository,
        read_by_access_token_digest=_session(),
    )
    _mock(monkeypatch, auth_service.user_repository, read_user=None)
    with pytest.raises(AuthenticationError):
        await auth_service.authenticate_session(
            mock_context(), access_token=_ACCESS_TOKEN
        )


# logout and session management


async def test_revoke_by_refresh_token_revokes_token_and_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Log out by revoking the refresh token and its session."""
    refresh_tokens = auth_service.auth_refresh_token_repository
    sessions = auth_service.auth_session_repository
    _mock(
        monkeypatch,
        refresh_tokens,
        read_by_token_digest_for_update=_refresh_token(),
        update=None,
    )
    _mock(monkeypatch, sessions, read_for_update=_session(), update=None)

    assert await auth_service.revoke_session_by_refresh_token(
        mock_context(), refresh_token=_REFRESH_TOKEN
    )
    refresh_tokens.update.assert_awaited_once()  # ty: ignore[unresolved-attribute]
    sessions.update.assert_awaited_once()  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    ('token', 'stored', 'session'),
    [
        (' ', None, None),
        (_REFRESH_TOKEN, None, None),
        (_REFRESH_TOKEN, _refresh_token(), None),
    ],
)
async def test_revoke_by_refresh_token_returns_false_for_unknown_rows(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    stored: AuthRefreshToken | None,
    session: AuthSession | None,
) -> None:
    """Report that no session was found."""
    _mock(
        monkeypatch,
        auth_service.auth_refresh_token_repository,
        read_by_token_digest_for_update=stored,
    )
    _mock(monkeypatch, auth_service.auth_session_repository, read_for_update=session)

    assert not await auth_service.revoke_session_by_refresh_token(
        mock_context(), refresh_token=token
    )


async def test_revoke_by_refresh_token_is_idempotent_for_revoked_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not write again when the token and the session are already revoked."""
    refresh_tokens = auth_service.auth_refresh_token_repository
    sessions = auth_service.auth_session_repository
    _mock(
        monkeypatch,
        refresh_tokens,
        read_by_token_digest_for_update=_refresh_token(revoked_at=_NOW),
        update=None,
    )
    _mock(monkeypatch, sessions, read_for_update=_session(revoked_at=_NOW), update=None)

    assert await auth_service.revoke_session_by_refresh_token(
        mock_context(), refresh_token=_REFRESH_TOKEN
    )
    refresh_tokens.update.assert_not_awaited()  # ty: ignore[unresolved-attribute]
    sessions.update.assert_not_awaited()  # ty: ignore[unresolved-attribute]


async def test_read_user_sessions_lists_the_sessions_of_the_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List the sessions of the authenticated user only."""
    read = AsyncMock(return_value=[_session()])
    monkeypatch.setattr(
        auth_service.auth_session_repository, 'read_active_for_user', read
    )

    sessions = await auth_service.read_user_sessions(
        mock_context(user=make_user(user_id=3))
    )

    assert len(sessions) == 1
    assert read.await_args.kwargs['user_id'] == 3  # ty: ignore[unresolved-attribute]


async def test_session_management_requires_a_user() -> None:
    """Refuse to list or revoke sessions without an authenticated user."""
    with pytest.raises(AuthorizationError):
        await auth_service.read_user_sessions(mock_context())
    with pytest.raises(AuthorizationError):
        await auth_service.revoke_user_session(mock_context(), auth_session_id=13)


@pytest.mark.parametrize(
    ('session', 'revoked'),
    [
        (None, False),
        (_session(user_id=2), False),
        (_session(revoked_at=_NOW), False),
        (_session(), True),
    ],
)
async def test_revoke_user_session_revokes_only_an_own_active_session(
    monkeypatch: pytest.MonkeyPatch,
    session: AuthSession | None,
    revoked: bool,
) -> None:
    """Never revoke a session of another user."""
    sessions = auth_service.auth_session_repository
    _mock(monkeypatch, sessions, read_for_update=session, update=None)

    result = await auth_service.revoke_user_session(
        mock_context(user=make_user(user_id=1)), auth_session_id=13
    )

    assert result is revoked
    assert sessions.update.await_count == int(revoked)  # ty: ignore[unresolved-attribute]
