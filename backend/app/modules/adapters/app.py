from fastapi import APIRouter, Depends, Header
from pydantic import ValidationError
from sqlalchemy import select

from ...config import settings
from ...db import SessionLocal, lock_demo_writes
from ...errors import APIError
from ...models import Case, Event, Person, Verification
from ...schemas import CaseActionData, InteractionRequest
from ..auth import _token_claims, bearer
from ..cases import change_channel, empty_steps, missing_steps
from ..events.safe import safe_event, utc_iso
from ..identity.service import aware, normalize_email, utc_now


router = APIRouter(tags=["app"])


def _authorize(session, credentials, key):
    claims = _token_claims(credentials)
    if claims.get("role") != "paciente" or claims.get("channel") != "app":
        raise APIError(403, "app_session_required", "Inicia sesión con un código en la app.")
    if key != settings.channel_key_app:
        raise APIError(403, "invalid_channel_key", "La clave del canal no es válida.")
    verification = session.get(Verification, claims.get("verification_id")) if claims.get("verification_id") else None
    if (not verification or verification.person_id != claims["sub"] or verification.channel != "app"
            or verification.method != "email_otp" or verification.status != "succeeded"
            or not verification.valid_until or aware(verification.valid_until) <= utc_now()):
        raise APIError(401, "session_expired", "La verificación de la app venció. Solicita otro código.")
    return verification


def _case_summary(session, case):
    patient = session.get(Person, case.patient_id) if case.relationship != "self" else None
    return {
        "id": case.id, "study_id": case.study_id, "clinic_id": case.clinic_id,
        "status": case.status, "version": case.version, "relationship": case.relationship,
        "patient_name": patient.full_name if patient else None,
        "steps": {**empty_steps(), **case.steps},
        "slot_datetime": utc_iso(case.slot_datetime) if case.slot_datetime else None,
        "last_channel": case.last_channel,
    }


@router.get("/me/cases")
def my_cases(credentials=Depends(bearer), key: str | None = Header(default=None, alias="X-Channel-Key")):
    with SessionLocal() as session:
        verification = _authorize(session, credentials, key)
        cases = session.scalars(select(Case).where(Case.requester_id == verification.person_id)
                                .order_by(Case.updated_at.desc(), Case.id))
        return {"cases": [_case_summary(session, case) for case in cases]}


@router.post("/channels/app/interactions")
def app_interaction(request: InteractionRequest, credentials=Depends(bearer),
                    key: str | None = Header(default=None, alias="X-Channel-Key")):
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        verification = _authorize(session, credentials, key)
        if (request.kind != "action" or request.action != "continue_case" or request.identifier_type != "account"
                or normalize_email(request.identifier) != verification.identifier):
            raise APIError(422, "invalid_app_interaction", "Usa la cuenta verificada y selecciona un trámite.")
        try:
            data = CaseActionData.model_validate(request.data)
        except ValidationError as exc:
            raise APIError(422, "invalid_case_action", "Indica el trámite y su versión.") from exc
        case = session.scalar(select(Case).where(
            Case.id == data.case_id, Case.requester_id == verification.person_id,
        ))
        if case is None:
            raise APIError(404, "case_not_found", "No encontramos el trámite en esta cuenta.")
        event_key = f"app:{verification.id}:{request.idempotency_key}"
        prior = session.scalar(select(Event).where(Event.idempotency_key == event_key))
        if prior and prior.case_id != case.id:
            raise APIError(409, "idempotency_conflict", "La clave ya se usó para otro trámite.")
        types = [prior.type] if prior else []
        if not prior and case.last_channel != "app":
            if case.version != data.expected_version:
                raise APIError(409, "version_conflict", "El trámite se actualizó. Vuelve a abrirlo.",
                               {"case": _case_summary(session, case)})
            events = change_channel(session, case, channel="app", actor_id=verification.person_id)
            events[0].idempotency_key = event_key
            case.version += 1
            types = [event.type for event in events]
        session.flush()
        timeline = session.scalars(select(Event).where(
            Event.case_id == case.id,
            Event.type.notin_(("nota_agregada", "contexto_consultado", "acceso_denegado")),
        ).order_by(Event.seq))
        return {
            "trust_level": 2, "case": _case_summary(session, case),
            "missing_steps": [] if case.status == "cancelado" else missing_steps(case.steps),
            "messages": [], "events": types, "timeline": [safe_event(event) for event in timeline],
        }
