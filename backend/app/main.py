from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import SessionLocal, create_tables
from .modules.demo.seed import seed_demo


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

