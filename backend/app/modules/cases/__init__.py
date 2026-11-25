
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ...catalog import CLINICS, STUDIES, get_demo_slots
from ...errors import APIError
from ...models import Case, Person
from ..events import append_event


STEP_ORDER = ("study", "patient_data", "clinic", "slot", "confirmed")


def empty_steps() -> dict[str, bool]:
    return {step: False for step in STEP_ORDER}


def derive_status(steps: dict[str, bool]) -> str:
    """Deriva el estado solo desde los pasos, independientemente de su orden."""
    if steps.get("confirmed"):
        return "cita_confirmada"
    if steps.get("slot"):
        return "horario_propuesto"
    if steps.get("clinic"):
        return "clinica_elegida"
    if steps.get("patient_data"):
        return "datos_completos"
    return "cotizando"


def missing_steps(steps: dict[str, bool]) -> list[str]:
    return [step for step in STEP_ORDER if not steps.get(step, False)]


def apply_step(case: Case, step: str) -> None:
    steps = {**empty_steps(), **(case.steps or {})}
    steps[step] = True
    case.steps = steps
    case.status = derive_status(steps)


def _iso(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "tzinfo") and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _person_view(person: Person) -> dict[str, Any]:
    return {
        "full_name": person.full_name or "Contacto sin registrar",
        "birth_date": person.birth_date.isoformat() if person.birth_date else None,
        "email": person.email,
        "phone": person.phone,
    }


def case_view(session: Session, case: Case) -> dict[str, Any]:
    requester = session.get(Person, case.requester_id)
    patient = session.get(Person, case.patient_id)
    return {
        "id": case.id,
        "relationship": case.relationship,
        "requester": _person_view(requester),
        "patient": _person_view(patient),
        "study_id": case.study_id,
        "clinic_id": case.clinic_id,
        "slot_id": case.slot_id,
        "slot_datetime": _iso(case.slot_datetime),
        "steps": {**empty_steps(), **(case.steps or {})},
        "status": case.status,
        "abandoned": case.abandoned,
        "current_channel": case.current_channel,
        "last_channel": case.last_channel,
        "version": case.version,
        "created_at": _iso(case.created_at),
        "updated_at": _iso(case.updated_at),
    }


def check_version(session: Session, case: Case, expected_version: int) -> None:
    if case.version != expected_version:
        raise APIError(
            409,
            "version_conflict",
            "El trámite cambió desde la última consulta.",
            {"case": case_view(session, case)},
        )


def change_channel(
    session: Session,
    case: Case,
    *,
    channel: str,
    actor_id: str,
    actor_role: str = "paciente",
    call_id: str | None = None,
) -> list[Any]:
    if case.last_channel == channel:
        case.current_channel = channel
        return []
    previous = case.last_channel
    case.last_channel = channel
    case.current_channel = channel
    return [
        append_event(
            session,
            event_type="canal_cambiado",
            channel=channel,
            actor_id=actor_id,
            case_id=case.id,
            person_id=case.requester_id,
            actor_role=actor_role,
            payload={"from": previous, "to": channel, **({"call_id": call_id} if call_id else {})},
        )
    ]


def create_case(
    session: Session,
    *,
    requester: Person,
    patient: Person,
    relationship: str,
    channel: str,
    actor_id: str,
    study_id: str | None = None,
) -> tuple[Case, list[Any]]:
    for person in (requester, patient):
        if not person.full_name or person.birth_date is None:
            raise APIError(422, "incomplete_person", "La persona necesita nombre y fecha de nacimiento antes de continuar.")
    if study_id is not None and not any(study["id"] == study_id for study in STUDIES):
        raise APIError(404, "study_not_found", "El estudio solicitado no existe.")
    steps = empty_steps()
    steps["patient_data"] = True
    steps["study"] = study_id is not None
    case = Case(
        id=f"C-{uuid4().hex[:8].upper()}",
        requester_id=requester.id,
        patient_id=patient.id,
        relationship=relationship,
        study_id=study_id,
        steps=steps,
        status=derive_status(steps),
        abandoned=False,
        current_channel=channel,
        last_channel=channel,
        version=1,
    )
    session.add(case)
    session.flush()
    events = [
        append_event(
            session,
            event_type="tramite_creado",
            channel=channel,
            actor_id=actor_id,
            case_id=case.id,
            person_id=requester.id,
            payload={"relationship": relationship},
        ),
        _record_patient_data(session, case, channel=channel, actor_id=actor_id),
    ]
    if study_id:
        events.append(
            append_event(
                session,
                event_type="estudio_seleccionado",
                channel=channel,
                actor_id=actor_id,
                case_id=case.id,
                person_id=requester.id,
                payload={"study_id": study_id},
            )
        )
    return case, events


