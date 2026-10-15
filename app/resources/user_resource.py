"""User HTTP resources."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# The limits match the columns of ``app/models/user.py``. Without them a longer
# value would pass this layer and fail in the model with status 500.


class UserResource(BaseModel):
    """HTTP representation of the authenticated user."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str
    name: str | None
    ui_language: Literal['pt-BR', 'en-US']
    resume_language: Literal['pt', 'en']
    default_template: str
    created_at: AwareDatetime


class UserUpdateResource(BaseModel):
    """HTTP payload used to update the name and preferences of the user."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    ui_language: Literal['pt-BR', 'en-US'] | None = None
    resume_language: Literal['pt', 'en'] | None = None
    default_template: str | None = Field(default=None, max_length=64)


__all__ = ('UserResource', 'UserUpdateResource')
