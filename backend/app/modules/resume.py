import secrets
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Cookie, Header, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from ..config import settings
from ..db import SessionLocal, lock_demo_writes
from ..errors import APIError
from ..models import Case, ChannelIdentity, Draft, MailboxMessage, Person, ResumeChallenge, Verification
from ..security import hash_password, verify_hash
from .cases import case_view, change_channel, check_version
from .drafts import owned_draft
from .events import append_event
from .identity.service import _identity, aware, new_id, normalize_email, normalize_phone, utc_now

router = APIRouter(prefix="/resume", tags=["resume"])
NEUTRAL = "Si podemos verificar los datos, enviaremos un código al correo correspondiente."


class RequestData(BaseModel):
    channel: Literal["web", "whatsapp"]
    email: str = Field(max_length=320)
    phone: str | None = None


class ConfirmData(BaseModel):
    challenge_id: str
    code: str = Field(pattern=r"^[0-9]{6}$")


class SelectData(BaseModel):
    challenge_id: str
    kind: Literal["case", "draft"]
    id: str
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


def _destination(cookie, phone=None):
    return f"{cookie}:{phone}" if phone else cookie


def _audit(session, challenge, event_type, **extra):
    append_event(session, event_type=event_type, channel=challenge.channel,
                 actor_id=challenge.id, payload={"method": "email_otp", **extra})


def _deliver(email, code, eligible):
    if eligible and settings.demo_mode:
        with SessionLocal.begin() as session:
            session.add(MailboxMessage(
                id=new_id("MAIL"), email=email, subject="Tu código para retomar (demo)",
                body=f"Tu código para retomar es {code}.", code=code,
            ))


@router.post("/request", status_code=202)
def request_resume(data: RequestData, background: BackgroundTasks, response: Response,
                   web_session: str | None = Cookie(None),
                   channel_key: str | None = Header(None, alias="X-Channel-Key")):
    phone = None
    if data.channel == "whatsapp":
        if channel_key != settings.channel_key_whatsapp:
            raise APIError(403, "invalid_channel_key", "La clave del canal no es válida.")
        phone = normalize_phone(data.phone or "")
    email = normalize_email(data.email)
    now = utc_now()
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        browser = _identity(session, "web", web_session) if web_session else None
        if not web_session or (browser and ((browser.session_state or {}).get("invalidated")
                                            or now - aware(browser.last_seen_at) > timedelta(minutes=30))):
            web_session = f"web-{uuid4()}"
        destination = _destination(web_session, phone)
        session.execute(delete(ResumeChallenge).where(
            ResumeChallenge.expires_at <= now,
            (ResumeChallenge.locked_until.is_(None) | (ResumeChallenge.locked_until <= now)),
            (ResumeChallenge.valid_until.is_(None) | (ResumeChallenge.valid_until <= now)),
        ))
        challenge = session.scalar(select(ResumeChallenge).where(
            ResumeChallenge.destination == destination, ResumeChallenge.channel == data.channel,
            ResumeChallenge.email == email, ResumeChallenge.valid_until.is_(None),
        ))
        if challenge is None:
            people = session.scalars(select(Person.id).where(Person.email == email).limit(2)).all()
            person_id = people[0] if len(people) == 1 else None
            drafts = session.scalars(select(Draft.id).where(Draft.email == email, Draft.expires_at > now)).all()
            code = f"{secrets.randbelow(1_000_000):06d}"
            challenge = ResumeChallenge(
                id=str(uuid4()), email=email, channel=data.channel, destination=destination,
                code_hash=hash_password(code), expires_at=now + timedelta(minutes=5),
                scope={"person_id": person_id, "draft_ids": list(drafts), "phone": phone,
                       "eligible": bool(people or drafts)},
            )
            session.add(challenge)
            _audit(session, challenge, "verificacion_solicitada")
            background.add_task(_deliver, email, code, challenge.scope["eligible"])
    response.set_cookie("web_session", web_session, max_age=1800, httponly=True, samesite="lax")
    return {"challenge_id": challenge.id, "message": NEUTRAL}


def _challenge(session, challenge_id, cookie):
    challenge = session.get(ResumeChallenge, challenge_id)
    browser = _identity(session, "web", cookie) if cookie else None
    if (not challenge or not cookie or challenge.destination != _destination(cookie, challenge.scope.get("phone"))
            or (browser and (browser.session_state or {}).get("invalidated"))):
        raise APIError(403, "resume_denied", "No se pudo verificar la solicitud.")
    return challenge


