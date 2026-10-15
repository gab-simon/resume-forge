"""Resume repository module.

The resume is persisted as YAML in ``RESUME_DATA_DIR``, not in PostgreSQL.
"""

import json
from pathlib import Path
from typing import Any

import yaml

from app.infra.context import IContext

RESUME_FILE_NAME = 'cv.yaml'
JSON_SCHEMA_FILE_NAME = 'cv.schema.json'


def resume_path(ctx: IContext) -> Path:
    """Return the path of the master resume file.

    Parameters
    ----------
    ctx : IContext
        The application context providing the settings.

    Returns
    -------
    Path
        Path of ``cv.yaml`` inside the data directory.
    """
    return ctx.settings.resume_data_dir / RESUME_FILE_NAME


def read_resume_data(ctx: IContext) -> dict[str, Any] | None:
    """Read the raw content of the master resume.

    The parser raises ``yaml.YAMLError`` when the file is not valid YAML.

    Parameters
    ----------
    ctx : IContext
        The application context providing the settings.

    Returns
    -------
    dict[str, Any] | None
        The parsed YAML mapping, or ``None`` when the file does not exist.

    Raises
    ------
    TypeError
        If the YAML document is not a mapping.
    """
    path = resume_path(ctx)
    if not path.is_file():
        return None

    with path.open(encoding='utf-8') as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise TypeError(f'{path.name} must contain a mapping at the top level.')
    return data


def write_json_schema(ctx: IContext, *, schema: dict[str, Any]) -> Path:
    """Write the JSON Schema of the resume next to ``cv.yaml``.

    Parameters
    ----------
    ctx : IContext
        The application context providing the settings.
    schema : dict[str, Any]
        JSON Schema to write.

    Returns
    -------
    Path
        Path of the written file.
    """
    path = ctx.settings.resume_data_dir / JSON_SCHEMA_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
    return path


__all__ = (
    'JSON_SCHEMA_FILE_NAME',
    'RESUME_FILE_NAME',
    'read_resume_data',
    'resume_path',
    'write_json_schema',
)
