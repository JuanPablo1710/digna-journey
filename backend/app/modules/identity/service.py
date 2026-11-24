import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...errors import APIError
from ...models import Case, ChannelIdentity, Event, MailboxMessage, Person, User, Verification
from ...security import create_patient_token, hash_password, mask_email, verify_hash
from ..events import append_event


VERIFICATION_TTL = timedelta(minutes=30)
OTP_TTL = timedelta(minutes=5)
LOCK_TTL = timedelta(minutes=10)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10].upper()}"


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise APIError(422, "invalid_email", "El correo no tiene un formato válido.")
    return normalized


def normalize_phone(value: str) -> str:
    raw = value.strip()
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) == 10:
        return f"+52{digits}"
    if len(digits) == 12 and digits.startswith("52"):
        return f"+{digits}"
    if raw.startswith("+") and 10 <= len(digits) <= 15:
        return f"+{digits}"
    raise APIError(422, "invalid_phone", "El teléfono debe tener formato E.164 o diez dígitos de México.")


def normalize_birth_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    try:
        if "/" in value:
            return datetime.strptime(value, "%d/%m/%Y").date()
        return date.fromisoformat(value)
    except ValueError as exc:
        raise APIError(422, "invalid_birth_date", "La fecha debe usar YYYY-MM-DD o DD/MM/AAAA.") from exc


def ensure_complete_person(person: Person | None) -> None:
    if person is None or not person.full_name or person.birth_date is None:
        raise APIError(
            422,
            "incomplete_person",
            "La persona necesita nombre y fecha de nacimiento antes de continuar.",
        )


def _identity(session: Session, channel: str, identifier: str) -> ChannelIdentity | None:
    return session.scalar(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == channel,
            ChannelIdentity.identifier == identifier,
        )
    )


def _link_identity(
    session: Session,
    *,
    channel: str,
    identifier: str,
    identifier_type: str,
    person: Person,
    actor_id: str,
) -> ChannelIdentity:
    identity = _identity(session, channel, identifier)
    linked = identity is None or identity.person_id != person.id
    if identity is None:
        identity = ChannelIdentity(
            id=new_id("CI"),
            person_id=person.id,
            channel=channel,
            identifier=identifier,
            identifier_type=identifier_type,
            session_state={},
            last_seen_at=utc_now(),
        )
        session.add(identity)
    elif identity.person_id in {None, person.id}:
        identity.person_id = person.id
        identity.last_seen_at = utc_now()
    else:
        raise APIError(409, "identity_conflict", "El identificador ya está ligado a otra persona.")
    if linked:
        append_event(
            session,
            event_type="identidad_vinculada",
            channel=channel,
            actor_id=actor_id,
            person_id=person.id,
            payload={"identifier_type": identifier_type},
        )
    return identity


def recognize_identity(
    session: Session,
    *,
    channel: str,
    identifier: str,
    identifier_type: str,
    birth_date: date | str | None = None,
) -> dict[str, Any]:
    if identifier_type == "phone":
        normalized = normalize_phone(identifier)
    elif identifier_type == "account":
        normalized = normalize_email(identifier)
    else:
        normalized = identifier.strip()

    existing = _identity(session, channel, normalized)
    if existing is not None:
        person = session.get(Person, existing.person_id) if existing.person_id else None
        if person is None or (person.is_provisional and not person.full_name):
            return {"state": "unknown", "trust_level": 0, "identifier": normalized}
        return {"state": "recognized", "trust_level": 1, "identifier": normalized, "pending": True}

    field = Person.phone if identifier_type == "phone" else Person.email
    matches = session.scalars(select(Person).where(field == normalized)).all()
    if len(matches) > 1:
        if birth_date is None:
            return {"state": "ambiguous", "trust_level": 0, "identifier": normalized}
        normalized_birth = normalize_birth_date(birth_date)
        matches = [person for person in matches if person.birth_date == normalized_birth]
        if len(matches) != 1:
            return {"state": "ambiguous", "trust_level": 0, "identifier": normalized}

    if len(matches) == 1:
        person = matches[0]
        _link_identity(
            session,
            channel=channel,
            identifier=normalized,
            identifier_type=identifier_type,
            person=person,
            actor_id=normalized,
        )
        return {"state": "recognized", "trust_level": 1, "identifier": normalized, "pending": True}

    provisional = Person(
        id=new_id("P"),
        full_name=None,
        birth_date=None,
        email=normalized if identifier_type == "account" else None,
        phone=normalized if identifier_type == "phone" else None,
        is_provisional=True,
    )
    session.add(provisional)
    session.flush()
    _link_identity(
        session,
        channel=channel,
        identifier=normalized,
        identifier_type=identifier_type,
        person=provisional,
        actor_id=normalized,
    )
    return {"state": "unknown", "trust_level": 0, "identifier": normalized}


