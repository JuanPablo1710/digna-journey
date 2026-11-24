
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select

from ...db import SessionLocal, lock_demo_writes
from ...errors import APIError
from ...models import Case, Event, Note, Person, User, Verification
from ...config import settings
from ...security import mask_name
from ..auth import require_agent
from ..cases import case_view, missing_steps, update_case
from ..events import append_event, public_event_view
from ..identity.service import check_shared_dob, dob_counter, new_id, normalize_email, normalize_phone, utc_now
from .calls import active_call, call_event, owned_call


router = APIRouter(prefix="/agent", tags=["agent"])
case_router = APIRouter(tags=["agent"])
demo_router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/lookup")
def lookup(phone: str | None = None, email: str | None = None,
           _agent: User = Depends(require_agent)) -> dict:
    if bool(phone) == bool(email):
        raise APIError(422, "lookup_requires_identifier", "Escribe un teléfono o un correo para buscar.")
    match = Person.phone == normalize_phone(phone) if phone else Person.email == normalize_email(email)
    with SessionLocal() as session:
        people = session.scalars(
            select(Person).where(match, Person.full_name.is_not(None)).order_by(Person.id)
        ).all()
        return {"matches": [
            {"person_id": person.id, "masked_name": mask_name(person.full_name), "trust_level": 1}
            for person in people
        ]}


class VerifyData(BaseModel):
    person_id: str
    method: Literal["agent_assisted"]
    birth_date: date
    call_id: str | None = None


