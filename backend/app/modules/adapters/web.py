from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Cookie, Header, Response
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...catalog import CLINICS, STUDIES, get_demo_slots
from ...config import settings
from ...db import SessionLocal, lock_demo_writes
from ...errors import APIError
from ...models import Case, ChannelIdentity, Event, Person
from ...schemas import CaseActionData, DraftData, InteractionRequest, PreregisterData
from ..cases import case_view, derive_status, empty_steps, missing_steps, update_case
from ..events import append_event, public_event_view
from ..drafts import discard_draft_record, save_draft_record
from ..identity.service import ensure_complete_person, trust_level as identity_trust_level


router = APIRouter(tags=["web"])
SUPPORTED_ACTIONS = {
    "start_quote",
    "continue_case",
    "save_draft",
    "select_study",
    "preregister",
    "select_clinic",
    "select_slot",
    "confirm_case",
    "cancel_case",
    "new_case",
}
SESSION_COOKIE = "web_session"
SESSION_TTL = timedelta(minutes=30)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8].upper()}"


def _normalize_email(value: str | None) -> str | None:
    return value.strip().lower() if value else None


def _normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) == 10:
        return f"+52{digits}"
    if len(digits) == 12 and digits.startswith("52"):
        return f"+{digits}"
    if value.startswith("+") and 10 <= len(digits) <= 15:
        return f"+{digits}"
    raise APIError(422, "invalid_phone", "El teléfono debe tener un formato válido.")


def _study(study_id: str | None) -> dict[str, Any]:
    study = next((item for item in STUDIES if item["id"] == study_id), None)
    if study is None:
        raise APIError(404, "study_not_found", "El estudio solicitado no existe.")
    return study


def _clinic(clinic_id: str | None) -> dict[str, Any]:
    clinic = next((item for item in CLINICS if item["id"] == clinic_id), None)
    if clinic is None:
        raise APIError(404, "clinic_not_found", "La clínica solicitada no existe.")
    return clinic


def _slot(slot_id: str | None) -> dict[str, str]:
    slot = next((item for item in get_demo_slots() if item["id"] == slot_id), None)
    if slot is None:
        raise APIError(404, "slot_not_found", "El horario solicitado no existe.")
    return slot


def _parse(model: type, data: dict[str, Any]):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise APIError(422, "invalid_data", "Los datos enviados están incompletos o no son válidos.") from exc


def _identity(session: Session, identifier: str) -> ChannelIdentity | None:
    return session.scalar(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == "web", ChannelIdentity.identifier == identifier
        )
    )


def _origin_identity(session: Session, identifier: str, case: Case) -> ChannelIdentity:
    identity = _identity(session, identifier)
    if identity is None or identity.person_id != case.requester_id:
        raise APIError(403, "access_denied", "Esta sesión no puede consultar ni modificar el trámite.")
    if identity_trust_level(session, channel="web", identifier=identifier, case=case) < 2:
        raise APIError(403, "verification_required", "Necesitas verificar tu identidad para continuar.")
    identity.last_seen_at = _utc_now()
    return identity


def _identity_is_fresh(identity: ChannelIdentity) -> bool:
    return not (identity.session_state or {}).get("invalidated") and (
        _utc_now() - _aware(identity.last_seen_at) <= SESSION_TTL
    )