def trust_level(
    session: Session,
    *,
    channel: str,
    identifier: str | None,
    case: Case | None = None,
) -> int:
    if not identifier:
        return 0
    identity = _identity(session, channel, identifier)
    if identity is None or identity.person_id is None:
        return 0
    if case is not None and identity.person_id != case.requester_id:
        return 0

    now = utc_now()
    valid_verification = session.scalar(
        select(Verification.id).where(
            Verification.person_id == identity.person_id,
            Verification.channel == channel,
            Verification.identifier == identifier,
            Verification.status == "succeeded",
            Verification.valid_until.is_not(None),
            Verification.valid_until > now,
        )
    )
    if valid_verification is not None:
        return 2

    if channel == "web" and case is not None and now - aware(identity.last_seen_at) <= VERIFICATION_TTL:
        source_event = session.scalar(
            select(Event.seq).where(
                Event.case_id == case.id,
                Event.type == "tramite_creado",
                Event.channel == "web",
                Event.actor_id == identifier,
            )
        )
        if source_event is not None:
            return 2
    return 1


def _person_for_email(session: Session, email: str) -> Person | None:
    matches = session.scalars(select(Person).where(Person.email == email)).all()
    if not matches:
        return None
    phones = {person.phone for person in matches if person.phone}
    if len(phones) > 1:
        raise APIError(409, "ambiguous", "El identificador coincide con más de una persona.")
    return sorted(matches, key=lambda person: (person.is_provisional, person.id))[0]


def _latest_dob_verification(session: Session, channel: str, identifier: str) -> Verification | None:
    return session.scalar(
        select(Verification)
        .where(
            Verification.channel == channel,
            Verification.identifier == identifier,
            Verification.method == "dob_check",
            Verification.status == "succeeded",
            Verification.valid_until.is_not(None),
            Verification.valid_until > utc_now(),
        )
        .order_by(Verification.created_at.desc())
    )


def request_verification(
    session: Session,
    *,
    channel: str,
    identifier: str,
    method: str,
    birth_date: date | None = None,
) -> dict[str, Any]:
    if method == "dob_check":
        phone = normalize_phone(identifier)
        if birth_date is None:
            raise APIError(422, "birth_date_required", "La fecha de nacimiento es obligatoria.")
        matches = session.scalars(select(Person).where(Person.phone == phone)).all()
        if not matches:
            return {"_error": (404, "unknown_identifier", "No encontramos datos para ese teléfono.", {})}
        matched = [person for person in matches if person.birth_date == birth_date]
        if len(matched) != 1:
            append_event(
                session,
                event_type="verificacion_fallida",
                channel=channel,
                actor_id=phone,
                person_id=matches[0].id if len(matches) == 1 else None,
                payload={"method": "dob_check", "reason": "mismatch", "locked": False},
            )
            code = "ambiguous" if len(matches) > 1 else "birth_date_mismatch"
            message = "La fecha no permite identificar a una sola persona." if len(matches) > 1 else "La fecha de nacimiento no coincide."
            return {"_error": (409 if len(matches) > 1 else 422, code, message, {})}
        person = matched[0]
        verification = Verification(
            id=new_id("V"),
            person_id=person.id,
            channel=channel,
            identifier=phone,
            method="dob_check",
            code_hash=None,
            status="succeeded",
            attempts=0,
            expires_at=None,
            valid_until=utc_now() + VERIFICATION_TTL,
        )
        session.add(verification)
        _link_identity(
            session,
            channel=channel,
            identifier=phone,
            identifier_type="phone",
            person=person,
            actor_id=phone,
        )
        append_event(
            session,
            event_type="verificacion_exitosa",
            channel=channel,
            actor_id=phone,
            person_id=person.id,
            payload={"method": "dob_check"},
        )
        return {
            "status": "succeeded",
            "trust_level": 1,
            "next_method": "email_otp",
            "masked_email": mask_email(person.email),
        }

    if method != "email_otp":
        raise APIError(422, "unsupported_method", "El método de verificación no está disponible.")

    if channel == "whatsapp":
        normalized_identifier = normalize_phone(identifier)
        dob_verification = _latest_dob_verification(session, channel, normalized_identifier)
        if dob_verification is None:
            raise APIError(403, "dob_check_required", "Primero valida la fecha de nacimiento.")
        person = session.get(Person, dob_verification.person_id)
    else:
        normalized_identifier = normalize_email(identifier)
        person = _person_for_email(session, normalized_identifier)
    if person is None or not person.email:
        raise APIError(404, "unknown_identifier", "No encontramos datos para ese identificador.")

    locked = session.scalar(
        select(Verification)
        .where(
            Verification.person_id == person.id,
            Verification.channel == channel,
            Verification.identifier == normalized_identifier,
            Verification.method == "email_otp",
            Verification.status == "locked",
        )
        .order_by(Verification.created_at.desc())
    )
    if locked is not None and locked.expires_at and aware(locked.expires_at) > utc_now():
        raise APIError(
            429,
            "temporarily_locked",
            "La verificación está bloqueada temporalmente.",
            {"locked_until": aware(locked.expires_at).isoformat().replace("+00:00", "Z")},
        )
    if locked is not None:
        locked.status = "expired"

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = utc_now() + OTP_TTL
    verification = Verification(
        id=new_id("V"),
        person_id=person.id,
        channel=channel,
        identifier=normalized_identifier,
        method="email_otp",
        code_hash=hash_password(code),
        status="pending",
        attempts=0,
        expires_at=expires_at,
        valid_until=None,
    )
    session.add(verification)
    session.add(
        MailboxMessage(
            id=f"mail_{uuid4().hex[:12]}",
            email=person.email,
            subject="Tu código de verificación (demo)",
            body=f"Tu código de verificación es {code}.",
            code=code,
        )
    )
    append_event(
        session,
        event_type="verificacion_solicitada",
        channel=channel,
        actor_id=normalized_identifier,
        person_id=person.id,
        payload={"method": "email_otp", "masked_email": mask_email(person.email)},
    )
    return {
        "status": "pending",
        "trust_level": 1,
        "masked_email": mask_email(person.email),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }


