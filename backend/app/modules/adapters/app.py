from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import or_, select

from ...config import settings
from ...db import SessionLocal, lock_demo_writes
from ...errors import APIError
from ...models import Case, Event, Person, Verification
from ..auth import _token_claims, bearer
from ..cases import change_channel, check_version, create_case, empty_steps, missing_steps, update_case
from ..events.safe import safe_event, utc_iso
from ..identity.service import VERIFICATION_TTL, aware, ensure_complete_person, normalize_email, resolve_dependent_patient, utc_now
from .app_contract import AppInteraction, AppPreregister


router = APIRouter(tags=["app"])
VALID_UNTIL_HEADER = "X-App-Valid-Until"
SESSION_RESPONSE = {
    200: {"headers": {VALID_UNTIL_HEADER: {
        "description": "Vigencia renovada de la sesión App, en UTC.",
        "schema": {"type": "string", "format": "date-time"},
    }}},
}
ACTION_EVENTS = {
    "continue_case": "canal_cambiado",
    "preregister": "tramite_creado",
    "select_study": "estudio_seleccionado",
    "select_clinic": "clinica_seleccionada",
    "select_slot": "horario_propuesto",
    "confirm_case": "cita_confirmada",
}


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
    return verification, datetime.fromtimestamp(claims["exp"], timezone.utc)


def _renew_session(verification, token_deadline, response: Response) -> None:
    verification.valid_until = min(utc_now() + VERIFICATION_TTL, token_deadline)
    response.headers[VALID_UNTIL_HEADER] = utc_iso(verification.valid_until)


def _belongs_to(person_id):
    return or_(Case.requester_id == person_id, Case.patient_id == person_id)


def _owned_case(session, person_id, case_id):
    case = session.scalar(select(Case).where(Case.id == case_id, _belongs_to(person_id)))
    if case is None:
        raise APIError(404, "case_not_found", "No encontramos el trámite en esta cuenta.")
    return case


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


@router.get("/me/cases", responses=SESSION_RESPONSE)
def my_cases(response: Response, credentials=Depends(bearer),
             key: str | None = Header(default=None, alias="X-Channel-Key")):
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        verification, deadline = _authorize(session, credentials, key)
        cases = session.scalars(select(Case).where(_belongs_to(verification.person_id))
                                .order_by(Case.updated_at.desc(), Case.id))
        result = {"cases": [_case_summary(session, case) for case in cases]}
        _renew_session(verification, deadline, response)
        return result


def _preregister(session, person_id, data, event_key):
    requester = session.get(Person, person_id)
    ensure_complete_person(requester)
    if not requester.email or not requester.phone:
        raise APIError(422, "incomplete_person", "Tu cuenta necesita correo y teléfono para iniciar un trámite.")
    patient = requester
    if data.relationship != "self":
        if data.patient is None:
            raise APIError(422, "missing_patient", "Captura los datos de la persona que recibirá el estudio.")
        patient = resolve_dependent_patient(session, requester, **data.patient.model_dump())
    elif data.patient is not None:
        raise APIError(422, "unexpected_patient", "Omite los datos de paciente cuando el estudio es para ti.")
    case, events = create_case(
        session, requester=requester, patient=patient, relationship=data.relationship,
        study_id=data.study_id, channel="app", actor_id=person_id,
    )
    events[0].idempotency_key = event_key
    return case, events


def _advance(session, case, person_id, request, event_key):
    data = request.data
    try:
        if request.action == "continue_case":
            check_version(session, case, data.expected_version)
            events = change_channel(session, case, channel="app", actor_id=person_id)
            if events:
                events[0].idempotency_key = event_key
                case.version += 1
            return events
        if case.status == "cita_confirmada":
            check_version(session, case, data.expected_version)
            raise APIError(422, "case_confirmed", "La cita ya está confirmada.")
        events, _ = update_case(
            session, case, action=request.action, expected_version=data.expected_version,
            channel="app", actor_id=person_id, idempotency_key=event_key,
            study_id=data.study_id, clinic_id=data.clinic_id, slot_id=data.slot_id,
            use_saved_patient_data=True,
        )
        return events
    except APIError as exc:
        if exc.error != "version_conflict":
            raise
        raise APIError(409, "version_conflict", "El trámite se actualizó. Vuelve a abrirlo.",
                       {"case": _case_summary(session, case)}) from exc


@router.post(
    "/channels/app/interactions", responses={
        **SESSION_RESPONSE, 401: {"description": "Sesión inválida o vencida."},
        404: {"description": "Trámite fuera de la cuenta o recurso no disponible."},
        409: {"description": "Conflicto de versión o de idempotencia."},
    },
)
def app_interaction(request: AppInteraction, response: Response, credentials=Depends(bearer),
                    key: str | None = Header(default=None, alias="X-Channel-Key")):
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        verification, deadline = _authorize(session, credentials, key)
        person_id = verification.person_id
        if normalize_email(request.identifier) != verification.identifier:
            raise APIError(422, "invalid_app_interaction", "Usa la cuenta verificada y selecciona un trámite.")
        creating = isinstance(request, AppPreregister)
        case = None if creating else _owned_case(session, person_id, request.data.case_id)
        event_key = f"app:{verification.id}:{request.idempotency_key}"
        prior = session.scalar(select(Event).where(Event.idempotency_key == event_key))
        if prior:
            if prior.type != ACTION_EVENTS[request.action] or (case and prior.case_id != case.id):
                raise APIError(409, "idempotency_conflict", "La clave ya se usó para otra interacción.")
            if creating:
                case = _owned_case(session, person_id, prior.case_id)
            event_types = prior.payload.get("_app_event_types", [prior.type])
        elif creating:
            case, events = _preregister(session, person_id, request.data, event_key)
            event_types = [event.type for event in events]
            events[0].payload = {**events[0].payload, "_app_event_types": event_types}
        else:
            events = _advance(session, case, person_id, request, event_key)
            event_types = [event.type for event in events]
            if events:
                events[-1].payload = {**events[-1].payload, "_app_event_types": event_types}
        _renew_session(verification, deadline, response)
        session.flush()
        timeline = session.scalars(select(Event).where(
            Event.case_id == case.id,
            Event.type.notin_(("nota_agregada", "contexto_consultado", "acceso_denegado")),
        ).order_by(Event.seq))
        return {
            "trust_level": 2, "case": _case_summary(session, case),
            "missing_steps": [] if case.status == "cancelado" else missing_steps(case.steps),
            "messages": [], "events": event_types, "timeline": [safe_event(event) for event in timeline],
        }
