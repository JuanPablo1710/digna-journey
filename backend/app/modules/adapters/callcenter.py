from secrets import compare_digest, token_urlsafe

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select, update

from ...config import settings
from ...db import SessionLocal, lock_demo_writes
from ...errors import APIError
from ...models import Event, Person, User, Verification
from ...schemas import InteractionRequest
from ...security import mask_phone
from ..agent.calls import active_call, call_event, owned_call
from ..auth import require_agent
from ..events import append_event
from ..identity.service import normalize_phone, utc_now


router = APIRouter(tags=["callcenter"])


@router.post("/channels/callcenter/interactions")
def call_interaction(request: InteractionRequest, agent: User = Depends(require_agent),
                     channel_key: str = Header(alias="X-Channel-Key")):
    if not compare_digest(channel_key, settings.channel_key_callcenter):
        raise APIError(403, "invalid_channel_key", "La clave del canal no es válida.")
    if request.kind not in {"call_started", "call_ended"}:
        raise APIError(422, "invalid_call_action", "Selecciona iniciar o terminar llamada.")
    opening = request.kind == "call_started"
    event_type = "llamada_iniciada" if opening else "llamada_finalizada"
    key = f"callcenter:{agent.id}:{request.idempotency_key}"
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        event = session.scalar(select(Event).where(Event.idempotency_key == key))
        if event is not None:
            if event.type != event_type:
                raise APIError(409, "idempotency_conflict", "La clave ya se usó en otra acción.")
            call_id = event.payload["call_id"]
            level = event.payload.get("trust_level", 0)
        else:
            if opening:
                if active_call(session, agent.id):
                    raise APIError(409, "call_already_open", "Termina la llamada actual antes de iniciar otra.")
                now = utc_now()
                session.execute(update(Verification).where(
                    Verification.channel == "callcenter", Verification.method == "agent_assisted",
                    Verification.identifier == agent.id, Verification.valid_until > now,
                ).values(valid_until=now))
                phone = normalize_phone(request.identifier) if request.identifier_type == "phone" else None
                recognized = phone is not None and session.scalar(
                    select(Person.id).where(Person.phone == phone).limit(1)
                ) is not None
                level = int(recognized)
                call_id = token_urlsafe(24)
                payload = {"call_id": call_id, "trust_level": level, "masked_phone": mask_phone(phone)}
                person_id = None
            else:
                call_id = request.data.get("call_id")
                if not isinstance(call_id, str) or not call_id:
                    raise APIError(422, "call_required", "Indica la llamada que quieres terminar.")
                owned_call(session, call_id, agent.id)
                binding = call_event(session, call_id, "identidad_vinculada")
                person_id = binding.person_id if binding else None
                now = utc_now()
                session.execute(update(Verification).where(
                    Verification.channel == "callcenter", Verification.method == "agent_assisted",
                    Verification.identifier == call_id, Verification.valid_until > now,
                ).values(valid_until=now))
                level = 0
                payload = {"call_id": call_id}
            append_event(session, event_type=event_type, channel="callcenter", actor_id=agent.id,
                         actor_role="asesor", person_id=person_id, payload=payload, idempotency_key=key)
    return {"call_id": call_id, "trust_level": level, "case": None, "missing_steps": [],
            "messages": [], "events": [event_type]}
