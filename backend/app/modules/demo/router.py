from datetime import timezone

from fastapi import APIRouter, Cookie, Query, Response
from sqlalchemy import select

from ...config import settings
from ...db import Base, SessionLocal, engine
from ...errors import APIError
from ...models import ChannelIdentity, MailboxMessage
from ..identity.service import new_id, normalize_email
from .seed import seed_demo


router = APIRouter(prefix="/demo", tags=["demo"])
device_router = APIRouter(prefix="/demo", tags=["demo"])


@device_router.get("/new-device", status_code=204)
def check_new_device():
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@device_router.post("/new-device", status_code=204)
def simulate_new_device(web_session: str | None = Cookie(default=None)):
    if web_session:
        with SessionLocal.begin() as session:
            identity = session.scalar(select(ChannelIdentity).where(
                ChannelIdentity.channel == "web",
                ChannelIdentity.identifier == web_session,
            ))
            if identity is None:
                identity = ChannelIdentity(
                    id=new_id("CI"), channel="web", identifier=web_session,
                    identifier_type="session",
                )
                session.add(identity)
            identity.session_state = {"invalidated": True}
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie("web_session", httponly=True, samesite="lax")
    return response


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