def bind_whatsapp_resume(session, challenge_id, cookie, phone):
    challenge = _challenge(session, challenge_id, cookie)
    if (challenge.channel != "whatsapp" or challenge.scope.get("phone") != phone
            or not challenge.valid_until or aware(challenge.valid_until) <= utc_now()):
        raise APIError(403, "resume_denied", "Verifica tu correo para continuar.")
    selected = [item[1] for item in challenge.selections.values() if item[0] == "case"]
    session.info["resume_case_ids"] = selected
    session.info["resume_challenge_id"] = challenge.id


def _items(session, challenge):
    person_id = challenge.scope["person_id"]
    person = session.get(Person, person_id) if person_id else None
    cases = session.scalars(select(Case).where(
        Case.requester_id == person_id, Case.status != "cancelado",
    )).all() if person and person.email == challenge.email else []
    drafts = session.scalars(select(Draft).where(
        Draft.id.in_(challenge.scope["draft_ids"]), Draft.email == challenge.email,
        Draft.expires_at > utc_now(),
    )).all()
    items = [
        dict(kind="case", id=case.id, version=case.version, status=case.status,
             study_id=case.study_id, clinic_id=case.clinic_id, channel=case.last_channel,
             updated_at=aware(case.updated_at).isoformat())
        for case in cases
    ] + [
        dict(kind="draft", id=draft.id, version=draft.version, status="borrador",
             study_id=draft.data.get("study_id"), clinic_id=None,
             channel=session.get(ChannelIdentity, draft.identity_id).channel,
             updated_at=aware(draft.updated_at).isoformat())
        for draft in drafts
    ]
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


@router.post("/confirm")
def confirm_resume(data: ConfirmData, web_session: str | None = Cookie(None)):
    error = None
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        challenge = _challenge(session, data.challenge_id, web_session)
        now = utc_now()
        if challenge.locked_until and aware(challenge.locked_until) > now:
            raise APIError(429, "resume_locked", "La verificación está bloqueada temporalmente.")
        if challenge.valid_until or aware(challenge.expires_at) <= now:
            raise APIError(410, "resume_expired", "Solicita un código nuevo.")
        correct = verify_hash(data.code, challenge.code_hash)
        if not (correct and challenge.scope["eligible"]):
            challenge.attempts += 1
            locked = challenge.attempts >= 3
            if locked:
                challenge.locked_until = now + timedelta(minutes=10)
            _audit(session, challenge, "verificacion_fallida", locked=locked)
            error = APIError(429 if locked else 422, "resume_locked" if locked else "incorrect_code",
                             "La verificación está bloqueada temporalmente." if locked else "El código es incorrecto.",
                             {"attempts_remaining": max(0, 3 - challenge.attempts)})
        else:
            challenge.valid_until = now + timedelta(minutes=30)
            _audit(session, challenge, "verificacion_exitosa")
            items = _items(session, challenge)
    if error:
        raise error
    return {"items": items}


def _target(session, channel, identifier):
    identity = _identity(session, channel, identifier)
    if identity is None:
        identity = ChannelIdentity(
            id=new_id("CI"), channel=channel, identifier=identifier,
            identifier_type="session" if channel == "web" else "phone", session_state={},
        )
        session.add(identity)
        session.flush()
    return identity


def _transfer(session, draft, target):
    source = session.get(ChannelIdentity, draft.identity_id)
    if source.id != target.id:
        if owned_draft(session, target):
            raise APIError(409, "draft_exists", "La sesión actual ya tiene un borrador.")
        source.session_state = {key: value for key, value in (source.session_state or {}).items()
                                if not key.startswith("draft") and key != "conversation"}
        source.session_state = {**source.session_state, "draft_transferred": True}
    draft.identity_id = target.id
    draft.version += 1
    draft.updated_at = utc_now()
    draft.expires_at = draft.updated_at + timedelta(minutes=30)
    target.last_seen_at = draft.updated_at
    state = {key: value for key, value in (target.session_state or {}).items() if not key.startswith("draft")}
    if target.channel == "web":
        state["draft"] = draft.data
    else:
        requester = draft.data.get("requester") or {}
        patient = draft.data.get("patient") or {}
        values = {**requester, "relationship": draft.data.get("relationship"),
                  "patient_name": patient.get("full_name"), "patient_birth_date": patient.get("birth_date")}
        steps = [("full_name", "full_name"), ("birth_date", "birth_date"), ("email", "email"),
                 ("relationship", "for_whom")]
        if values["relationship"] not in (None, "self"):
            steps += [("patient_name", "patient_name"), ("patient_birth_date", "patient_birth_date")]
        stage = next((stage for field, stage in steps if not values.get(field)), "for_whom")
        state["conversation"] = {"stage": f"collect_{stage}", "data": values}
    target.session_state = state


