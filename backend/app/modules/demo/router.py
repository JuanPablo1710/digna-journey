from datetime import timezone

from fastapi import APIRouter, Query
from sqlalchemy import select

from ...config import settings
from ...db import Base, SessionLocal, engine
from ...errors import APIError
from ...models import MailboxMessage
from ..identity.service import normalize_email
from .seed import seed_demo


router = APIRouter(prefix="/demo", tags=["demo"])


def _require_demo_mode() -> None:
    if not settings.demo_mode:
        raise APIError(403, "demo_mode_disabled", "El modo demo no está habilitado.")


@router.get("/mailbox")
def get_mailbox(email: str = Query()) -> dict:
    _require_demo_mode()
    normalized = normalize_email(email)
    with SessionLocal() as session:
        messages = session.scalars(
            select(MailboxMessage)
            .where(MailboxMessage.email == normalized)
            .order_by(MailboxMessage.created_at.desc())
        ).all()
        return {
            "messages": [
                {
                    "id": message.id,
                    "email": message.email,
                    "subject": message.subject,
                    "body": message.body,
                    "code": message.code,
                    "created_at": (
                        message.created_at.replace(tzinfo=timezone.utc)
                        if message.created_at.tzinfo is None
                        else message.created_at
                    ).isoformat().replace("+00:00", "Z"),
                }
                for message in messages
            ]
        }


@router.post("/reset")
def reset_demo() -> dict[str, str]:
    _require_demo_mode()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_demo(session)
    return {"status": "ok"}
