import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR.parent / ".env")


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    jwt_secret: str = os.getenv("JWT_SECRET", "change-me-in-local-development")
    channel_key_web: str = os.getenv("CHANNEL_KEY_WEB", "demo-web-key")
    channel_key_whatsapp: str = os.getenv("CHANNEL_KEY_WHATSAPP", "demo-whatsapp-key")
    channel_key_callcenter: str = os.getenv("CHANNEL_KEY_CALLCENTER", "demo-callcenter-key")
    channel_key_app: str = os.getenv("CHANNEL_KEY_APP", "demo-app-key")
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'data' / 'app.db').as_posix()}"
    )
    abandon_minutes: int = int(os.getenv("ABANDON_MINUTES", "15"))
    demo_mode: bool = _as_bool(os.getenv("DEMO_MODE", "true"))
    ai_enabled: bool = _as_bool(os.getenv("AI_ENABLED", "false"))
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")


settings = Settings()