def _record_patient_data(session: Session, case: Case, *, channel: str, actor_id: str):
    apply_step(case, "patient_data")
    return append_event(
        session,
        event_type="datos_paciente_capturados",
        channel=channel,
        actor_id=actor_id,
        case_id=case.id,
        person_id=case.requester_id,
        payload={"relationship": case.relationship},
    )


def update_case(
    session: Session,
    case: Case,
    *,
    action: str,
    expected_version: int,
    channel: str,
    actor_id: str,
    idempotency_key: str | None,
    study_id: str | None = None,
    clinic_id: str | None = None,
    slot_id: str | None = None,
    actor_role: str = "paciente",
    call_id: str | None = None,
    use_saved_patient_data: bool = False,
) -> tuple[list[Any], str]:
    check_version(session, case, expected_version)
    if case.status == "cancelado":
        raise APIError(422, "case_cancelled", "El trámite está cancelado y no puede modificarse.")

    events = change_channel(session, case, channel=channel, actor_id=actor_id, actor_role=actor_role, call_id=call_id)
    if action == "select_study":
        item = next((value for value in STUDIES if value["id"] == study_id), None)
        if item is None:
            raise APIError(404, "study_not_found", "El estudio solicitado no existe.")
        case.study_id = item["id"]
        apply_step(case, "study")
        event_type = "estudio_seleccionado"
        payload = {"study_id": item["id"]}
        message = "Estudio seleccionado."
    elif action == "select_clinic":
        item = next((value for value in CLINICS if value["id"] == clinic_id), None)
        if item is None:
            raise APIError(404, "clinic_not_found", "La clínica solicitada no existe.")
        if case.slot_id:
            selected_slot = next((value for value in get_demo_slots() if value["id"] == case.slot_id), None)
            if selected_slot and selected_slot["clinic_id"] != item["id"]:
                raise APIError(422, "clinic_slot_mismatch", "La clínica no corresponde al horario elegido.")
        case.clinic_id = item["id"]
        apply_step(case, "clinic")
        event_type = "clinica_seleccionada"
        payload = {"clinic_id": item["id"]}
        message = "Clínica seleccionada."
    elif action == "select_slot":
        item = next((value for value in get_demo_slots() if value["id"] == slot_id), None)
        if item is None:
            raise APIError(404, "slot_not_found", "El horario solicitado no existe.")
        if case.clinic_id and item["clinic_id"] != case.clinic_id:
            raise APIError(422, "clinic_slot_mismatch", "El horario no corresponde a la clínica elegida.")
        case.slot_id = item["id"]
        case.slot_datetime = datetime.fromisoformat(item["starts_at"].replace("Z", "+00:00"))
        apply_step(case, "slot")
        event_type = "horario_propuesto"
        payload = {"slot_id": item["id"], "starts_at": item["starts_at"]}
        message = "Horario seleccionado."
    else:
        requester = session.get(Person, case.requester_id)
        patient = session.get(Person, case.patient_id)
        if requester is None or patient is None or not requester.full_name or not requester.birth_date or not patient.full_name or not patient.birth_date:
            raise APIError(422, "incomplete_person", "La persona necesita nombre y fecha de nacimiento antes de continuar.")
        if use_saved_patient_data and requester.email and requester.phone and not case.steps.get("patient_data"):
            events.append(_record_patient_data(session, case, channel=channel, actor_id=actor_id))
        if any(not case.steps.get(step, False) for step in ("study", "patient_data", "clinic", "slot")):
            raise APIError(422, "incomplete_case", "Completa los datos pendientes antes de confirmar la cita.")
        apply_step(case, "confirmed")
        event_type = "cita_confirmada"
        payload = {}
        message = "Tu cita ficticia quedó confirmada."

    case.version += 1
    events.append(
        append_event(
            session,
            event_type=event_type,
            channel=channel,
            actor_id=actor_id,
            case_id=case.id,
            person_id=case.requester_id,
            actor_role=actor_role,
            payload={**payload, **({"call_id": call_id} if call_id else {})},
            idempotency_key=idempotency_key,
        )
    )
    return events, message
