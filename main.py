"""Main entry point for the application."""

from dotenv import load_dotenv

load_dotenv()

if __name__ == '__main__':
    from app.infra.cli.command import create_app

    app = create_app()
    app()

else:
    from app.infra.api.api import create_app

    app = create_app()

__all__ = ('app',)
