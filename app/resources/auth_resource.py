"""HTTP resources for passwordless email authentication."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field

from app.resources.user_resource import UserResource


class AuthenticationChallengeRequestResource(BaseModel):
    """HTTP payload used to request a login code by email."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr = Field(max_length=320, examples=['ana@example.com'])
    language: Literal['pt-BR', 'en-US'] = Field(
        default='pt-BR',
        description='Language of the email, and of the account if it is new.',
    )


class AuthenticationChallengeResource(BaseModel):
    """Public authentication challenge, the same for known and new emails."""

    challenge_id: str = Field(min_length=32, max_length=64)
    expires_at: AwareDatetime
    expires_in_seconds: int = Field(ge=1)


class AuthenticationCodeResource(BaseModel):
    """HTTP payload used to verify a code for one app or browser installation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r'^[0-9]{6}$',
        examples=['482913'],
    )
    device_id: str = Field(min_length=8, max_length=128)
    platform: Literal['android', 'ios', 'web']
    device_name: str | None = Field(default=None, max_length=255)


class AuthenticationRefreshResource(BaseModel):
    """HTTP payload carrying a rotating refresh token."""

    model_config = ConfigDict(str_strip_whitespace=True)

    refresh_token: str = Field(min_length=32, max_length=512)


class AuthenticationSessionResource(BaseModel):
    """Access and refresh tokens issued after authentication."""

    auth_session_id: int
    access_token: str = Field(min_length=32)
    token_type: Literal['bearer'] = 'bearer'  # ruff: ignore[hardcoded-password-string]
    access_expires_at: AwareDatetime
    access_expires_in_seconds: int = Field(ge=1)
    refresh_token: str = Field(min_length=32)
    refresh_expires_at: AwareDatetime
    refresh_expires_in_seconds: int = Field(ge=1)
    is_new_user: bool
    user: UserResource


class AuthenticationSessionSummaryResource(BaseModel):
    """Safe representation of one authenticated device session."""

    model_config = ConfigDict(from_attributes=True)

    auth_session_id: int
    device_id: str
    device_name: str | None
    platform: str | None
    authenticated_at: AwareDatetime
    last_used_at: AwareDatetime
    access_expires_at: AwareDatetime
    absolute_expires_at: AwareDatetime


class AuthenticationSessionListResource(BaseModel):
    """List of active device sessions owned by a user."""

    items: list[AuthenticationSessionSummaryResource]


__all__ = (
    'AuthenticationChallengeRequestResource',
    'AuthenticationChallengeResource',
    'AuthenticationCodeResource',
    'AuthenticationRefreshResource',
    'AuthenticationSessionListResource',
    'AuthenticationSessionResource',
    'AuthenticationSessionSummaryResource',
)
