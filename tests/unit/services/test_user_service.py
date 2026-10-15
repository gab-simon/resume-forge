"""Unit tests for the user profile service."""

from unittest.mock import AsyncMock

import pytest

from app.infra.auth import AuthorizationError
from app.models.user import UserUpdate
from app.services import user_service
from app.services.user_service import UserPreferenceError
from tests.unit.mocks.context import make_user, mock_context


def test_read_profile_returns_the_authenticated_user() -> None:
    """Return the user loaded for the request."""
    user = make_user()

    assert user_service.read_profile(mock_context(user=user)) is user


async def test_profile_requires_a_user() -> None:
    """Refuse an anonymous context."""
    with pytest.raises(AuthorizationError):
        user_service.read_profile(mock_context())
    with pytest.raises(AuthorizationError):
        await user_service.update_profile(
            mock_context(), entity=UserUpdate.model_construct()
        )


async def test_update_profile_saves_preferences_and_ignores_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Strip the name and never change the login email."""
    updated = make_user(name='Ana Souza')
    update = AsyncMock(return_value=updated)
    monkeypatch.setattr(user_service.user_repository, 'update', update)

    result = await user_service.update_profile(
        mock_context(user=make_user(user_id=4)),
        entity=UserUpdate.model_construct(
            name='  Ana Souza ',
            email='other@example.com',
            ui_language='en-US',
            resume_language='en',
            default_template='classic',
        ),
    )

    assert result is updated
    assert update.await_args.kwargs['user_id'] == 4  # ty: ignore[unresolved-attribute]
    assert update.await_args.kwargs['entity'].model_dump(exclude_unset=True) == {  # ty: ignore[unresolved-attribute]
        'name': 'Ana Souza',
        'ui_language': 'en-US',
        'resume_language': 'en',
        'default_template': 'classic',
    }


async def test_update_profile_clears_a_blank_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Store a blank name as no name."""
    update = AsyncMock(return_value=make_user(name=None))
    monkeypatch.setattr(user_service.user_repository, 'update', update)

    await user_service.update_profile(
        mock_context(user=make_user()), entity=UserUpdate.model_construct(name='  ')
    )

    assert update.await_args.kwargs['entity'].name is None  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    'changes',
    [
        {'ui_language': 'es-ES'},
        {'resume_language': 'es'},
        {'default_template': 'nope'},
    ],
)
async def test_update_profile_rejects_unknown_preferences(
    changes: dict[str, str],
) -> None:
    """Refuse a language or a template that does not exist."""
    with pytest.raises(UserPreferenceError):
        await user_service.update_profile(
            mock_context(user=make_user()),
            entity=UserUpdate.model_construct(**changes),  # ty: ignore[invalid-argument-type]
        )


async def test_update_profile_fails_when_the_user_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail loudly instead of answering with stale data."""
    monkeypatch.setattr(
        user_service.user_repository, 'update', AsyncMock(return_value=None)
    )

    with pytest.raises(RuntimeError):
        await user_service.update_profile(
            mock_context(user=make_user()), entity=UserUpdate.model_construct(name='A')
        )
