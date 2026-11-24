from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .catalog import router as catalog_router
from .config import settings
from .db import SessionLocal, create_tables
from .errors import APIError
from .modules.adapters.web import router as web_router
from .modules.adapters.whatsapp import router as whatsapp_router
from .modules.demo.router import router as demo_router
from .modules.demo.seed import seed_demo
from .modules.identity import router as identity_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    with SessionLocal() as session:
        seed_demo(session)
    yield


app = FastAPI(title="Motor de contexto omnicanal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(catalog_router)
app.include_router(web_router)
app.include_router(whatsapp_router)
app.include_router(identity_router)
app.include_router(demo_router)


@app.exception_handler(APIError)
async def api_error_handler(_: Request, exc: APIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "message": exc.message, **exc.extra},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

