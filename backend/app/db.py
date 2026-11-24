from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def lock_demo_writes(session):
    # Serialize read/modify/write operations before reading a draft or challenge.
    session.execute(text("BEGIN IMMEDIATE"))


def create_tables() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

