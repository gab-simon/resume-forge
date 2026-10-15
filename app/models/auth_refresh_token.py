"""Rotating refresh-token models."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field

from app.models.base import OptionalModel, SQLBaseModel


class AuthRefreshTokenBase(SQLBaseModel):
    """Represent shared rotating refresh-token fields."""

    auth_session_id: int = Field(
        foreign_key='auth_session.auth_session_id',
        sa_type=BigInteger,
    )
    token_digest: str = Field(max_length=64)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    consumed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    replaced_by_auth_refresh_token_id: int | None = Field(
        default=None,
        foreign_key='auth_refresh_token.auth_refresh_token_id',
        sa_type=BigInteger,
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class AuthRefreshToken(AuthRefreshTokenBase, table=True):
    """Represent one single-use refresh token in a device session family."""

    __tablename__ = 'auth_refresh_token'
    __table_args__ = (
        Index(
            'ix_auth_refresh_token_session_expires_at',
            'auth_session_id',
            'expires_at',
        ),
        UniqueConstraint(
            'token_digest',
            name='uq_auth_refresh_token_token_digest',
        ),
    )

    auth_refresh_token_id: int = Field(
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


class AuthRefreshTokenCreate(AuthRefreshTokenBase):
    """Represent data required to create a rotating refresh token."""


class AuthRefreshTokenUpdate(AuthRefreshTokenBase, OptionalModel):
    """Represent data used to update a rotating refresh token."""


class AuthRefreshTokenFilter(AuthRefreshTokenBase, OptionalModel):
    """Represent filters used to read rotating refresh tokens."""
