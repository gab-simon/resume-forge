"""Health commands."""

import asyncio

import typer

from app.infra.context import get_context
from app.infra.database.postgres import ping_database

# ruff:file-ignore[print]
#
app = typer.Typer(
    name='health',
    help='Health commands',
    no_args_is_help=True,
)


@app.command(name='readiness', help='Check readiness by pinging the database')
def health_readiness() -> None:
    """Check application readiness by pinging the database."""

    async def _() -> None:
        async with get_context():
            await ping_database()

        print('OK')

    asyncio.run(_())
