"""API module."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from app.infra.api import router
from app.infra.database.postgres import role_bypasses_row_level_security
from app.infra.logging import configure_logging
from app.infra.settings import get_settings

_OPENAPI_TAGS = [
    {
        'name': 'HEALTH',
        'description': 'Probes de disponibilidade da aplicação.',
    },
    {
        'name': 'AUTHENTICATION',
        'description': 'Login por código enviado ao e-mail e tokens Bearer.',
    },
    {
        'name': 'ME',
        'description': 'Usuário autenticado e suas preferências.',
    },
    {
        'name': 'RESUME',
        'description': 'Currículo de data/cv.yaml, modelos, PDF e checagem ATS.',
    },
]


def _generate_unique_id(route: APIRoute) -> str:
    """Build the OpenAPI ``operationId`` as ``<TAG>-<function name>``.

    API clients generated from the schema name their functions after the
    operation ID. ``RESUME-read_resume`` becomes ``resumeReadResume``, while
    the FastAPI default would produce ``readResumeApiV1ResumeGet``. Spaces in
    a tag become underscores, so ``JOB POSTS`` yields ``JOB_POSTS-...``.

    Parameters
    ----------
    route : APIRoute
        The route being registered.

    Returns
    -------
    str
        The operation ID. Routes without tags use only the function name.
    """
    if not route.tags:
        return route.name
    return f'{str(route.tags[0]).replace(" ", "_")}-{route.name}'


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    logger.info('Starting Resume Forge up...')
    if get_settings().uses_dev_login_code:
        logger.warning(
            'No SMTP_HOST in development: every login code is 123456 and '
            'emails go to this log. Set APP_ENV=production on a server.'
        )
    await _warn_when_user_isolation_is_bypassed()
    try:
        yield
    finally:
        logger.info('Shutting down...')


async def _warn_when_user_isolation_is_bypassed() -> None:
    """Log a warning when the database role ignores row-level security."""
    if not get_settings().db_url:
        return
    try:
        bypassed = await role_bypasses_row_level_security()
    except (SQLAlchemyError, OSError) as exc:
        logger.warning(
            'Could not check the database role for row-level security: {error}',
            error=type(exc).__name__,
        )
        return
    if bypassed:
        logger.warning(
            'The database role in DB_URL is a superuser, has BYPASSRLS or owns '
            'the tables. PostgreSQL does not isolate users for this role. Use '
            'a restricted application role.'
        )


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns
    -------
    FastAPI
        The configured FastAPI application instance.
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        openapi_tags=_OPENAPI_TAGS,
        with_google_fonts=True,
        lifespan=lifespan,
        redoc_url=None,
        docs_url='/docs' if settings.openapi_enabled else None,
        openapi_url='/openapi.json' if settings.openapi_enabled else None,
        generate_unique_id_function=_generate_unique_id,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=['*'],
            allow_headers=['*'],
        )

    router.init_app(app)

    if settings.openapi_enabled:
        app.get('/', include_in_schema=False)(
            lambda: RedirectResponse(url='/docs', status_code=status.HTTP_302_FOUND)
        )

    return app


__all__ = ('create_app',)
