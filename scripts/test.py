"""Test script."""

# ruff:file-ignore[implicit-namespace-package]
# ruff:file-ignore[suspicious-subprocess-import]

import subprocess
import sys
from pathlib import Path
from shlex import split

from rich.console import Console

console = Console()

ROOT_FOLDER = Path(__file__).parent.parent
SERVER_FOLDER = ROOT_FOLDER / 'app'
TEST_FOLDER = ROOT_FOLDER / 'tests'


def _shell(cmd: str) -> int:
    console.print(f'[yellow]%[/yellow] {cmd}')
    return subprocess.run(split(cmd), check=False).returncode  # ruff:ignore[subprocess-without-shell-equals-true]


def unit_test() -> None:
    """Run the unit test suite with coverage reporting enabled.

    Constructs and executes the pytest command with coverage enabled,
    including term-missing and HTML coverage reports, targeting the
    unit tests located in ``TEST_FOLDER``. The process exits with the pytest
    exit status, so a failing test or low coverage fails the caller.
    """
    cmd = [
        f'pytest -vv -ra -q -n auto --cov={SERVER_FOLDER}/services',
        '--cov-report=term-missing --cov-report html',
        f'--cov-fail-under=85 {TEST_FOLDER}/unit/services',
    ]

    cmd = ' '.join(cmd)
    sys.exit(_shell(cmd))
