"""OpenAPI commands."""

import json
from pathlib import Path
from typing import Annotated

import typer

# ruff:file-ignore[print]

app = typer.Typer(
    name='openapi',
    help='OpenAPI commands',
    no_args_is_help=True,
)


@app.command(name='export', help='Write the OpenAPI schema without starting the API.')
def openapi_export(
    output: Annotated[
        Path | None,
        typer.Option('--output', '-o', help='File to write. Prints when omitted.'),
    ] = None,
) -> None:
    """Write the OpenAPI schema that the front end generates its client from."""
    from app.infra.api.api import create_app

    schema = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + '\n'
    if output is None:
        print(schema, end='')
        return
    output.write_text(schema, encoding='utf-8')
    print(f'Wrote {output}')
