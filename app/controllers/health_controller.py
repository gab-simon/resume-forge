"""Health controller."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.exc import SQLAlchemyError

from app.infra.database.postgres import ping_database

router = APIRouter(
    prefix='/health',
    tags=['HEALTH'],
)


@router.get(
    '/v1/liveness',
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
)
async def health_liveness() -> str:
    """Return the liveness status.

    The probe touches no dependency. It fails only when the process cannot
    answer HTTP requests, which is the case a restart fixes.

    Returns
    -------
    str
        The liveness status as a plain-text response.
    """
    return 'OK'


@router.get(
    '/v1/readiness',
    response_class=PlainTextResponse,
    status_code=status.HTTP_200_OK,
)
async def health_readiness() -> str:
    """Return the readiness status after pinging the database.

    Returns
    -------
    str
        The readiness status as a plain-text response.

    Raises
    ------
    HTTPException
        With status 503 when the database is not configured or does not
        answer.
    """
    try:
        await ping_database()
    except (SQLAlchemyError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Database unavailable.',
        ) from exc

    return 'OK'


__all__ = ('router',)
