"""Logging module."""

import inspect
import logging
import sys
from functools import cache

from loguru import logger

# Loggers that install their own handler and do not propagate to the root
# logger. Their handlers are replaced so the records reach Loguru only once.
_LOGGERS_WITH_OWN_HANDLER = (
    'uvicorn',
    'uvicorn.error',
    'uvicorn.access',
    'sqlalchemy.engine.Engine',
)


class InterceptHandler(logging.Handler):
    """Send records of the standard ``logging`` module to Loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        """Log the record through Loguru, keeping its level and call site."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Skip the frames of the logging module, so Loguru reports the module
        # and line that created the record.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def configure_logging(level: str) -> None:
    """Configure Loguru and redirect the standard ``logging`` module to it.

    Loguru writes to ``stderr`` the records at ``level`` or above. Libraries
    that log through ``logging``, such as Uvicorn and SQLAlchemy, go through
    the same output and format.

    Parameters
    ----------
    level : str
        Minimum level to write, such as ``INFO``.
    """
    logger.remove()
    logger.add(sys.stderr, level=level)

    handler = InterceptHandler()
    logging.basicConfig(handlers=[handler], level=logger.level(level).no, force=True)

    for name in _LOGGERS_WITH_OWN_HANDLER:
        library_logger = logging.getLogger(name)
        library_logger.handlers = [handler]
        library_logger.propagate = False


@cache
def get_logger():  # ruff: ignore[missing-return-type-undocumented-public-function]
    """Loguru logger.

    Returns
    -------
    Logger
        Loguru logger instance.
    """
    return logger
