"""Authenticated device session models."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from app.models.base import OptionalModel, SQLBaseModel


class AuthSessionBase(SQLBaseModel):
    """Represent shared authenticated session fields."""

    user_id: int = Field(foreign_key='app_user.user_id', sa_type=BigInteger)
    access_token_digest: str = Field(max_length=64)
    device_id: str = Field(max_length=128)
    device_name: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=16)
    request_ip: str | None = Field(default=None, max_length=45)
    user_agent: str | None = Field(default=None, max_length=512)
    access_expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    absolute_expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    authenticated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text('now()'),
        ),
    )
    last_used_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class AuthSession(AuthSessionBase, table=True):
    """Represent one revocable authenticated device session."""

    __tablename__ = 'auth_session'
    __table_args__ = (
        CheckConstraint(
            "platform IS NULL OR platform IN ('android', 'ios', 'web')",
            name='ck_auth_session_supported_platform',
        ),
        Index(
            'ix_auth_session_user_absolute_expires_at',
            'user_id',
            'absolute_expires_at',
        ),
        UniqueConstraint(
            'access_token_digest',
            name='uq_auth_session_access_token_digest',
        ),
    )

    auth_session_id: int = Field(
        default=None,
        nullable=False,
        primary_key=True,
        sa_type=BigInteger,
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text('now()'),
        ),
        default=None,
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text('now()'),
            onupdate=text('now()'),
        ),
        default=None,
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class AuthSessionCreate(AuthSessionBase):
    """Represent data required to create an authenticated device session."""


class AuthSessionUpdate(AuthSessionBase, OptionalModel):
    """Represent data used to update an authenticated device session."""


class AuthSessionFilter(AuthSessionBase, OptionalModel):
    """Represent filters used to read authenticated device sessions."""