def _merge_exact_provisionals(
    session: Session,
    person: Person,
    *,
    channel: str,
    actor_id: str,
) -> None:
    if not person.phone or not person.email:
        return
    duplicates = session.scalars(
        select(Person).where(
            Person.id != person.id,
            Person.is_provisional.is_(True),
            Person.phone == person.phone,
            Person.email == person.email,
        )
    ).all()
    if not duplicates:
        return
    duplicate_ids = {duplicate.id for duplicate in duplicates}
    for identity in session.scalars(select(ChannelIdentity).where(ChannelIdentity.person_id.in_(duplicate_ids))):
        identity.person_id = person.id
    for case in session.scalars(
        select(Case).where((Case.requester_id.in_(duplicate_ids)) | (Case.patient_id.in_(duplicate_ids)))
    ):
        if case.requester_id in duplicate_ids:
            case.requester_id = person.id
        if case.patient_id in duplicate_ids:
            case.patient_id = person.id
    for verification in session.scalars(select(Verification).where(Verification.person_id.in_(duplicate_ids))):
        verification.person_id = person.id
    for user in session.scalars(select(User).where(User.person_id.in_(duplicate_ids))):
        user.person_id = person.id
    append_event(
        session,
        event_type="identidad_fusionada",
        channel=channel,
        actor_id=actor_id,
        person_id=person.id,
        payload={"merged_count": len(duplicates)},
    )


