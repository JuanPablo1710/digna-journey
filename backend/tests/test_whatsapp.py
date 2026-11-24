import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import count

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import Case, ChannelIdentity, Event, MailboxMessage, Person, Verification
from app.modules.identity.service import aware


WEB_KEY = "demo-web-key"
WHATSAPP_KEY = "demo-whatsapp-key"
sequence = count(1)


def web_interaction(client, session_id, action, data):
    return client.post(
        "/channels/web/interactions",
        headers={"X-Channel-Key": WEB_KEY},
        json={
            "identifier": session_id,
            "identifier_type": "session",
            "idempotency_key": f"web-wa-{next(sequence)}",
            "kind": "action",
            "action": action,
            "content": None,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def whatsapp(client, phone, *, content=None, action=None, data=None, key=None):
    return client.post(
        "/channels/whatsapp/interactions",
        headers={"X-Channel-Key": WHATSAPP_KEY},
        json={
            "identifier": phone,
            "identifier_type": "phone",
            "idempotency_key": key or f"wa-{next(sequence)}",
            "kind": "action" if action else "message",
            "action": action,
            "content": content,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def ana_web_case(client, phone="2221234567"):
    session_id = f"ana-wa-{next(sequence)}"
    created = web_interaction(
        client,
        session_id,
        "preregister",
        {
            "requester": {
                "full_name": "Ana Demo",
                "birth_date": "1990-05-10",
                "email": "ana.demo@example.com",
                "phone": phone,
            },
            "relationship": "self",
            "study_id": "ST-003",
        },
    )
    assert created.status_code == 200, created.text
    case = created.json()["case"]
    selected = web_interaction(
        client,
        session_id,
        "select_clinic",
        {"case_id": case["id"], "expected_version": case["version"], "clinic_id": "CL-001"},
    )
    assert selected.status_code == 200, selected.text
    return selected.json()["case"]


def latest_code(email):
    with SessionLocal() as session:
        return session.scalar(
            select(MailboxMessage.code)
            .where(MailboxMessage.email == email)
            .order_by(MailboxMessage.created_at.desc())
        )


def complete_unknown_booking(client, phone, email="nuevo@example.com"):
    assert whatsapp(client, phone, content="agendar").status_code == 200
    assert whatsapp(client, phone, content="Persona Nueva").status_code == 200
    assert whatsapp(client, phone, content="02/02/1992").status_code == 200
    assert whatsapp(client, phone, content=email).status_code == 200
    completed = whatsapp(client, phone, action="answer", data={"value": "self"})
    assert completed.status_code == 200, completed.text
    return completed.json()


def test_ana_web_to_whatsapp_verifies_and_selects_slot(client):
    web_case = ana_web_case(client)
    phone = "+522221234567"

    recognized = whatsapp(client, phone, content="hola")
    assert recognized.status_code == 200
    assert recognized.json()["trust_level"] == 1
    assert "fecha de nacimiento" in recognized.text.lower()
    assert "Ultrasonido" not in recognized.text

    dob = whatsapp(client, phone, content="10/05/1990")
    assert dob.status_code == 200, dob.text
    assert dob.json()["trust_level"] == 1
    assert "a***@example.com" in dob.text

    code = latest_code("ana.demo@example.com")
    verified = whatsapp(client, phone, content=code)
    assert verified.status_code == 200, verified.text
    assert verified.json()["trust_level"] == 2
    assert code not in verified.text

    continued = whatsapp(client, phone, action="continue_case")
    slot_reply = continued.json()["messages"][0]["quick_replies"][0]
    assert slot_reply["action"] == "select_slot"
    selected = whatsapp(client, phone, action=slot_reply["action"], data=slot_reply["payload"])
    assert selected.status_code == 200, selected.text
    assert selected.json()["case"]["status"] == "horario_propuesto"
    assert selected.json()["case"]["last_channel"] == "whatsapp"

    with SessionLocal() as session:
        stored = session.get(Case, web_case["id"])
        types = session.scalars(
            select(Event.type).where(Event.case_id == stored.id).order_by(Event.seq)
        ).all()
        changes = session.scalars(
            select(Event).where(Event.case_id == stored.id, Event.type == "canal_cambiado")
        ).all()
    assert stored.status == "horario_propuesto"
    assert "horario_propuesto" in types
    assert len(changes) == 1
    assert changes[0].payload == {"from": "web", "to": "whatsapp"}


def test_interruption_resume_asks_exact_pending_field(client):
    phone = "+522225550001"
    whatsapp(client, phone, content="agendar")
    named = whatsapp(client, phone, content="Interrupción Demo")
    assert "DD/MM/AAAA" in named.text

    resumed = whatsapp(client, phone, content="hola")
    assert resumed.status_code == 200
    assert "fecha" in resumed.text.lower()
    assert "nombre completo" not in resumed.text.lower()
    with SessionLocal() as session:
        identity = session.scalar(select(ChannelIdentity).where(ChannelIdentity.identifier == phone))
        assert identity.session_state["conversation"]["stage"] == "collect_birth_date"


def test_partial_info_prompts_only_what_is_missing(client):
    phone = "+522225550002"
    whatsapp(client, phone, content="agendar")
    whatsapp(client, phone, content="Parcial Demo")
    birth = whatsapp(client, phone, content="04/03/1991")
    assert "correo" in birth.text.lower()
    assert "nombre" not in birth.text.lower()

    resumed = whatsapp(client, phone, content="dato-invalido")
    assert "correo" in resumed.text.lower()
    assert "fecha" not in resumed.text.lower()


def test_unknown_number_exposes_no_existing_data(client):
    response = whatsapp(client, "+522225550003", content="hola")
    assert response.status_code == 200
    assert response.json()["trust_level"] == 0
    assert response.json()["case"] is None
    assert all(name not in response.text for name in ("Luis", "Marta", "Pablo"))


def test_shared_phone_requires_birth_date_without_guessing(client):
    response = whatsapp(client, "+522229999999", content="hola")
    assert response.status_code == 200
    assert response.json()["trust_level"] == 0
    assert response.json()["case"] is None
    assert "más de una persona" in response.text
    assert "Marta" not in response.text and "Pablo" not in response.text


def test_duplicate_idempotency_key_changes_nothing(client):
    phone = "+522225550004"
    key = "whatsapp-same-key"
    first = whatsapp(client, phone, content="hola", key=key)
    with SessionLocal() as session:
        event_count = session.scalar(select(func.count()).select_from(Event))
        person_count = session.scalar(select(func.count()).select_from(Person))
    duplicate = whatsapp(client, phone, content="hola", key=key)
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == event_count
        assert session.scalar(select(func.count()).select_from(Person)) == person_count
    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()


def test_whatsapp_version_conflict_returns_current_case(client):
    body = complete_unknown_booking(client, "+522225550007")
    case = body["case"]
    first_study = body["messages"][0]["quick_replies"][0]
    selected = whatsapp(
        client,
        "+522225550007",
        action=first_study["action"],
        data=first_study["payload"],
    )
    assert selected.status_code == 200

    stale = whatsapp(
        client,
        "+522225550007",
        action="select_study",
        data={"case_id": case["id"], "expected_version": 1, "study_id": "ST-002"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "version_conflict"
    assert stale.json()["case"]["version"] == 2


def test_otp_and_birth_date_never_appear_in_event_payloads_or_replies(client):
    ana_web_case(client)
    phone = "+522221234567"
    whatsapp(client, phone, content="hola")
    birth = "10/05/1990"
    whatsapp(client, phone, content=birth)
    code = latest_code("ana.demo@example.com")
    response = whatsapp(client, phone, content=code)
    assert code not in response.text
    with SessionLocal() as session:
        received = session.scalars(
            select(Event).where(Event.channel == "whatsapp", Event.type == "mensaje_recibido")
        ).all()
        sent = session.scalars(
            select(Event).where(Event.channel == "whatsapp", Event.type == "mensaje_enviado")
        ).all()
    serialized = json.dumps([event.payload for event in received + sent], ensure_ascii=False)
    assert code not in serialized
    assert birth not in serialized
    assert any(event.payload.get("type") == "dob_enviada" for event in received)
    assert any(event.payload.get("type") == "otp_enviado" for event in received)


def test_unknown_origin_access_is_limited_to_its_created_cases(client):
    phone = "+522225550005"
    body = complete_unknown_booking(client, phone, email="luis.demo@example.com")
    assert body["trust_level"] == 2
    created_id = body["case"]["id"]
    with SessionLocal() as session:
        identity = session.scalar(select(ChannelIdentity).where(ChannelIdentity.identifier == phone))
        requester = session.get(Person, identity.person_id)
        luis = session.scalar(select(Person).where(Person.email == "luis.demo@example.com", Person.phone == "+522221111111"))
        luis_cases = session.scalars(select(Case).where(Case.requester_id == luis.id)).all()
        assert requester.id != luis.id
        assert requester.phone == phone
        assert identity.session_state["origin_case_ids"] == [created_id]
        assert all(case.id != created_id for case in luis_cases)
    assert "C-1001" not in json.dumps(body)


def test_unknown_origin_expires_and_requires_dob_and_otp(client):
    phone = "+522225550006"
    created = complete_unknown_booking(client, phone)
    assert created["trust_level"] == 2
    with SessionLocal() as session:
        identity = session.scalar(select(ChannelIdentity).where(ChannelIdentity.identifier == phone))
        identity.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        session.commit()

    expired = whatsapp(client, phone, content="hola")
    assert expired.status_code == 200
    assert expired.json()["trust_level"] == 1
    assert expired.json()["case"]["pending"] is True
    assert "fecha de nacimiento" in expired.text.lower()
    with SessionLocal() as session:
        identity = session.scalar(select(ChannelIdentity).where(ChannelIdentity.identifier == phone))
        assert identity.session_state["origin_case_ids"] == []


def test_prelinked_number_never_receives_origin_trust(client):
    with SessionLocal() as session:
        cases_before = session.scalar(select(func.count()).select_from(Case))
    response = whatsapp(client, "+522221111111", content="agendar")
    assert response.status_code == 200
    assert response.json()["trust_level"] == 1
    assert "fecha de nacimiento" in response.text.lower()
    with SessionLocal() as session:
        identity = session.scalar(select(ChannelIdentity).where(ChannelIdentity.identifier == "+522221111111"))
        assert identity.session_state.get("started_unknown") is not True
        assert session.scalar(select(func.count()).select_from(Case)) == cases_before


def test_reset_conversation_clears_state_and_expires_verification(client):
    ana_web_case(client)
    phone = "+522221234567"
    whatsapp(client, phone, content="hola")
    whatsapp(client, phone, content="10/05/1990")
    code = latest_code("ana.demo@example.com")
    whatsapp(client, phone, content=code)
    with SessionLocal() as session:
        events_before = session.scalar(select(func.count()).select_from(Event))
        cases_before = session.scalar(select(func.count()).select_from(Case))
        people_before = session.scalar(select(func.count()).select_from(Person))

    reset = whatsapp(client, phone, action="reset_conversation")
    assert reset.status_code == 200
    assert "Cotizar estudio" in reset.text
    with SessionLocal() as session:
        identity = session.scalar(select(ChannelIdentity).where(ChannelIdentity.identifier == phone))
        valid = session.scalars(
            select(Verification).where(
                Verification.channel == "whatsapp",
                Verification.identifier == phone,
                Verification.valid_until.is_not(None),
            )
        ).all()
        assert identity.session_state == {}
        assert all(aware(verification.valid_until) <= datetime.now(timezone.utc) for verification in valid)
        assert session.scalar(select(func.count()).select_from(Event)) == events_before
        assert session.scalar(select(func.count()).select_from(Case)) == cases_before
        assert session.scalar(select(func.count()).select_from(Person)) == people_before


def test_reset_conversation_is_forbidden_outside_demo_mode(client, monkeypatch):
    import app.modules.adapters.whatsapp as adapter

    monkeypatch.setattr(adapter, "settings", replace(settings, demo_mode=False))
    response = whatsapp(client, "+522221111111", action="reset_conversation")
    assert response.status_code == 403
    assert response.json()["error"] == "demo_mode_required"