@router.post("/select")
def select_resume(data: SelectData, web_session: str | None = Cookie(None)):
    with SessionLocal.begin() as session:
        lock_demo_writes(session)
        challenge = _challenge(session, data.challenge_id, web_session)
        if not challenge.valid_until or aware(challenge.valid_until) <= utc_now():
            raise APIError(403, "resume_denied", "Verifica tu correo para continuar.")
        channel = challenge.channel
        identifier = challenge.scope.get("phone") or web_session
        replay = challenge.selections.get(data.idempotency_key)
        if replay and replay != [data.kind, data.id, data.expected_version]:
            raise APIError(409, "idempotency_conflict", "La clave ya se usó para otra selección.")
        if data.kind == "draft":
            draft = session.get(Draft, data.id) if data.id in challenge.scope["draft_ids"] else None
            if not draft or draft.email != challenge.email or aware(draft.expires_at) <= utc_now():
                raise APIError(403, "resume_denied", "No se puede retomar ese elemento.")
            target = _target(session, channel, identifier)
            if (replay and draft.identity_id != target.id) or (not replay and draft.version != data.expected_version):
                raise APIError(409, "version_conflict", "El borrador cambió.")
            if not replay:
                if target.person_id and channel == "web":
                    raise APIError(409, "identity_conflict", "Abre una sesión nueva para retomar el borrador.")
                if channel == "whatsapp" and not target.person_id:
                    if session.scalar(select(Person.id).where(Person.phone == identifier).limit(1)):
                        raise APIError(409, "identity_conflict", "Usa otro número simulado para importar el borrador.")
                    person = Person(id=new_id("P"), phone=identifier, is_provisional=True)
                    session.add(person)
                    target.person_id = person.id
                if channel == "whatsapp":
                    person = session.get(Person, target.person_id)
                    if person and person.full_name:
                        raise APIError(409, "identity_conflict", "Usa otro número simulado para importar el borrador.")
                _transfer(session, draft, target)
                if channel == "whatsapp":
                    target.session_state = {**target.session_state, "resume_draft_challenge": challenge.id}
            result = {"draft": draft.data}
        else:
            case = session.get(Case, data.id)
            person = session.get(Person, case.requester_id) if case else None
            if (not case or not person or person.email != challenge.email
                    or case.requester_id != challenge.scope["person_id"] or case.status == "cancelado"):
                raise APIError(403, "resume_denied", "No se puede retomar ese elemento.")
            target = _target(session, channel, identifier)
            if not replay:
                check_version(session, case, data.expected_version)
                if channel == "web":
                    if target.person_id not in (None, case.requester_id):
                        raise APIError(409, "identity_conflict", "Abre una sesión nueva para retomar el trámite.")
                    if target.person_id is None:
                        target.person_id = case.requester_id
                        append_event(session, event_type="identidad_vinculada", channel=channel,
                                     actor_id=identifier, person_id=case.requester_id)
                    session.add(Verification(
                        id=new_id("V"), person_id=case.requester_id, channel=channel,
                        identifier=identifier, method="email_otp", status="succeeded",
                        valid_until=challenge.valid_until,
                    ))
                    target.session_state = {**(target.session_state or {}), "resume_case_id": case.id}
                change_channel(session, case, channel=channel, actor_id=identifier)
                if case.abandoned:
                    case.abandoned = False
                    append_event(session, event_type="tramite_reanudado", channel=channel,
                                 actor_id=identifier, case_id=case.id, person_id=case.requester_id)
                case.version += 1
                target.last_seen_at = utc_now()
                session.flush()
            result = {"case": case_view(session, case)}
        if not replay:
            challenge.selections = {**challenge.selections, data.idempotency_key: [data.kind, data.id, data.expected_version]}
        if channel == "web":
            result["session_identifier"] = web_session
        return result
