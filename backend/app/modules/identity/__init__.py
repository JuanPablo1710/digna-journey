
from fastapi import APIRouter, Cookie, Header, Response
from sqlalchemy import select

from ...config import settings
from ...db import SessionLocal, lock_demo_writes
from ...errors import APIError
from ...schemas import VerificationConfirmData, VerificationRequestData
from ...models import Event
from .service import _identity, confirm_verification, request_verification


router = APIRouter(prefix="/identity", tags=["identity"])
SESSION_COOKIE = "web_session"


def _require_app_key(channel, key):
    if channel == "app" and key != settings.channel_key_app:
        raise APIError(403, "invalid_channel_key", "La clave del canal no es válida.")


def _reject_invalidated_session(session, channel, identifier):
    if channel == "web" and identifier:
        identity = _identity(session, channel, identifier)
        known = not (identity.session_state or {}).get("invalidated") if identity is not None else (
            session.scalar(select(Event.seq).where(
                Event.channel == "web", Event.actor_id == identifier, Event.type == "contacto_creado",
                Event.case_id.is_(None),
            ).limit(1)) is not None
        )
        if not known:
            raise APIError(403, "session_expired", "La sesión web ya no está vigente.")


def _raise_service_error(result: dict) -> None:
    error = result.get("_error")
    if error:
        status_code, code, message, extra = error
        raise APIError(status_code, code, message, extra)


@router.post("/verify/request")
def request_identity_verification(
    data: VerificationRequestData,
    web_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    channel_key: str | None = Header(default=None, alias="X-Channel-Key"),
):
    _require_app_key(data.channel, channel_key)
    if data.channel == "web" and not web_session:
        raise APIError(403, "web_session_required", "Inicia una sesión web antes de verificar el correo.")
    with SessionLocal() as session:
        with session.begin():
            lock_demo_writes(session)
            _reject_invalidated_session(session, data.channel, web_session)
            result = request_verification(
                session,
                channel=data.channel,
                identifier=data.identifier,
                method=data.method,
                birth_date=data.birth_date,
            )
        _raise_service_error(result)
        return result


@router.post("/verify/confirm")
def confirm_identity_verification(
    data: VerificationConfirmData,
    response: Response,
    web_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    channel_key: str | None = Header(default=None, alias="X-Channel-Key"),
):
    _require_app_key(data.channel, channel_key)
    with SessionLocal() as session:
        with session.begin():
            if data.channel == "app":
                lock_demo_writes(session)
            _reject_invalidated_session(session, data.channel, web_session)
            result = confirm_verification(
                session,
                channel=data.channel,
                identifier=data.identifier,
                code=data.code,
                web_session=web_session,
            )
        _raise_service_error(result)
    new_session = result.pop("_new_session", None)
    if new_session:
        response.set_cookie(
            SESSION_COOKIE,
            new_session,
            max_age=1800,
            httponly=True,
            samesite="lax",
        )
        result["session_identifier"] = new_session
    return result