def confirm_verification(
    session: Session,
    *,
    channel: str,
    identifier: str,
    code: str,
    web_session: str | None = None,
) -> dict[str, Any]:
    normalized_identifier = normalize_email(identifier) if "@" in identifier else normalize_phone(identifier)
    verification = session.scalar(
        select(Verification)
        .where(
            Verification.channel == channel,
            Verification.identifier == normalized_identifier,
            Verification.method == "email_otp",
            Verification.status.in_(("pending", "locked")),
        )
        .order_by(Verification.created_at.desc())
    )
    if verification is None:
        raise APIError(404, "verification_not_found", "No hay una verificación pendiente.")
    now = utc_now()
    if verification.status == "locked":
        if verification.expires_at and aware(verification.expires_at) > now:
            raise APIError(
                429,
                "temporarily_locked",
                "La verificación está bloqueada temporalmente.",
                {"locked_until": aware(verification.expires_at).isoformat().replace("+00:00", "Z")},
            )
        verification.status = "expired"
        return {"_error": (410, "lock_expired", "El bloqueo terminó; solicita un código nuevo.", {})}
    if verification.expires_at is None or aware(verification.expires_at) <= now:
        verification.status = "expired"
        append_event(
            session,
            event_type="verificacion_fallida",
            channel=channel,
            actor_id=normalized_identifier,
            person_id=verification.person_id,
            payload={"method": "email_otp", "reason": "expired", "locked": False},
        )
        return {"_error": (410, "otp_expired", "El código expiró; solicita uno nuevo.", {})}

    if not verification.code_hash or not verify_hash(code, verification.code_hash):
        verification.attempts += 1
        remaining = max(0, 3 - verification.attempts)
        locked = verification.attempts >= 3
        if locked:
            verification.status = "locked"
            verification.expires_at = now + LOCK_TTL
        append_event(
            session,
            event_type="verificacion_fallida",
            channel=channel,
            actor_id=normalized_identifier,
            person_id=verification.person_id,
            payload={"method": "email_otp", "locked": locked, "attempts_remaining": remaining},
        )
        extra: dict[str, Any] = {"attempts_remaining": remaining}
        if locked:
            extra["locked_until"] = aware(verification.expires_at).isoformat().replace("+00:00", "Z")
        return {
            "_error": (
                429 if locked else 422,
                "temporarily_locked" if locked else "incorrect_code",
                "La verificación está bloqueada temporalmente." if locked else "El código es incorrecto.",
                extra,
            )
        }

    person = session.get(Person, verification.person_id)
    verification.status = "succeeded"
    verification.valid_until = now + VERIFICATION_TTL
    if person.full_name and person.birth_date:
        person.is_provisional = False
    _merge_exact_provisionals(session, person, channel=channel, actor_id=normalized_identifier)

    result_identifier = normalized_identifier
    if channel == "web":
        if not web_session:
            raise APIError(403, "web_session_required", "La sesión web es obligatoria.")
        previous = _identity(session, "web", web_session)
        new_session = f"web-{uuid4()}"
        if previous is not None:
            previous.person_id = None
            previous.session_state = {"invalidated": True}
            previous.last_seen_at = now - VERIFICATION_TTL - timedelta(seconds=1)
        _link_identity(
            session,
            channel="web",
            identifier=new_session,
            identifier_type="session",
            person=person,
            actor_id=new_session,
        )
        session.add(
            Verification(
                id=new_id("V"),
                person_id=person.id,
                channel="web",
                identifier=new_session,
                method="email_otp",
                code_hash=None,
                status="succeeded",
                attempts=0,
                expires_at=None,
                valid_until=verification.valid_until,
            )
        )
        result_identifier = new_session
    else:
        identifier_type = "phone" if channel == "whatsapp" else "account"
        _link_identity(
            session,
            channel=channel,
            identifier=normalized_identifier,
            identifier_type=identifier_type,
            person=person,
            actor_id=normalized_identifier,
        )

    append_event(
        session,
        event_type="verificacion_exitosa",
        channel=channel,
        actor_id=result_identifier,
        person_id=person.id,
        payload={"method": "email_otp"},
    )
    return {
        "trust_level": 2,
        "valid_until": aware(verification.valid_until).isoformat().replace("+00:00", "Z"),
        "access_token": create_patient_token(person.id),
        "_new_session": result_identifier if channel == "web" else None,
    }


def verify_agent_assisted(
    session: Session,
    *,
    person_id: str,
    identifier: str,
    birth_date: date,
) -> dict[str, Any]:
    person = session.get(Person, person_id)
    if person is None or person.birth_date != birth_date:
        raise APIError(422, "birth_date_mismatch", "La fecha de nacimiento no coincide.")
    normalized = normalize_phone(identifier)
    valid_until = utc_now() + VERIFICATION_TTL
    session.add(
        Verification(
            id=new_id("V"),
            person_id=person.id,
            channel="callcenter",
            identifier=normalized,
            method="agent_assisted",
            code_hash=None,
            status="succeeded",
            attempts=0,
            valid_until=valid_until,
        )
    )
    _link_identity(
        session,
        channel="callcenter",
        identifier=normalized,
        identifier_type="phone",
        person=person,
        actor_id=normalized,
    )
    append_event(
        session,
        event_type="verificacion_exitosa",
        channel="callcenter",
        actor_id=normalized,
        actor_role="asesor",
        person_id=person.id,
        payload={"method": "agent_assisted"},
    )
    return {"trust_level": 2, "valid_until": valid_until.isoformat().replace("+00:00", "Z")}
