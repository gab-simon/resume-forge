"""Router initialization for the application API."""

from fastapi import APIRouter, Depends, FastAPI

from app.controllers import (
    auth_controller,
    health_controller,
    me_controller,
    resume_controller,
)
from app.infra.context import get_authenticated_context

API_PREFIX = '/api/v1'

# Probes keep their own paths, outside the API prefix, so orchestrators and
# load balancers can call them without knowing the API version.
_PROBE_ROUTERS: tuple[APIRouter, ...] = (health_controller.router,)

# Login routes. Every route here is served under ``API_PREFIX``. Routes of
# this router that need a user declare ``UserContext`` themselves.
_PUBLIC_API_ROUTERS: tuple[APIRouter, ...] = (auth_controller.router,)

# Routes that require a Bearer token. The router-level dependency rejects a
# missing or invalid token before the route runs.
_AUTHENTICATED_API_ROUTERS: tuple[APIRouter, ...] = (
    me_controller.router,
    resume_controller.router,
)


def init_app(app: FastAPI) -> None:
    """Register probe and API routers."""
    for router in _PROBE_ROUTERS:
        app.include_router(router)

    for router in _PUBLIC_API_ROUTERS:
        app.include_router(router, prefix=API_PREFIX)

    # The same scope as ``UserContext``: FastAPI caches a dependency per scope,
    # so a different scope here would authenticate twice and open two
    # sessions per request.
    for router in _AUTHENTICATED_API_ROUTERS:
        app.include_router(
            router,
            prefix=API_PREFIX,
            dependencies=[Depends(get_authenticated_context, scope='function')],
        )


__all__ = ('API_PREFIX', 'init_app')