def _load_case(session: Session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise APIError(404, "case_not_found", "El trámite solicitado no existe.")
    return case


def _check_version(session: Session, case: Case, expected_version: int) -> None:
    if case.version != expected_version:
        raise APIError(
            409,
            "version_conflict",
            "El trámite cambió desde la última consulta.",
            {"case": case_view(session, case)},
        )


def _response(
    session: Session,
    *,
    case: Case | None,
    event_types: list[str],
    message: str,
    trust_level: int,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "trust_level": trust_level,
        "case": case_view(session, case) if case else None,
        "missing_steps": (
            [] if case and case.status == "cancelado" else missing_steps(case.steps) if case else []
        ),
        "messages": [{"text": message, "quick_replies": []}],
        "events": event_types,
    }
    if extra:
        result.update(extra)
    return result


def _store_idempotent_response(marker: Event, result: dict[str, Any]) -> None:
    marker.payload = {**(marker.payload or {}), "_response": result}


def _draft(identity: ChannelIdentity) -> dict[str, Any] | None:
    value = (identity.session_state or {}).get("draft")
    return value if isinstance(value, dict) else None


def _clear_draft(session: Session, identity: ChannelIdentity) -> None:
    discard_draft_record(session, identity)
    state = dict(identity.session_state or {})
    for key in (
        "draft",
        "draft_updated_at",
        "draft_idempotency_key",
        "draft_response",
    ):
        state.pop(key, None)
    identity.session_state = state


def _active_case(session: Session, person_id: str | None) -> Case | None:
    if person_id is None:
        return None
    return session.scalar(
        select(Case)
        .where(Case.requester_id == person_id, Case.status != "cancelado")
        .order_by(Case.created_at.desc())
        .limit(1)
    )


def _visible_cases(session: Session, identity: ChannelIdentity) -> list[Case]:
    if identity.person_id is None:
        return []
    cases = session.scalars(
        select(Case)
        .where(Case.requester_id == identity.person_id)
        .order_by(Case.created_at.desc())
    ).all()
    return [
        case
        for case in cases
        if identity_trust_level(session, channel="web", identifier=identity.identifier, case=case) >= 2
    ]


def _previous_cases(cases: list[Case], current: Case | None) -> list[dict[str, str | None]]:
    return [
        {"status": case.status, "study_id": case.study_id}
        for case in cases
        if current is None or case.id != current.id
    ][:3]


def _merge_draft(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in patch.items():
        if key in {"requester", "patient"} and isinstance(value, dict):
            previous = merged.get(key) if isinstance(merged.get(key), dict) else {}
            merged[key] = {**previous, **value}
        else:
            merged[key] = value
    return merged


def _save_draft(session: Session, request: InteractionRequest) -> dict[str, Any]:
    if request.identifier_type != "session":
        raise APIError(422, "invalid_identifier", "El canal web requiere un identificador de sesión.")
    data = _parse(DraftData, request.data)
    patch = data.model_dump(mode="json", exclude_unset=True)
    if patch.get("study_id"):
        _study(patch["study_id"])

    identity = _identity(session, request.identifier)
    if identity is None:
        identity = ChannelIdentity(
            id=_new_id("CI"),
            person_id=None,
            channel="web",
            identifier=request.identifier,
            identifier_type="session",
            session_state={},
            last_seen_at=_utc_now(),
        )
        session.add(identity)
        session.flush()

    state = dict(identity.session_state or {})
    if state.get("draft_idempotency_key") == request.idempotency_key:
        stored = state.get("draft_response")
        if isinstance(stored, dict):
            return stored

    if state.get("draft_transferred"):
        raise APIError(409, "draft_transferred", "El borrador se retomó en otra sesión.")

    if _active_case(session, identity.person_id) is not None:
        return _response(
            session,
            case=None,
            event_types=[],
            message="El preregistro ya se convirtió en un trámite.",
            trust_level=2,
            extra={"draft": None},
        )

    stored_at = state.get("draft_updated_at")
    if stored_at:
        previous_timestamp = datetime.fromisoformat(stored_at.replace("Z", "+00:00"))
        if _aware(request.timestamp) < _aware(previous_timestamp):
            return _response(
                session,
                case=None,
                event_types=[],
                message="Borrador guardado.",
                trust_level=2 if identity.person_id else 0,
                extra={"draft": _draft(identity)},
            )

    merged = _merge_draft(_draft(identity) or {}, patch)
    save_draft_record(session, identity, merged)
    identity.last_seen_at = _utc_now()
    result = _response(
        session,
        case=None,
        event_types=[],
        message="Borrador guardado.",
        trust_level=2 if identity.person_id else 0,
        extra={"draft": merged},
    )
    identity.session_state = {
        **state,
        "draft": merged,
        "draft_updated_at": _aware(request.timestamp).isoformat().replace("+00:00", "Z"),
        "draft_idempotency_key": request.idempotency_key,
        "draft_response": result,
    }
    return result


def _first_contact_events(
    session: Session, identifier: str, case_id: str | None = None, person_id: str | None = None
) -> list[Event]:
    already_created = session.scalar(
        select(Event.seq).where(
            Event.channel == "web",
            Event.actor_id == identifier,
            Event.type == "contacto_creado",
        )
    )
    if already_created is not None:
        return []
    return [
        append_event(
            session,
            event_type="contacto_creado",
            channel="web",
            actor_id=identifier,
            case_id=case_id,
            person_id=person_id,
        ),
        append_event(
            session,
            event_type="consentimiento_aceptado",
            channel="web",
            actor_id=identifier,
            case_id=case_id,
            person_id=person_id,
            payload={"accepted_at": _utc_now().isoformat().replace("+00:00", "Z")},
        ),
        append_event(
            session,
            event_type="canal_iniciado",
            channel="web",
            actor_id=identifier,
            case_id=case_id,
            person_id=person_id,
        ),
    ]


def _public_action(session: Session, request: InteractionRequest) -> dict[str, Any]:
    events = _first_contact_events(session, request.identifier)
    extra: dict[str, Any] | None = None
    if request.action == "select_study":
        study = _study(request.data.get("study_id"))
        events.append(
            append_event(
                session,
                event_type="estudio_seleccionado",
                channel="web",
                actor_id=request.identifier,
                payload={"study_id": study["id"]},
            )
        )
        message = f"{study['name']}: ${study['price']} MXN (precio ficticio)."
        extra = {"quote": study}
    else:
        if not events:
            events.append(
                append_event(
                    session,
                    event_type="canal_iniciado",
                    channel="web",
                    actor_id=request.identifier,
                )
            )
        message = "Selecciona un estudio para consultar su precio ficticio."
    events[0].idempotency_key = request.idempotency_key
    session.flush()
    result = _response(
        session,
        case=None,
        event_types=[event.type for event in events],
        message=message,
        trust_level=0,
        extra=extra,
    )
    _store_idempotent_response(events[0], result)
    return result


def _continue_case(
    session: Session,
    request: InteractionRequest,
    cookie_identifier: str | None,
) -> dict[str, Any]:
    """Retoma solo con la cookie de origen; localStorage por sí solo no da confianza."""
    if cookie_identifier != request.identifier:
        return _response(
            session,
            case=None,
            event_types=[],
            message="No hay un trámite activo en esta sesión.",
            trust_level=0,
            extra={"draft": None, "reset_session": True},
        )

    identity = _identity(session, cookie_identifier)
    if identity is None or not _identity_is_fresh(identity):
        return _response(
            session,
            case=None,
            event_types=[],
            message="No hay un trámite activo en esta sesión.",
            trust_level=0,
            extra={"draft": None, "reset_session": True},
        )

    draft = _draft(identity)
    visible_cases = _visible_cases(session, identity)
    active_cases = [item for item in visible_cases if item.status != "cancelado"]
    selected_id = (identity.session_state or {}).get("resume_case_id")
    case = next((item for item in active_cases if item.id == selected_id), None)
    if case is None and active_cases:
        case = active_cases[0]
    identity.last_seen_at = _utc_now()
    if case is None and draft is not None:
        return _response(
            session,
            case=None,
            event_types=[],
            message="Retomamos tu borrador donde lo dejaste.",
            trust_level=2 if identity.person_id else 0,
            extra={"draft": draft, "reset_session": False, "previous_cases": []},
        )
    if case is None and identity.person_id is None:
        return _response(
            session,
            case=None,
            event_types=[],
            message="No hay un trámite activo en esta sesión.",
            trust_level=0,
            extra={"draft": None, "reset_session": False, "previous_cases": []},
        )

    level = identity_trust_level(session, channel="web", identifier=request.identifier, case=case) if case else 1
    if case is not None and level < 2:
        append_event(
            session,
            event_type="acceso_denegado",
            channel="web",
            actor_id=request.identifier,
            case_id=case.id,
            person_id=identity.person_id,
            payload={"reason": "verification_required"},
        )
        return {
            "trust_level": level,
            "case": {"id": case.id, "pending": True},
            "missing_steps": [],
            "messages": [{"text": "Verifica tu identidad para ver el trámite.", "quick_replies": []}],
            "events": ["acceso_denegado"],
            "draft": None,
            "reset_session": False,
            "previous_cases": [],
        }

    duplicate = session.scalar(
        select(Event).where(
            Event.idempotency_key == request.idempotency_key,
            Event.actor_id == request.identifier,
        )
    )
    if duplicate is not None:
        stored = (duplicate.payload or {}).get("_response")
        if stored is not None:
            return stored

    event = append_event(
        session,
        event_type="canal_iniciado",
        channel="web",
        actor_id=request.identifier,
        case_id=case.id if case else None,
        person_id=identity.person_id,
        idempotency_key=request.idempotency_key,
        payload={"resumed": case is not None},
    )
    session.flush()
    result = _response(
        session,
        case=case,
        event_types=[event.type],
        message=(
            "Retomamos tu trámite donde lo dejaste."
            if case
            else "No hay un trámite activo en esta sesión."
        ),
        trust_level=2,
        extra={
            "draft": None,
            "reset_session": False,
            "previous_cases": _previous_cases(visible_cases, case),
        },
    )
    _store_idempotent_response(event, result)
    return result


def _create_person(data) -> Person:
    return Person(
        id=_new_id("P"),
        full_name=data.full_name.strip(),
        birth_date=data.birth_date,
        email=_normalize_email(data.email),
        phone=_normalize_phone(data.phone),
        is_provisional=True,
    )


def _ensure_case_people_complete(session: Session, case: Case) -> None:
    ensure_complete_person(session.get(Person, case.requester_id))
    ensure_complete_person(session.get(Person, case.patient_id))


def _preregister(session: Session, request: InteractionRequest) -> dict[str, Any]:
    if request.identifier_type != "session":
        raise APIError(422, "invalid_identifier", "El canal web requiere un identificador de sesión.")
    data = _parse(PreregisterData, request.data)
    if not data.requester.email or not data.requester.phone:
        raise APIError(422, "missing_requester_data", "El correo y teléfono del solicitante son obligatorios.")
    if data.relationship != "self" and data.patient is None:
        raise APIError(422, "missing_patient", "Captura los datos de la persona que recibirá el estudio.")

    identity = _identity(session, request.identifier)
    if identity and (identity.session_state or {}).get("draft_transferred"):
        raise APIError(409, "draft_transferred", "El borrador se retomó en otra sesión.")
    if identity is None or identity.person_id is None:
        requester = _create_person(data.requester)
        session.add(requester)
        if identity is None:
            identity = ChannelIdentity(
                id=_new_id("CI"),
                person_id=requester.id,
                channel="web",
                identifier=request.identifier,
                identifier_type="session",
                session_state={},
                last_seen_at=_utc_now(),
            )
            session.add(identity)
        else:
            identity.person_id = requester.id
            identity.last_seen_at = _utc_now()
    else:
        requester = session.get(Person, identity.person_id)
        requester.full_name = data.requester.full_name.strip()
        requester.birth_date = data.requester.birth_date
        requester.email = _normalize_email(data.requester.email)
        requester.phone = _normalize_phone(data.requester.phone)
        identity.last_seen_at = _utc_now()

    _clear_draft(session, identity)

    if data.relationship == "self":
        patient = requester
    else:
        patient = _create_person(data.patient)
        session.add(patient)

    ensure_complete_person(requester)
    ensure_complete_person(patient)

    steps = empty_steps()
    steps["patient_data"] = True
    if data.study_id:
        _study(data.study_id)
        steps["study"] = True
    case = Case(
        id=_new_id("C"),
        requester_id=requester.id,
        patient_id=patient.id,
        relationship=data.relationship,
        study_id=data.study_id,
        steps=steps,
        status=derive_status(steps),
        abandoned=False,
        current_channel="web",
        last_channel="web",
        version=1,
    )
    session.add(case)
    session.flush()

    events = _first_contact_events(session, request.identifier, case.id, requester.id)
    events.append(
        append_event(
            session,
            event_type="tramite_creado",
            channel="web",
            actor_id=request.identifier,
            case_id=case.id,
            person_id=requester.id,
            payload={"relationship": data.relationship},
        )
    )
    events.append(
        append_event(
            session,
            event_type="datos_paciente_capturados",
            channel="web",
            actor_id=request.identifier,
            case_id=case.id,
            person_id=requester.id,
            payload={"relationship": data.relationship},
        )
    )
    if data.study_id:
        events.append(
            append_event(
                session,
                event_type="estudio_seleccionado",
                channel="web",
                actor_id=request.identifier,
                case_id=case.id,
                person_id=requester.id,
                payload={"study_id": data.study_id},
            )
        )
    marker = events[0]
    marker.idempotency_key = request.idempotency_key
    session.flush()
    result = _response(
        session,
        case=case,
        event_types=[event.type for event in events],
        message="Preregistro guardado. Puedes continuar con la clínica y el horario.",
        trust_level=2,
    )
    _store_idempotent_response(marker, result)
    return result


def _cancel_case(
    session: Session,
    request: InteractionRequest,
    cookie_identifier: str | None,
) -> dict[str, Any]:
    case_id = request.data.get("case_id")
    if not case_id:
        identity = _identity(session, request.identifier)
        if identity is None:
            return _response(
                session,
                case=None,
                event_types=[],
                message="No hay un borrador activo.",
                trust_level=0,
                extra={"draft": None},
            )
        if cookie_identifier != request.identifier or not _identity_is_fresh(identity):
            raise APIError(403, "session_expired", "La sesión de origen expiró.")
        _clear_draft(session, identity)
        identity.last_seen_at = _utc_now()
        return _response(
            session,
            case=None,
            event_types=[],
            message="Borrador descartado.",
            trust_level=2 if identity.person_id else 0,
            extra={"draft": None},
        )

    data = _parse(CaseActionData, request.data)
    case = _load_case(session, data.case_id)
    identity = _origin_identity(session, request.identifier, case)
    _check_version(session, case, data.expected_version)
    _clear_draft(session, identity)
    if case.status == "cancelado":
        return _response(
            session,
            case=case,
            event_types=[],
            message="El trámite ya estaba cancelado.",
            trust_level=2,
            extra={"draft": None},
        )

    case.status = "cancelado"
    case.version += 1
    event = append_event(
        session,
        event_type="tramite_cancelado",
        channel="web",
        actor_id=request.identifier,
        case_id=case.id,
        person_id=case.requester_id,
        payload={},
        idempotency_key=request.idempotency_key,
    )
    session.flush()
    result = _response(
        session,
        case=case,
        event_types=[event.type],
        message="El trámite fue cancelado.",
        trust_level=2,
        extra={"draft": None},
    )
    _store_idempotent_response(event, result)
    return result


def _new_case(
    session: Session,
    request: InteractionRequest,
) -> dict[str, Any]:
    data = _parse(CaseActionData, request.data)
    source_case = _load_case(session, data.case_id)
    identity = _origin_identity(session, request.identifier, source_case)
    _check_version(session, source_case, data.expected_version)
    if source_case.status != "cita_confirmada":
        raise APIError(422, "case_not_confirmed", "Solo puedes agendar otro estudio después de confirmar una cita.")

    requester = session.get(Person, source_case.requester_id)
    ensure_complete_person(requester)
    steps = empty_steps()
    steps["patient_data"] = True
    new_case = Case(
        id=_new_id("C"),
        requester_id=requester.id,
        patient_id=requester.id,
        relationship="self",
        steps=steps,
        status=derive_status(steps),
        abandoned=False,
        current_channel="web",
        last_channel="web",
        version=1,
    )
    session.add(new_case)
    session.flush()
    event = append_event(
        session,
        event_type="tramite_creado",
        channel="web",
        actor_id=request.identifier,
        case_id=new_case.id,
        person_id=requester.id,
        payload={"relationship": "self"},
        idempotency_key=request.idempotency_key,
    )
    identity.last_seen_at = _utc_now()
    _clear_draft(session, identity)
    session.flush()
    visible_cases = _visible_cases(session, identity)
    result = _response(
        session,
        case=new_case,
        event_types=[event.type],
        message="Puedes elegir el estudio para tu nuevo trámite.",
        trust_level=2,
        extra={"draft": None, "previous_cases": _previous_cases(visible_cases, new_case)},
    )
    _store_idempotent_response(event, result)
    return result


def _case_action(session: Session, request: InteractionRequest) -> dict[str, Any]:
    data = _parse(CaseActionData, request.data)
    case = _load_case(session, data.case_id)
    _origin_identity(session, request.identifier, case)
    events, message = update_case(
        session,
        case,
        action=request.action,
        expected_version=data.expected_version,
        channel="web",
        actor_id=request.identifier,
        idempotency_key=request.idempotency_key,
        study_id=data.study_id,
        clinic_id=data.clinic_id,
        slot_id=data.slot_id,
    )
    session.flush()
    result = _response(
        session,
        case=case,
        event_types=[event.type for event in events],
        message=message,
        trust_level=2,
    )
    _store_idempotent_response(events[-1], result)
    return result


def process_interaction(
    session: Session,
    request: InteractionRequest,
    cookie_identifier: str | None = None,
) -> dict[str, Any]:
    if request.kind != "action" or request.action not in SUPPORTED_ACTIONS:
        raise APIError(422, "unsupported_action", "La acción web no está disponible en esta rebanada.")
    if request.action == "continue_case":
        return _continue_case(session, request, cookie_identifier)
    if request.action == "save_draft":
        return _save_draft(session, request)
    duplicate = session.scalar(select(Event).where(Event.idempotency_key == request.idempotency_key))
    if duplicate is not None:
        stored = (duplicate.payload or {}).get("_response")
        if stored is not None:
            return stored
    if request.action in {"start_quote", "select_study"} and not request.data.get("case_id"):
        return _public_action(session, request)
    if request.action == "preregister":
        return _preregister(session, request)
    if request.action == "cancel_case":
        return _cancel_case(session, request, cookie_identifier)
    if request.action == "new_case":
        return _new_case(session, request)
    return _case_action(session, request)


def _verify_channel_key(channel_key: str) -> None:
    if channel_key != settings.channel_key_web:
        raise APIError(403, "invalid_channel_key", "La clave del canal no es válida.")


@router.post("/channels/web/interactions")
def web_interaction(
    request: InteractionRequest,
    response: Response,
    channel_key: str = Header(alias="X-Channel-Key"),
    web_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, Any]:
    _verify_channel_key(channel_key)
    with SessionLocal() as session:
        try:
            with session.begin():
                lock_demo_writes(session)
                existing_identity = _identity(session, request.identifier)
                if request.action != "continue_case" and existing_identity is not None:
                    if web_session != request.identifier or not _identity_is_fresh(existing_identity):
                        raise APIError(403, "session_expired", "La sesión de origen expiró.")
                result = process_interaction(session, request, web_session)
        except APIError as exc:
            if exc.status_code == 403:
                case_id = request.data.get("case_id")
                with session.begin():
                    case = session.get(Case, case_id) if case_id else None
                    append_event(
                        session,
                        event_type="acceso_denegado",
                        channel="web",
                        actor_id=request.identifier,
                        case_id=case.id if case else None,
                        person_id=case.requester_id if case else None,
                        payload={"reason": exc.error},
                    )
            raise
    if request.action == "continue_case" and result.get("reset_session"):
        response.delete_cookie(SESSION_COOKIE, samesite="lax")
    else:
        response.set_cookie(
            SESSION_COOKIE,
            request.identifier,
            max_age=int(SESSION_TTL.total_seconds()),
            httponly=True,
            samesite="lax",
        )
    return result


def _denied_event(session: Session, case: Case, identifier: str | None, reason: str) -> None:
    append_event(
        session,
        event_type="acceso_denegado",
        channel="web",
        actor_id=identifier or "anonymous",
        case_id=case.id,
        person_id=case.requester_id,
        payload={"reason": reason},
    )


@router.get("/cases/{case_id}")
def get_case(case_id: str, web_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    with SessionLocal() as session:
        with session.begin():
            case = _load_case(session, case_id)
            level = identity_trust_level(session, channel="web", identifier=web_session, case=case)
            if level == 0:
                _denied_event(session, case, web_session, "identity_not_linked")
                result = None
            elif level == 1:
                result = {"trust_level": 1, "case": {"id": case.id, "pending": True}, "missing_steps": []}
            else:
                identity = _identity(session, web_session)
                identity.last_seen_at = _utc_now()
                result = {
                    "trust_level": 2,
                    "case": case_view(session, case),
                    "missing_steps": missing_steps(case.steps),
                }
        if result is None:
            raise APIError(403, "access_denied", "Esta sesión no puede consultar el trámite.")
        return result


@router.get("/cases/{case_id}/timeline")
def get_timeline(case_id: str, web_session: str | None = Cookie(default=None, alias=SESSION_COOKIE)):
    with SessionLocal() as session:
        with session.begin():
            case = _load_case(session, case_id)
            level = identity_trust_level(session, channel="web", identifier=web_session, case=case)
            if level < 2:
                _denied_event(session, case, web_session, "verification_required")
                result = None
            else:
                identity = _identity(session, web_session)
                identity.last_seen_at = _utc_now()
                events = session.scalars(
                    select(Event)
                    .where(
                        or_(
                            Event.case_id == case.id,
                            (Event.case_id.is_(None) & (Event.actor_id == web_session) & (Event.channel == "web")),
                        )
                    )
                    .order_by(Event.seq)
                ).all()
                result = {"events": [public_event_view(event) for event in events]}
        if result is None:
            raise APIError(403, "verification_required", "Necesitas verificar tu identidad para ver la línea de tiempo.")
        return result

