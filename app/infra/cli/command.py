"""Command-line interface (CLI) application setup."""

from typer import Typer

from app import get_logger, get_settings
from app.cli_commands import health_command, openapi_command, resume_command
from app.infra.logging import configure_logging

logger = get_logger()


def create_app() -> Typer:
    """Create and configure a Typer CLI application instance.

    Returns
    -------
    Typer
        A configured Typer CLI application instance.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    app = Typer(
        name=settings.app_name,
        help=f'{settings.app_description} (version: {settings.app_version})',
        no_args_is_help=True,
        add_completion=False,
    )

    # Add commands
    app.add_typer(resume_command.app)
    app.add_typer(health_command.app)
    app.add_typer(openapi_command.app)

    return app


def main() -> None:
    """Run the CLI, the entry point of the ``cv`` script."""
    create_app()()
