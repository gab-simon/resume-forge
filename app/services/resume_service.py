"""Resume business service functions."""

import asyncio
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.infra.context import IContext
from app.models.resume import Resume
from app.repositories import resume_repository


class ResumeNotFoundError(LookupError):
    """Raised when the master resume file does not exist."""

    def __init__(self, path: Path) -> None:
        super().__init__(f'Resume file not found: {path}')


class ResumeInvalidError(ValueError):
    """Raised when the master resume file is not a valid resume."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__('Invalid resume file:\n' + '\n'.join(errors))


async def read_resume(ctx: IContext) -> Resume:
    """Read and validate the master resume.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.

    Returns
    -------
    Resume
        The validated resume.

    Raises
    ------
    ResumeNotFoundError
        If ``cv.yaml`` does not exist.
    ResumeInvalidError
        If the file is not YAML or does not match the resume schema.
    """
    try:
        data = await asyncio.to_thread(resume_repository.read_resume_data, ctx)
    except (yaml.YAMLError, TypeError) as exc:
        raise ResumeInvalidError([str(exc)]) from exc

    if data is None:
        raise ResumeNotFoundError(resume_repository.resume_path(ctx))

    try:
        return Resume.model_validate(data)
    except ValidationError as exc:
        raise ResumeInvalidError(
            [
                f'{".".join(str(part) for part in error["loc"])}: {error["msg"]}'
                for error in exc.errors()
            ]
        ) from exc


async def write_json_schema(ctx: IContext) -> Path:
    """Write the JSON Schema that editors use to validate ``cv.yaml``.

    Parameters
    ----------
    ctx : IContext
        Application context for the operation.

    Returns
    -------
    Path
        Path of the written schema.
    """
    schema = Resume.model_json_schema()
    schema['title'] = 'Resume Forge CV'
    return await asyncio.to_thread(
        resume_repository.write_json_schema, ctx, schema=schema
    )


__all__ = (
    'ResumeInvalidError',
    'ResumeNotFoundError',
    'read_resume',
    'write_json_schema',
)
