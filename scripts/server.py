"""Server script."""

# ruff:file-ignore[implicit-namespace-package]
# ruff:file-ignore[suspicious-subprocess-import]

import subprocess
from pathlib import Path
from shlex import split

from rich.console import Console

console = Console()

ROOT_FOLDER = Path(__file__).parent.parent
SERVER_FOLDER = ROOT_FOLDER / 'app'

API_APP = 'main:app'
API_PORT = 9000


def _shell(cmd: str) -> int:
    console.print(f'[yellow]%[/yellow] {cmd}')
    return subprocess.run(split(cmd), check=False).returncode  # ruff:ignore[subprocess-without-shell-equals-true]


def server() -> None:
    """Start the Uvicorn development server with hot-reloading enabled.

    Constructs and executes a Uvicorn command that runs the API application
    defined by ``API_APP``, listening on ``API_PORT``, with automatic reloading
    triggered by changes in ``SERVER_FOLDER``.
    """
    cmd = (
        f'uvicorn --reload --reload-dir {SERVER_FOLDER!s} --port {API_PORT!s} {API_APP}'
    )
    _shell(cmd)
