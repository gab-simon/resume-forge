"""Application settings."""

import tomllib
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PositiveFloat, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """Application settings."""

    # Application
    app_name: str = ''
    app_version: str = ''
    app_description: str = ''

    # Logging
    log_level: Literal[
        'TRACE', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL'
    ] = 'INFO'

    # OpenAPI
    openapi_enabled: bool = True

    # CORS
    cors_allowed_origins: str = ''

    # Postgres database. Optional, so the CLI builds a resume without a
    # database; the API readiness probe answers 503 while it is not set.
    db_url: str | None = None
    db_migration_url: str | None = None
    db_debug: bool = False
    db_pool_recycle_seconds: int = 3600
    # Each Uvicorn worker has its own pool and opens up to
    # db_pool_size + db_max_overflow connections.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    # Passwordless authentication. Optional, so the CLI runs without it; the
    # login routes answer 503 while it is not set.
    auth_otp_secret: SecretStr | None = Field(default=None, min_length=32)
    auth_otp_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    auth_otp_max_attempts: int = Field(default=5, ge=1, le=10)
    auth_otp_resend_cooldown_seconds: int = Field(default=60, ge=1, le=3600)
    auth_otp_request_window_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_otp_max_requests_per_email: int = Field(default=5, ge=1, le=100)
    auth_otp_max_requests_per_ip: int = Field(default=20, ge=1, le=1000)
    auth_access_token_ttl_minutes: int = Field(default=60, ge=5, le=1440)
    auth_refresh_token_idle_ttl_days: int = Field(default=30, ge=1, le=180)
    auth_session_absolute_ttl_days: int = Field(default=90, ge=1, le=365)

    # Email delivery of login codes. ``console`` writes the code to the log and
    # is meant only for local development.
    email_backend: Literal['smtp', 'console'] = 'smtp'
    email_from: str = 'Resume Forge <no-reply@localhost>'
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_timeout_seconds: PositiveFloat = 10.0

    # Resume sources and outputs
    resume_data_dir: Path = ROOT_DIR / 'data'
    resume_templates_dir: Path = ROOT_DIR / 'templates'
    resume_output_dir: Path = ROOT_DIR / 'build'

    # External tools. The Docker image installs both; on the host they come
    # from TeX Live and poppler-utils.
    latex_command: str = 'pdflatex'
    pdftotext_command: str = 'pdftotext'
    latex_timeout_seconds: PositiveFloat = 60.0

    # Config
    model_config = SettingsConfigDict(env_file='.env', extra='allow')

    @property
    def cors_origins(self) -> list[str]:
        """Origins allowed to call the API from a browser."""
        return [
            origin.strip().rstrip('/')
            for origin in self.cors_allowed_origins.split(',')
            if origin.strip()
        ]

    @property
    def db_conn_uri(self) -> str:
        """Database connection URI.

        Raises
        ------
        ValueError
            If ``DB_URL`` is not configured.
        """
        if not self.db_url:
            raise ValueError('Database connection URI is not configured.')
        return f'postgresql+psycopg://{self.db_url}'

    @property
    def db_migration_conn_uri(self) -> str:
        """Database connection URI used by Alembic migrations.

        Falls back to the application connection when no migration URL is set.

        Raises
        ------
        ValueError
            If neither ``DB_MIGRATION_URL`` nor ``DB_URL`` is configured.
        """
        url = self.db_migration_url or self.db_url
        if not url:
            raise ValueError('Database connection URI is not configured.')
        return f'postgresql+psycopg://{url}'


@cache
def get_settings() -> Settings:
    """Get the application settings.

    Returns
    -------
    Settings
        The application settings.
    """
    pyproject_path = ROOT_DIR / 'pyproject.toml'

    with pyproject_path.open('rb') as f:
        pyproject = tomllib.load(f)

    return Settings(
        app_name=pyproject['project']['name'],
        app_version=pyproject['project']['version'],
        app_description=pyproject['project']['description'],
    )


__all__ = ('ROOT_DIR', 'Settings', 'get_settings')
