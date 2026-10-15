"""Context mock and builders shared by the service unit tests."""

from pathlib import Path

from pydantic import SecretStr

from app.infra.context import Context
from app.infra.settings import ROOT_DIR, Settings
from app.models.resume import Resume
from app.models.user import User

TEMPLATES_DIR = ROOT_DIR / 'templates'
TEST_OTP_SECRET = 'test-authentication-secret-at-least-32-chars'  # ruff: ignore[hardcoded-password-string]


def make_settings(**overrides: object) -> Settings:
    """Build settings that do not read the environment or a ``.env`` file.

    Parameters
    ----------
    **overrides : object
        Setting values that replace the defaults below.

    Returns
    -------
    Settings
        Settings built without validation. The templates are the ones of the
        repository; data and output go to ``/nonexistent`` unless overridden.
    """
    values: dict[str, object] = {
        'resume_data_dir': Path('/nonexistent/data'),
        'resume_templates_dir': TEMPLATES_DIR,
        'resume_output_dir': Path('/nonexistent/build'),
        'latex_command': 'pdflatex',
        'pdftotext_command': 'pdftotext',
        'latex_timeout_seconds': 60.0,
        'auth_otp_secret': SecretStr(TEST_OTP_SECRET),
        'auth_otp_ttl_seconds': 600,
        'auth_otp_max_attempts': 5,
        'auth_otp_resend_cooldown_seconds': 60,
        'auth_otp_request_window_seconds': 3600,
        'auth_otp_max_requests_per_email': 5,
        'auth_otp_max_requests_per_ip': 20,
        'auth_access_token_ttl_minutes': 60,
        'auth_refresh_token_idle_ttl_days': 30,
        'auth_session_absolute_ttl_days': 90,
    }
    values.update(overrides)
    return Settings.model_construct(**values)  # ty: ignore[invalid-argument-type]


def make_user(
    *,
    user_id: int = 1,
    email: str = 'ana@example.com',
    name: str | None = 'Ana',
) -> User:
    """Build a detached user.

    Parameters
    ----------
    user_id : int, optional
        User identifier.
    email : str, optional
        Email in lowercase.
    name : str | None, optional
        Display name.

    Returns
    -------
    User
        Detached user that no database session tracks.
    """
    return User(
        user_id=user_id,
        email=email,
        name=name,
        ui_language='pt-BR',
        resume_language='pt',
        default_template='classic',
    )


def mock_context(
    *,
    user: User | None = None,
    settings: Settings | None = None,
) -> Context:
    """Build the context a service receives in a unit test.

    The context has no PostgreSQL session and no request, so reading
    ``postgres`` or ``request`` raises ``ValueError``. A repository call that
    the test did not replace therefore fails instead of reaching a database.

    Parameters
    ----------
    user : User | None, optional
        Authenticated user. Without one, reading ``user`` raises
        ``ValueError``, as it does for an anonymous operation.
    settings : Settings | None, optional
        Application settings. The default is ``make_settings()``.

    Returns
    -------
    Context
        Context holding only the settings.
    """
    return Context(
        user=user,
        settings=make_settings() if settings is None else settings,
    )


def make_resume(**overrides: object) -> Resume:
    """Build a small valid resume with Portuguese accents and LaTeX characters.

    Parameters
    ----------
    **overrides : object
        Top-level resume fields that replace the defaults below.

    Returns
    -------
    Resume
        The validated resume.
    """
    data: dict[str, object] = {
        'basics': {
            'name': 'Ana Souza',
            'headline': {'pt': 'Engenheira de Software', 'en': 'Software Engineer'},
            'location': 'São Paulo, SP',
            'email': 'ana@example.com',
            'links': ['github.com/ana'],
        },
        'summary': {'pt': 'Integração contínua & 100% testes.', 'en': 'CI & tests.'},
        'experience': [
            {
                'id': 'acme',
                'company': 'Acme',
                'title': {'pt': 'Engenheira II', 'en': 'Engineer II'},
                'start': '2022-03',
                'end': None,
                'bullets': [
                    {
                        'id': 'acme-latency',
                        'tags': ['redis'],
                        'text': 'Reduzi a latência p95 de 800 ms para 180 ms.',
                    }
                ],
                'technologies': ['Redis', 'C#'],
            }
        ],
        'skills': [{'category': {'pt': 'Linguagens'}, 'items': ['Python', 'Go']}],
        'education': [
            {'institution': 'UFPR', 'degree': 'Ciência da Computação', 'start': '2018'}
        ],
    }
    data.update(overrides)
    return Resume.model_validate(data)


__all__ = (
    'TEMPLATES_DIR',
    'TEST_OTP_SECRET',
    'make_resume',
    'make_settings',
    'make_user',
    'mock_context',
)
