"""User models."""

from datetime import datetime
from typing import Literal

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, text
from sqlmodel import Field

from app.models.base import OptionalModel, SQLBaseModel

type UiLanguage = Literal['pt-BR', 'en-US']
UI_LANGUAGES: tuple[UiLanguage, ...] = ('pt-BR', 'en-US')
DEFAULT_TEMPLATE = 'classic'


class UserBase(SQLBaseModel):
    """Represent shared user fields."""

    # Stored in lowercase. The unique index is on this column.
    email: str = Field(max_length=320)
    name: str | None = Field(default=None, max_length=255)
    # Language of the interface, which is not the language of a resume.
    ui_language: str = Field(default='pt-BR', max_length=8)
    # Language and template a new resume export uses by default.
    resume_language: str = Field(default='pt', max_length=2)
    default_template: str = Field(default=DEFAULT_TEMPLATE, max_length=64)


class User(UserBase, table=True):
    """Represent an account of the platform."""

    __tablename__ = 'app_user'
    __table_args__ = (
        CheckConstraint(
            "ui_language IN ('pt-BR', 'en-US')",
            name='ck_app_user_ui_language',
        ),
        CheckConstraint(
            "resume_language IN ('pt', 'en')",
            name='ck_app_user_resume_language',
        ),
        CheckConstraint('email = lower(email)', name='ck_app_user_email_lowercase'),
        Index(
            'uq_app_user_email',
            'email',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
    )

    user_id: int = Field(
        default=None,
        nullable=False,
        primary_key=True,
        sa_type=BigInteger,
    )

    # Timestamps
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
        sa_column=Column(DateTime(timezone=True), nullable=True, server_default=None),
        default=None,
    )


class UserCreate(UserBase):
    """Represent the data required to create a user."""


class UserUpdate(UserBase, OptionalModel):
    """Represent the data required to update a user."""


class UserFilter(UserBase, OptionalModel):
    """Represent the data required to filter users."""


__all__ = (
    'DEFAULT_TEMPLATE',
    'UI_LANGUAGES',
    'UiLanguage',
    'User',
    'UserCreate',
    'UserFilter',
    'UserUpdate',
)
