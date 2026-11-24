from fastapi import APIRouter, BackgroundTasks, Cookie, Header, Response

from ...config import settings
from ...db import SessionLocal, lock_demo_writes
from ...errors import APIError
from ...models import Case
from ...schemas import InteractionRequest
from ..conversation import process_interaction, reset_conversation
from ..events import append_event
from ..identity.service import normalize_phone
from ..resume import bind_whatsapp_resume
from .whatsapp_resume import ACTIONS, handle_chat_resume


router = APIRouter(tags=["whatsapp"])


@router.post("/channels/whatsapp/interactions")
def whatsapp_interaction(
    request: InteractionRequest,
    background: BackgroundTasks,
    response: Response,
    channel_key: str = Header(alias="X-Channel-Key"),
    web_session: str | None = Cookie(None),
) -> dict:
    if channel_key != settings.channel_key_whatsapp:
        raise APIError(403, "invalid_channel_key", "La clave del canal no es válida.")
    if request.identifier_type != "phone":
        raise APIError(422, "invalid_identifier", "WhatsApp requiere un número de teléfono.")
    if request.kind not in {"message", "action"}:
        raise APIError(422, "unsupported_interaction", "La interacción de WhatsApp no está disponible.")

    normalized = normalize_phone(request.identifier)
    normalized_request = request.model_copy(update={"identifier": normalized})
    if request.action in ACTIONS:
        result = handle_chat_resume(normalized_request, web_session, channel_key, background, response)
        if result is not None:
            return result
        normalized_request = normalized_request.model_copy(update={
            "action": "continue_case", "idempotency_key": f"resume:{request.idempotency_key}",
        })
    with SessionLocal() as session:
        try:
            with session.begin():
                lock_demo_writes(session)
                if request.action == "reset_conversation":
                    return reset_conversation(session, normalized, demo_mode=settings.demo_mode)
                if request.data.get("resume_challenge_id"):
                    bind_whatsapp_resume(session, request.data["resume_challenge_id"], web_session, normalized)
                return process_interaction(session, normalized_request)
        except APIError as exc:
            if exc.status_code == 403 and request.action != "reset_conversation":
                with session.begin():
                    case = session.get(Case, request.data.get("case_id")) if request.data.get("case_id") else None
                    append_event(
                        session,
                        event_type="acceso_denegado",
                        channel="whatsapp",
                        actor_id=normalized,
                        case_id=case.id if case else None,
                        person_id=case.requester_id if case else None,
                        payload={"reason": exc.error},
                    )
            raise

