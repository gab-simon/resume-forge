"""Lint script."""

# ruff:file-ignore[implicit-namespace-package]
# ruff:file-ignore[suspicious-subprocess-import]

import subprocess
import sys
from pathlib import Path
from shlex import split

from rich.console import Console

console = Console()

ROOT_FOLDER = Path(__file__).parent.parent
# The same targets the code-quality workflow checks.
LINT_TARGETS = ('app', 'scripts', 'tests', 'main.py')


def _shell(cmd: str) -> int:
    console.print(f'[yellow]%[/yellow] {cmd}')
    return subprocess.run(split(cmd), check=False, cwd=ROOT_FOLDER).returncode  # ruff:ignore[subprocess-without-shell-equals-true]


def ruff_lint() -> None:
    """Run the lint tools of the code-quality workflow and exit on failure.

    Execute ``ruff check``, ``ruff format --check`` and ``ty check`` against
    the application, scripts, tests and ``main.py``, printing the outcome to
    the console. Every tool runs even when a previous one fails. If any tool
    returns a non-zero exit code, print an error message and terminate the
    process with exit status 1.
    """
    cmd_tools = (
        'ruff check {targets}',
        'ruff format --check {targets}',
        'ty check {targets}',
    )
    targets = ' '.join(LINT_TARGETS)
    results = [_shell(cmd.format(targets=targets)) for cmd in cmd_tools]

    if not all(sc == 0 for sc in results):
        console.print('LINT ERROR')
        sys.exit(1)

    console.print('LINT SUCCESSFUL')
