"""Base model for all SQL models."""

from contextlib import suppress
from typing import Any, get_args

from pydantic import BaseModel, PydanticUndefinedAnnotation
from sqlalchemy import MetaData
from sqlmodel import SQLModel


class SQLBaseModel(SQLModel):
    """Base model for all SQL models."""

    metadata = MetaData(schema='resume_forge')


class OptionalModel(BaseModel):
    """OptionalModel[T] makes a subclass of T with all fields optional."""

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:  # ruff: ignore[any-type]
        """Initialize the subclass, making all fields optional."""
        super().__pydantic_init_subclass__(**kwargs)

        for field in cls.model_fields.values():
            if type(None) not in get_args(field.annotation):
                field.annotation = field.annotation | None
            field.default = None

        with suppress(PydanticUndefinedAnnotation):
            cls.model_rebuild(force=True)
