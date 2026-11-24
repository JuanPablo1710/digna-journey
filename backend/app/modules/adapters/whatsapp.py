from fastapi import APIRouter, Header

from ...config import settings
from ...db import SessionLocal
from ...errors import APIError
from ...models import Case
from ...schemas import InteractionRequest
from ..conversation import process_interaction, reset_conversation
from ..events import append_event
from ..identity.service import normalize_phone


router = APIRouter(tags=["whatsapp"])


@router.post("/channels/whatsapp/interactions")
def whatsapp_interaction(
    request: InteractionRequest,
    channel_key: str = Header(alias="X-Channel-Key"),
) -> dict:
    if channel_key != settings.channel_key_whatsapp:
        raise APIError(403, "invalid_channel_key", "La clave del canal no es válida.")
    if request.identifier_type != "phone":
        raise APIError(422, "invalid_identifier", "WhatsApp requiere un número de teléfono.")
    if request.kind not in {"message", "action"}:
        raise APIError(422, "unsupported_interaction", "La interacción de WhatsApp no está disponible.")

    normalized = normalize_phone(request.identifier)
    normalized_request = request.model_copy(update={"identifier": normalized})
    with SessionLocal() as session:
        try:
            with session.begin():
                if request.action == "reset_conversation":
                    return reset_conversation(session, normalized, demo_mode=settings.demo_mode)
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

