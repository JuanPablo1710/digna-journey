import os

import pytest
from fastapi.testclient import TestClient


os.environ["DATABASE_URL"] = "sqlite:///./data/test.db"

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)

