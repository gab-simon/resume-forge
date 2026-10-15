"""Authentication challenge models."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    SmallInteger,
    UniqueConstraint,
    text,
)
from sqlmodel import Field

from app.models.base import OptionalModel, SQLBaseModel


class AuthChallengeBase(SQLBaseModel):
    """Represent shared authentication-challenge fields."""

    # The challenge belongs to an email, not to a user: the account is created
    # only when the first code for that email is verified.
    email: str = Field(max_length=320)
    # Interface language used for the email and for an account created by the
    # verification.
    language: str = Field(max_length=8)
    public_id: str = Field(max_length=64)
    code_digest: str = Field(max_length=64)
    request_ip: str | None = Field(default=None, max_length=45)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    attempt_count: int = Field(default=0, sa_type=SmallInteger)
    consumed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class AuthChallenge(AuthChallengeBase, table=True):
    """Represent a one-time email authentication challenge."""

    __tablename__ = 'auth_challenge'
    __table_args__ = (
        CheckConstraint(
            'attempt_count >= 0',
            name='ck_auth_challenge_attempt_count_non_negative',
        ),
        Index(
            'ix_auth_challenge_email_created_at',
            'email',
            'created_at',
        ),
        Index(
            'ix_auth_challenge_request_ip_created_at',
            'request_ip',
            'created_at',
        ),
        UniqueConstraint('public_id', name='uq_auth_challenge_public_id'),
    )

    auth_challenge_id: int = Field(
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


class AuthChallengeCreate(AuthChallengeBase):
    """Represent data required to create an authentication challenge."""


class AuthChallengeUpdate(AuthChallengeBase, OptionalModel):
    """Represent data used to update an authentication challenge."""


class AuthChallengeFilter(AuthChallengeBase, OptionalModel):
    """Represent filters used to read authentication challenges."""
