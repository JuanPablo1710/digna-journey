
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from ...db import SessionLocal
from ...models import Case, Event, Person, User
from ...security import masked_person
from ..auth import require_admin
from ..events.safe import safe_event, utc_iso
from .metrics import dashboard_counts, journeys


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
AUDIT_TYPES = {"contexto_consultado", "acceso_denegado", "verificacion_solicitada", "verificacion_exitosa", "verificacion_fallida"}
Statuses = Literal["cotizando", "datos_completos", "clinica_elegida", "horario_propuesto", "cita_confirmada", "cancelado"]
Channels = Literal["web", "whatsapp", "callcenter", "app"]


def _cases_and_routes(session):
    cases = session.scalars(select(Case).order_by(Case.updated_at.desc(), Case.id)).all()
    events = session.scalars(select(Event).where(Event.case_id.is_not(None))
                             .order_by(Event.timestamp, Event.seq)).all()
    routes, events_by_case = journeys(cases, events)
    return cases, routes, events_by_case


@router.get("/dashboard")
def dashboard():
    with SessionLocal() as session:
        cursor = session.scalar(select(func.max(Event.seq))) or 0
        cases, routes, by_case = _cases_and_routes(session)
        recent = session.scalars(select(Event).where(Event.seq <= cursor)
                                 .order_by(Event.timestamp.desc(), Event.seq.desc()).limit(20)).all()
        return {
            **dashboard_counts(cases, routes, by_case),
            "journeys": routes,
            "recent_events": [{**safe_event(event, session.get(Person, event.person_id) if event.person_id else None),
                               "cursor": event.seq} for event in recent],
            "cursor": cursor,
        }


@router.get("/cases")
def list_cases(status: Statuses | None = None, channel: Channels | None = None):
    with SessionLocal() as session:
        cases, routes, _ = _cases_and_routes(session)
        return {"cases": [{
            "id": case.id, "status": case.status, "abandoned": case.abandoned,
            "study_id": case.study_id, "clinic_id": case.clinic_id, "channels": routes[case.id],
            "requester": masked_person(session.get(Person, case.requester_id)),
            "patient": masked_person(session.get(Person, case.patient_id)),
            "updated_at": utc_iso(case.updated_at),
        } for case in cases if (not status or case.status == status) and (not channel or channel in routes[case.id])]}


@router.get("/audit")
def audit():
    with SessionLocal() as session:
        entries = session.scalars(select(Event).where(Event.type.in_(AUDIT_TYPES))
                                  .order_by(Event.timestamp.desc(), Event.seq.desc()).limit(100)).all()
        staff_ids = set(session.scalars(select(User.id).where(User.role.in_(("asesor", "admin")))))
        results = []
        for event in entries:
            contact = masked_person(session.get(Person, event.person_id)) if event.person_id else None
            roles = {"paciente", "asesor", "admin"}
            role = event.actor_role if event.actor_role in roles else None
            is_staff = role in {"asesor", "admin"} and event.actor_id in staff_ids
            results.append({
                **safe_event(event),
                "cursor": event.seq,
                "actor": {"role": role, "id": event.actor_id if is_staff else None},
                "person": contact,
            })
        return {"entries": results}
