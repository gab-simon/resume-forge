"""External process execution."""

import asyncio
import subprocess  # ruff: ignore[suspicious-subprocess-import]
from collections.abc import Sequence
from pathlib import Path


class ExternalToolNotFoundError(FileNotFoundError):
    """Raised when an external tool, such as pdflatex, is not installed."""

    def __init__(self, tool: str) -> None:
        self.tool = tool
        super().__init__(f'External tool not found: {tool}')


async def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a command in a worker thread and capture its output.

    The command never goes through a shell, so arguments need no quoting.

    Parameters
    ----------
    args : Sequence[str]
        Program and arguments.
    cwd : Path | None, optional
        Working directory of the process.
    timeout_seconds : float | None, optional
        Seconds to wait before the process is killed.

    Returns
    -------
    subprocess.CompletedProcess[bytes]
        The finished process. A non-zero exit status does not raise.

    Raises
    ------
    ExternalToolNotFoundError
        If the program is not installed.
    """
    try:
        # Without ``text``, ``subprocess.run`` returns bytes; ty cannot narrow
        # the overload through ``asyncio.to_thread``.
        result: subprocess.CompletedProcess[bytes] = await asyncio.to_thread(  # ty: ignore[invalid-assignment]
            subprocess.run,
            list(args),
            cwd=cwd,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExternalToolNotFoundError(args[0]) from exc
    return result


__all__ = ('ExternalToolNotFoundError', 'run_command')
