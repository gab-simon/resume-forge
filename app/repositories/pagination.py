"""Pagination utilities for the application."""

from pydantic import BaseModel, Field


class PageRequest(BaseModel):
    """Represents a request for a paginated response."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class Page[T](BaseModel):
    """Represents a paginated response."""

    items: list[T]
    total: int
    offset: int
    limit: int
