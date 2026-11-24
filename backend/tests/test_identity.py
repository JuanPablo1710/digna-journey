from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.errors import APIError
from app.models import Case, ChannelIdentity, Event, MailboxMessage, Person, Verification
from app.modules.identity.service import ensure_complete_person, recognize_identity, verify_agent_assisted
from app.security import mask_email, mask_name, mask_phone


WEB_KEY = "demo-web-key"


def web_interaction(client, session_id: str, action: str, data=None, key=None):
    return client.post(
        "/channels/web/interactions",
        headers={"X-Channel-Key": WEB_KEY},
        json={
            "identifier": session_id,
            "identifier_type": "session",
            "idempotency_key": key or f"{session_id}-{action}-{datetime.now(timezone.utc).timestamp()}",
            "kind": "action",
            "action": action,
            "content": None,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def establish_web_session(client, session_id: str) -> None:
    response = web_interaction(client, session_id, "start_quote")
    assert response.status_code == 200
    assert client.cookies.get("web_session") == session_id


def request_otp(client, session_id="otp-web-session", email="luis.demo@example.com"):
    establish_web_session(client, session_id)
    response = client.post(
        "/identity/verify/request",
        json={"channel": "web", "identifier": email, "method": "email_otp"},
    )
    assert response.status_code == 200, response.text
    mailbox = client.get("/demo/mailbox", params={"email": email})
    assert mailbox.status_code == 200
    code = mailbox.json()["messages"][0]["code"]
    return response, code


def test_unknown_phone_and_email_expose_no_data_and_phone_is_reused(client):
    with SessionLocal() as session:
        before = session.scalar(select(func.count()).select_from(Person))
        first = recognize_identity(
            session,
            channel="whatsapp",
            identifier="222 555 0101",
            identifier_type="phone",
        )
        session.commit()
    with SessionLocal() as session:
        second = recognize_identity(
            session,
            channel="whatsapp",
            identifier="+522225550101",
            identifier_type="phone",
        )
        after = session.scalar(select(func.count()).select_from(Person))
        provisional = session.scalar(select(Person).where(Person.phone == "+522225550101"))
        session.commit()

    assert first == {"state": "unknown", "trust_level": 0, "identifier": "+522225550101"}
    assert second == first
    assert after == before + 1
    assert provisional.full_name is None
    assert provisional.birth_date is None

    unknown_email = client.post(
        "/identity/verify/request",
        json={"channel": "app", "identifier": "nadie@example.com", "method": "email_otp"},
    )
    assert unknown_email.status_code == 404
    assert "Luis" not in unknown_email.text
    assert "Marta" not in unknown_email.text


def test_shared_phone_is_ambiguous_and_dob_does_not_guess(client):
    with SessionLocal() as session:
        result = recognize_identity(
            session,
            channel="whatsapp",
            identifier="+522229999999",
            identifier_type="phone",
        )
    assert result["state"] == "ambiguous"
    assert result["trust_level"] == 0
    assert "person" not in result

    wrong = client.post(
        "/identity/verify/request",
        json={
            "channel": "whatsapp",
            "identifier": "+522229999999",
            "method": "dob_check",
            "birth_date": "2000-01-01",
        },
    )
    assert wrong.status_code == 409
    assert wrong.json()["error"] == "ambiguous"
    assert "Marta" not in wrong.text and "Pablo" not in wrong.text

    matched = client.post(
        "/identity/verify/request",
        json={
            "channel": "whatsapp",
            "identifier": "+522229999999",
            "method": "dob_check",
            "birth_date": "1982-08-20",
        },
    )
    assert matched.status_code == 200
    assert matched.json()["trust_level"] == 1
    assert matched.json()["next_method"] == "email_otp"
    assert "Marta" not in matched.text


def test_correct_otp_reaches_level_two_and_rotates_web_session(client):
    _, code = request_otp(client, session_id="old-web-session")
    old_cookie = client.cookies.get("web_session")
    confirmed = client.post(
        "/identity/verify/confirm",
        json={"channel": "web", "identifier": "luis.demo@example.com", "code": code},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    new_session = body["session_identifier"]
    assert body["trust_level"] == 2
    assert body["access_token"]
    assert new_session != old_cookie
    assert client.cookies.get("web_session") == new_session
    assert client.get("/cases/C-1001").json()["case"]["id"] == "C-1001"

    client.cookies.clear()
    client.cookies.set("web_session", old_cookie)
    old_access = client.get("/cases/C-1001")
    assert old_access.status_code == 403
    assert "clinic_id" not in old_access.text


def test_incorrect_otp_counts_attempts_third_failure_locks_and_lock_expires(client):
    _, code = request_otp(client, session_id="lock-session")
    wrong = "000000" if code != "000000" else "111111"
    first = client.post(
        "/identity/verify/confirm",
        json={"channel": "web", "identifier": "luis.demo@example.com", "code": wrong},
    )
    second = client.post(
        "/identity/verify/confirm",
        json={"channel": "web", "identifier": "luis.demo@example.com", "code": wrong},
    )
    third = client.post(
        "/identity/verify/confirm",
        json={"channel": "web", "identifier": "luis.demo@example.com", "code": wrong},
    )
    assert first.status_code == 422 and first.json()["attempts_remaining"] == 2
    assert second.status_code == 422 and second.json()["attempts_remaining"] == 1
    assert third.status_code == 429 and third.json()["attempts_remaining"] == 0
    assert third.json()["error"] == "temporarily_locked"

    with SessionLocal() as session:
        verification = session.scalar(
            select(Verification)
            .where(Verification.identifier == "luis.demo@example.com", Verification.method == "email_otp")
            .order_by(Verification.created_at.desc())
        )
        locked_event = session.scalar(
            select(Event)
            .where(Event.type == "verificacion_fallida")
            .order_by(Event.seq.desc())
        )
        assert verification.status == "locked"
        assert verification.attempts == 3
        assert locked_event.payload["locked"] is True
        verification.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    requested_again = client.post(
        "/identity/verify/request",
        json={"channel": "web", "identifier": "luis.demo@example.com", "method": "email_otp"},
    )
    assert requested_again.status_code == 200


def test_expired_otp_is_rejected_and_code_is_never_stored_in_clear(client):
    _, code = request_otp(client, session_id="expired-otp-session")
    with SessionLocal() as session:
        verification = session.scalar(
            select(Verification)
            .where(Verification.identifier == "luis.demo@example.com", Verification.method == "email_otp")
            .order_by(Verification.created_at.desc())
        )
        assert verification.code_hash != code
        assert code not in verification.code_hash
        verification.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    response = client.post(
        "/identity/verify/confirm",
        json={"channel": "web", "identifier": "luis.demo@example.com", "code": code},
    )
    assert response.status_code == 410
    assert response.json()["error"] == "otp_expired"
    with SessionLocal() as session:
        payloads = [str(event.payload) for event in session.scalars(select(Event)).all()]
    assert all(code not in payload for payload in payloads)


def test_level_one_sees_only_pending_and_timeline_denial_is_audited(client):
    with SessionLocal() as session:
        result = recognize_identity(
            session,
            channel="web",
            identifier="luis.demo@example.com",
            identifier_type="account",
        )
        session.commit()
    assert result["trust_level"] == 1
    client.cookies.set("web_session", "luis.demo@example.com")

    case_response = client.get("/cases/C-1001")
    assert case_response.status_code == 200
    assert case_response.json()["case"] == {"id": "C-1001", "pending": True}
    assert "clinic_id" not in case_response.text

    timeline = client.get("/cases/C-1001/timeline")
    assert timeline.status_code == 403
    with SessionLocal() as session:
        denied = session.scalar(
            select(Event)
            .where(Event.type == "acceso_denegado", Event.case_id == "C-1001")
            .order_by(Event.seq.desc())
        )
    assert denied is not None
    assert denied.payload["reason"] == "verification_required"


def test_verification_expires_after_thirty_minutes(client):
    _, code = request_otp(client, session_id="expiring-trust-session")
    confirmed = client.post(
        "/identity/verify/confirm",
        json={"channel": "web", "identifier": "luis.demo@example.com", "code": code},
    )
    new_session = confirmed.json()["session_identifier"]
    with SessionLocal() as session:
        verification = session.scalar(
            select(Verification).where(
                Verification.identifier == new_session,
                Verification.status == "succeeded",
            )
        )
        verification.valid_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    response = client.get("/cases/C-1001")
    assert response.status_code == 200
    assert response.json()["trust_level"] == 1
    assert response.json()["case"] == {"id": "C-1001", "pending": True}
    assert client.get("/cases/C-1001/timeline").status_code == 403


def test_recognition_from_another_browser_does_not_grant_access(client):
    establish_web_session(client, "unverified-browser")
    requested = client.post(
        "/identity/verify/request",
        json={"channel": "web", "identifier": "luis.demo@example.com", "method": "email_otp"},
    )
    assert requested.status_code == 200
    denied = client.get("/cases/C-1001")
    assert denied.status_code == 403
    assert "clinic_id" not in denied.text


def test_incomplete_provisional_person_cannot_start_or_confirm_case(client):
    with SessionLocal() as session:
        recognize_identity(
            session,
            channel="web",
            identifier="+522225551212",
            identifier_type="phone",
        )
        provisional = session.scalar(select(Person).where(Person.phone == "+522225551212"))
        with pytest.raises(APIError) as exc_info:
            ensure_complete_person(provisional)
        assert exc_info.value.error == "incomplete_person"
        case = Case(
            id="C-NULLS",
            requester_id=provisional.id,
            patient_id=provisional.id,
            relationship="self",
            study_id="ST-001",
            clinic_id="CL-001",
            slot_id="SL-NULLS",
            steps={"study": True, "patient_data": True, "clinic": True, "slot": True, "confirmed": False},
            status="horario_propuesto",
            abandoned=False,
            current_channel="web",
            last_channel="web",
            version=1,
        )
        session.add(case)
        session.add(
            Event(
                event_id="evt_null_source",
                type="tramite_creado",
                case_id=case.id,
                person_id=provisional.id,
                channel="web",
                actor_role="paciente",
                actor_id="+522225551212",
                payload={},
            )
        )
        session.commit()

    client.cookies.set("web_session", "+522225551212")
    response = web_interaction(
        client,
        "+522225551212",
        "confirm_case",
        {"case_id": "C-NULLS", "expected_version": 1},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "incomplete_person"


def test_masking_tolerates_null_values():
    assert mask_name(None) == "Contacto sin registrar"
    assert mask_email(None) == "Correo sin registrar"
    assert mask_phone(None) == "Teléfono sin registrar"


def test_demo_reset_empties_mailbox(client):
    request_otp(client, session_id="reset-mailbox-session")
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(MailboxMessage)) == 1
    reset = client.post("/demo/reset")
    assert reset.status_code == 200
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(MailboxMessage)) == 0
        assert session.get(Person, "P-1001") is not None


def test_whatsapp_requires_dob_before_email_otp(client):
    denied = client.post(
        "/identity/verify/request",
        json={"channel": "whatsapp", "identifier": "+522229999999", "method": "email_otp"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"] == "dob_check_required"

    dob = client.post(
        "/identity/verify/request",
        json={
            "channel": "whatsapp",
            "identifier": "+522229999999",
            "method": "dob_check",
            "birth_date": "2012-03-15",
        },
    )
    assert dob.status_code == 200
    otp = client.post(
        "/identity/verify/request",
        json={"channel": "whatsapp", "identifier": "+522229999999", "method": "email_otp"},
    )
    assert otp.status_code == 200
    assert otp.json()["masked_email"] == "p***@example.com"


def test_agent_assisted_service_reaches_level_two_without_endpoint(client):
    with SessionLocal() as session:
        result = verify_agent_assisted(
            session,
            person_id="P-1001",
            identifier="2221111111",
            birth_date=datetime.strptime("1985-04-12", "%Y-%m-%d").date(),
        )
        session.commit()
    assert result["trust_level"] == 2
    with SessionLocal() as session:
        verification = session.scalar(
            select(Verification).where(
                Verification.person_id == "P-1001",
                Verification.method == "agent_assisted",
            )
        )
    assert verification is not None
    assert verification.code_hash is None


def test_successful_verification_fuses_only_exact_provisional_duplicates(client):
    with SessionLocal() as session:
        exact = Person(
            id="P-EXACT-DUP",
            full_name="Luis Provisional",
            birth_date=datetime.strptime("1985-04-12", "%Y-%m-%d").date(),
            email="luis.demo@example.com",
            phone="+522221111111",
            is_provisional=True,
        )
        different_phone = Person(
            id="P-NONEXACT-DUP",
            full_name="Otro Provisional",
            birth_date=datetime.strptime("1985-04-12", "%Y-%m-%d").date(),
            email="otro.provisional@example.com",
            phone="+522221111112",
            is_provisional=True,
        )
        session.add_all([exact, different_phone])
        session.add_all(
            [
                ChannelIdentity(
                    id="CI-EXACT-DUP",
                    person_id=exact.id,
                    channel="app",
                    identifier="exact-duplicate",
                    identifier_type="account",
                    session_state={},
                    last_seen_at=datetime.now(timezone.utc),
                ),
                ChannelIdentity(
                    id="CI-NONEXACT-DUP",
                    person_id=different_phone.id,
                    channel="app",
                    identifier="nonexact-duplicate",
                    identifier_type="account",
                    session_state={},
                    last_seen_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.commit()

    _, code = request_otp(client, session_id="fusion-session")
    confirmed = client.post(
        "/identity/verify/confirm",
        json={"channel": "web", "identifier": "luis.demo@example.com", "code": code},
    )
    assert confirmed.status_code == 200
    with SessionLocal() as session:
        exact_identity = session.get(ChannelIdentity, "CI-EXACT-DUP")
        different_identity = session.get(ChannelIdentity, "CI-NONEXACT-DUP")
        fusion_event = session.scalar(select(Event).where(Event.type == "identidad_fusionada"))
    assert exact_identity.person_id == "P-1001"
    assert different_identity.person_id == "P-NONEXACT-DUP"
    assert fusion_event is not None