class NoteData(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class PatchFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    study_id: str | None = None
    clinic_id: str | None = None
    slot_id: str | None = None
    confirmed: Literal[True] | None = None


class PatchData(BaseModel):
    expected_version: int = Field(ge=1)
    fields: PatchFields


def _audit(session, agent, event_type, person_id, call_id=None, case_id=None, **payload):
    return append_event(
        session, event_type=event_type, channel="callcenter", actor_role="asesor",
        actor_id=agent.id, case_id=case_id, person_id=person_id,
        payload={**payload, **({"call_id": call_id} if call_id else {})},
    )


def _grant(session, agent, person_id):
    call = active_call(session, agent.id)
    identifier = call.payload["call_id"] if call else agent.id
    return session.scalar(select(Verification).where(
        Verification.person_id == person_id, Verification.channel == "callcenter",
        Verification.identifier == identifier, Verification.method == "agent_assisted",
        Verification.status == "succeeded", Verification.valid_until > utc_now(),
    ).limit(1))


def _require_grant(session, agent, person_id, grant, case_id=None):
    if grant is None:
        call = active_call(session, agent.id)
        _audit(session, agent, "acceso_denegado", person_id, call.payload["call_id"] if call else None,
               case_id, reason="verification_required")
        session.commit()
        raise APIError(403, "verification_required", "Verifica la identidad del solicitante para continuar.")


def _call_id(agent, grant):
    return grant.identifier if grant.identifier != agent.id else None


@router.post("/verify")
def verify(data: VerifyData, agent: User = Depends(require_agent)):
    error = None
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        call = owned_call(session, data.call_id, agent.id) if data.call_id else active_call(session, agent.id)
        if call and not data.call_id and call.payload["trust_level"] == 0:
            raise APIError(422, "call_required", "Indica la llamada para verificar un número oculto o desconocido.")
        call_id = call.payload["call_id"] if call else None
        binding = call_event(session, call_id, "identidad_vinculada") if call_id else None
        if binding and binding.person_id != data.person_id:
            raise APIError(409, "call_already_linked", "La llamada ya está vinculada a otra persona.")
        person = session.get(Person, data.person_id)
        if person is None or person.birth_date is None or not (person.email or person.phone):
            raise APIError(404, "person_not_found", "No encontramos al solicitante.")
        error = check_shared_dob(session, person, data.birth_date)
        if error:
            _audit(session, agent, "verificacion_fallida", person.id, call_id,
                   method=data.method, locked=error[0] == 429)
        else:
            valid_until = utc_now() + timedelta(minutes=30)
            session.add(Verification(
                id=new_id("V"), person_id=person.id, channel="callcenter",
                identifier=call_id or agent.id, method=data.method,
                status="succeeded", attempts=0, valid_until=valid_until,
            ))
            _audit(session, agent, "verificacion_exitosa", person.id, call_id, method=data.method)
            if call_id and not binding:
                _audit(session, agent, "identidad_vinculada", person.id, call_id)
                latest = session.scalar(select(Case).where(Case.requester_id == person.id)
                                        .order_by(Case.updated_at.desc()).limit(1))
                if latest and latest.last_channel != "callcenter":
                    _audit(session, agent, "canal_cambiado", person.id, call_id,
                           **{"from": latest.last_channel, "to": "callcenter"})
    if error:
        raise APIError(*error)
    return {"trust_level": 2, "valid_until": valid_until.isoformat(), "call_id": call_id}


def _note_view(note):
    return {"id": note.id, "text": note.text, "author_user_id": note.author_user_id,
            "created_at": note.created_at}


@router.get("/patients/{person_id}/context")
def context(person_id: str, agent: User = Depends(require_agent)):
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        person = session.get(Person, person_id)
        if person is None:
            raise APIError(404, "person_not_found", "No encontramos al solicitante.")
        grant = _grant(session, agent, person_id)
        _require_grant(session, agent, person_id, grant)
        _audit(session, agent, "contexto_consultado", person_id, _call_id(agent, grant))
        session.flush()
        cases = session.scalars(select(Case).where(Case.requester_id == person_id)
                                .order_by(Case.updated_at.desc())).all()
        ids = [case.id for case in cases]
        call_ids = session.scalars(select(Event.payload["call_id"].as_string()).where(
            Event.type == "identidad_vinculada", Event.channel == "callcenter",
            Event.person_id == person_id,
        )).all()
        events = session.scalars(select(Event).where(or_(
            Event.case_id.in_(ids), Event.person_id == person_id,
            Event.payload["call_id"].as_string().in_(call_ids),
        )).order_by(Event.seq)).all()
        notes = session.scalars(select(Note).where(Note.case_id.in_(ids)).order_by(Note.created_at)).all()
        return {
            "person_id": person.id,
            "cases": [{**case_view(session, case), "missing_steps": missing_steps(case.steps),
                       "notes": [_note_view(note) for note in notes if note.case_id == case.id]}
                      for case in cases],
            "timeline": [{**public_event_view(event), "case_id": event.case_id,
                          "actor": {"id": event.actor_id if event.channel == "callcenter" else None,
                                    "role": event.actor_role}}
                         for event in events],
        }


def _load_case(session, case_id):
    case = session.get(Case, case_id)
    if case is None:
        raise APIError(404, "case_not_found", "No encontramos el trámite.")
    return case


@router.post("/cases/{case_id}/notes", status_code=201)
def add_note(case_id: str, data: NoteData, agent: User = Depends(require_agent)):
    text = data.text.strip()
    if not text:
        raise APIError(422, "invalid_note", "Escribe el texto de la nota.")
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        case = _load_case(session, case_id)
        grant = _grant(session, agent, case.requester_id)
        _require_grant(session, agent, case.requester_id, grant, case.id)
        note = Note(id=new_id("N"), case_id=case.id, author_user_id=agent.id, text=text)
        session.add(note)
        _audit(session, agent, "nota_agregada", case.requester_id, _call_id(agent, grant),
               case.id, note_id=note.id)
        session.flush()
        return _note_view(note)


@case_router.patch("/cases/{case_id}")
def patch_case(case_id: str, data: PatchData, agent: User = Depends(require_agent)):
    changes = data.fields.model_dump(exclude_none=True)
    if not changes:
        raise APIError(422, "empty_patch", "Indica el paso que quieres actualizar.")
    actions = {"study_id": "select_study", "clinic_id": "select_clinic",
               "slot_id": "select_slot", "confirmed": "confirm_case"}
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        case = _load_case(session, case_id)
        grant = _grant(session, agent, case.requester_id)
        _require_grant(session, agent, case.requester_id, grant, case.id)
        version = data.expected_version
        events = []
        for field, action in actions.items():
            if field in changes:
                arguments = {field: changes[field]} if field != "confirmed" else {}
                emitted, _ = update_case(
                    session, case, action=action, expected_version=version,
                    channel="callcenter", actor_id=agent.id, idempotency_key=None,
                    actor_role="asesor", call_id=_call_id(agent, grant), **arguments,
                )
                events.extend(event.type for event in emitted)
                version = case.version
        case.version = data.expected_version + 1
        session.flush()
        return {"case": case_view(session, case), "missing_steps": missing_steps(case.steps), "events": events}


@demo_router.post("/patients/{person_id}/unlock")
def unlock(person_id: str, agent: User = Depends(require_agent)):
    if not settings.demo_mode:
        raise APIError(404, "not_found", "No encontramos este recurso.")
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        counter = dob_counter(session, person_id)
        if counter:
            session.delete(counter)
    return {"status": "ok"}
