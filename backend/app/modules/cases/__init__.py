
from datetime import timezone
from typing import Any

from sqlalchemy.orm import Session

from ...models import Case, Person


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
        "full_name": person.full_name,
        "birth_date": person.birth_date.isoformat(),
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
