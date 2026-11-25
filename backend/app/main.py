from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .catalog import router as catalog_router
from .config import settings
from .db import SessionLocal, create_tables
from .errors import APIError
from .modules.adapters.web import router as web_router
from .modules.adapters.app import VALID_UNTIL_HEADER, router as app_router
from .modules.adapters.callcenter import router as callcenter_router
from .modules.adapters.whatsapp import router as whatsapp_router
from .modules.admin import router as admin_router
from .modules.agent import router as agent_router
from .modules.agent import case_router as agent_case_router
from .modules.auth import router as auth_router
from .modules.demo.router import router as demo_router
from .modules.demo.router import device_router
from .modules.demo.seed import seed_demo
from .modules.identity import router as identity_router
from .modules.resume import router as resume_router
from .modules.events.stream import router as stream_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    with SessionLocal.begin() as session:
        seed_demo(session)
    yield


async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "message": exc.message, **exc.extra},
    )


def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app(*, demo_mode: bool | None = None) -> FastAPI:
    application = FastAPI(title="Motor de contexto omnicanal", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[VALID_UNTIL_HEADER],
    )
    for router in (catalog_router, web_router, whatsapp_router, app_router, identity_router, auth_router, admin_router,
                   agent_router, agent_case_router, callcenter_router, resume_router, demo_router, stream_router):
        application.include_router(router)
    demo_enabled = settings.demo_mode if demo_mode is None else demo_mode
    if demo_enabled:
        application.include_router(device_router)
    application.add_exception_handler(APIError, api_error_handler)
    application.add_api_route("/health", health, methods=["GET"])
    return application


app = create_app()

