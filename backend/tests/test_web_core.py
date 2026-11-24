from datetime import datetime, timedelta, timezone
from itertools import count

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import ChannelIdentity, Event, Person


WEB_KEY = "demo-web-key"
sequence = count(1)


def interaction(client, session_id: str, action: str, data=None, idempotency_key=None):
    number = next(sequence)
    payload = {
        "identifier": session_id,
        "identifier_type": "session",
        "idempotency_key": idempotency_key or f"test-{number}",
        "kind": "action",
        "action": action,
        "content": None,
        "data": data or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return client.post(
        "/channels/web/interactions",
        headers={"X-Channel-Key": WEB_KEY},
        json=payload,
    )


def preregister(client, session_id="web-session-1", study_id="ST-003", relationship="self"):
    data = {
        "requester": {
            "full_name": "Ana Demo",
            "birth_date": "1990-05-10",
            "email": "ANA.DEMO@example.com",
            "phone": "222 123 4567",
        },
        "relationship": relationship,
        "study_id": study_id,
    }
    if relationship != "self":
        data["patient"] = {
            "full_name": "Paciente Demo",
            "birth_date": "2015-02-03",
        }
    response = interaction(client, session_id, "preregister", data)
    assert response.status_code == 200, response.text
    return response.json()


def first_slot(client, clinic_id="CL-001"):
    response = client.get("/catalog/slots", params={"clinic_id": clinic_id})
    assert response.status_code == 200
    return response.json()[0]


def test_idempotency_duplicate_interaction(client):
    created = preregister(client, session_id="idem-session")
    case = created["case"]
    payload = {
        "case_id": case["id"],
        "expected_version": case["version"],
        "clinic_id": "CL-001",
    }
    key = "same-interaction-key"

    first = interaction(client, "idem-session", "select_clinic", payload, key)
    with SessionLocal() as session:
        events_before = session.scalar(select(func.count()).select_from(Event))
    second = interaction(client, "idem-session", "select_clinic", payload, key)
    with SessionLocal() as session:
        events_after = session.scalar(select(func.count()).select_from(Event))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert events_after == events_before
    assert second.json()["case"]["version"] == 2


def test_version_conflict_returns_current_case(client):
    created = preregister(client, session_id="version-session")
    case = created["case"]
    selected = interaction(
        client,
        "version-session",
        "select_clinic",
        {"case_id": case["id"], "expected_version": 1, "clinic_id": "CL-001"},
    )
    assert selected.status_code == 200

    conflict = interaction(
        client,
        "version-session",
        "select_slot",
        {"case_id": case["id"], "expected_version": 1, "slot_id": first_slot(client)["id"]},
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"] == "version_conflict"
    assert conflict.json()["case"]["version"] == 2
    assert conflict.json()["case"]["clinic_id"] == "CL-001"


def test_derived_status_and_required_events(client):
    created = preregister(client, session_id="flow-session", relationship="hijo_a")
    case = created["case"]
    assert case["status"] == "datos_completos"
    assert created["missing_steps"] == ["clinic", "slot", "confirmed"]
    assert case["requester"]["email"] == "ana.demo@example.com"
    assert case["requester"]["phone"] == "+522221234567"
    assert case["patient"]["full_name"] == "Paciente Demo"

    clinic = interaction(
        client,
        "flow-session",
        "select_clinic",
        {"case_id": case["id"], "expected_version": 1, "clinic_id": "CL-001"},
    ).json()
    assert clinic["case"]["status"] == "clinica_elegida"

    slot = interaction(
        client,
        "flow-session",
        "select_slot",
        {"case_id": case["id"], "expected_version": 2, "slot_id": first_slot(client)["id"]},
    ).json()
    assert slot["case"]["status"] == "horario_propuesto"

    confirmed = interaction(
        client,
        "flow-session",
        "confirm_case",
        {"case_id": case["id"], "expected_version": 3},
    ).json()
    assert confirmed["case"]["status"] == "cita_confirmada"
    assert confirmed["missing_steps"] == []

    timeline = client.get(f"/cases/{case['id']}/timeline")
    assert timeline.status_code == 200
    event_types = {event["type"] for event in timeline.json()["events"]}
    assert {
        "contacto_creado",
        "consentimiento_aceptado",
        "canal_iniciado",
        "tramite_creado",
        "estudio_seleccionado",
        "datos_paciente_capturados",
        "clinica_seleccionada",
        "horario_propuesto",
        "cita_confirmada",
    }.issubset(event_types)


def test_status_comes_from_steps_completed_out_of_order(client):
    created = preregister(client, session_id="unordered-session", study_id=None)
    case = created["case"]
    slot = first_slot(client)

    slot_result = interaction(
        client,
        "unordered-session",
        "select_slot",
        {"case_id": case["id"], "expected_version": 1, "slot_id": slot["id"]},
    ).json()
    assert slot_result["case"]["steps"]["clinic"] is False
    assert slot_result["case"]["status"] == "horario_propuesto"

    study_result = interaction(
        client,
        "unordered-session",
        "select_study",
        {"case_id": case["id"], "expected_version": 2, "study_id": "ST-001"},
    ).json()
    assert study_result["case"]["status"] == "horario_propuesto"

    clinic_result = interaction(
        client,
        "unordered-session",
        "select_clinic",
        {"case_id": case["id"], "expected_version": 3, "clinic_id": slot["clinic_id"]},
    ).json()
    assert clinic_result["case"]["status"] == "horario_propuesto"
    assert clinic_result["missing_steps"] == ["confirmed"]

    case_response = client.get(f"/cases/{case['id']}")
    assert case_response.status_code == 200
    assert case_response.json()["case"]["status"] == "horario_propuesto"


def test_catalog_endpoints(client):
    assert len(client.get("/catalog/studies").json()) == 5
    assert len(client.get("/catalog/clinics").json()) == 3
    assert len(client.get("/catalog/slots", params={"clinic_id": "CL-001"}).json()) == 15


def test_only_origin_web_session_can_view_case(client):
    created = preregister(client, session_id="owner-session")
    case_id = created["case"]["id"]
    assert client.get(f"/cases/{case_id}").status_code == 200

    quote = interaction(
        client,
        "different-session",
        "select_study",
        {"study_id": "ST-002"},
    )
    assert quote.status_code == 200
    assert quote.json()["quote"]["id"] == "ST-002"

    denied = client.get(f"/cases/{case_id}")
    assert denied.status_code == 403
    assert denied.json()["error"] == "access_denied"


def test_continue_with_cookie_returns_same_case_idempotently(client):
    created = preregister(client, session_id="resume-session")
    case = created["case"]
    selected = interaction(
        client,
        "resume-session",
        "select_clinic",
        {"case_id": case["id"], "expected_version": 1, "clinic_id": "CL-001"},
    )
    assert selected.status_code == 200
    assert client.cookies.get("web_session") == "resume-session"

    with SessionLocal() as session:
        events_before = session.scalar(
            select(func.count()).select_from(Event).where(
                Event.case_id == case["id"], Event.type == "canal_iniciado"
            )
        )

    key = "resume-idempotency-key"
    first = interaction(client, "resume-session", "continue_case", idempotency_key=key)
    second = interaction(client, "resume-session", "continue_case", idempotency_key=key)

    with SessionLocal() as session:
        events_after = session.scalar(
            select(func.count()).select_from(Event).where(
                Event.case_id == case["id"], Event.type == "canal_iniciado"
            )
        )

    assert first.status_code == 200
    assert first.json()["case"]["id"] == case["id"]
    assert first.json()["case"]["status"] == "clinica_elegida"
    assert first.json()["missing_steps"] == ["slot", "confirmed"]
    assert second.json() == first.json()
    assert events_after == events_before + 1
    assert "web_session=resume-session" in first.headers["set-cookie"]
    assert "HttpOnly" in first.headers["set-cookie"]
    assert "Max-Age=1800" in first.headers["set-cookie"]


def test_continue_without_cookie_starts_over_without_exposing_case(client):
    created = preregister(client, session_id="missing-cookie-session")
    case_id = created["case"]["id"]
    client.cookies.clear()

    response = interaction(client, "missing-cookie-session", "continue_case")

    assert response.status_code == 200
    assert response.json()["case"] is None
    assert response.json()["trust_level"] == 0
    assert response.json()["reset_session"] is True
    assert case_id not in response.text
    assert client.cookies.get("web_session") is None


def test_continue_with_expired_cookie_starts_over_without_exposing_case(client):
    created = preregister(client, session_id="expired-cookie-session")
    case_id = created["case"]["id"]
    with SessionLocal() as session:
        identity = session.scalar(
            select(ChannelIdentity).where(ChannelIdentity.identifier == "expired-cookie-session")
        )
        identity.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        session.commit()

    response = interaction(client, "expired-cookie-session", "continue_case")

    assert response.status_code == 200
    assert response.json()["case"] is None
    assert response.json()["trust_level"] == 0
    assert response.json()["reset_session"] is True
    assert case_id not in response.text
    assert client.cookies.get("web_session") is None


def test_cors_allows_exact_frontend_origin_with_credentials(client):
    response = client.options(
        "/channels/web/interactions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-channel-key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_partial_draft_is_saved_and_recovered(client):
    saved = interaction(
        client,
        "draft-session",
        "save_draft",
        {
            "requester": {"full_name": "Ana", "email": "ana@example.com"},
            "relationship": "self",
            "study_id": "ST-003",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["case"] is None
    assert saved.json()["draft"]["requester"]["full_name"] == "Ana"

    resumed = interaction(client, "draft-session", "continue_case")
    assert resumed.status_code == 200
    assert resumed.json()["case"] is None
    assert resumed.json()["draft"] == saved.json()["draft"]
    assert resumed.json()["reset_session"] is False


def test_preregister_converts_draft_and_clears_it(client):
    data = {
        "requester": {
            "full_name": "Ana Demo",
            "birth_date": "1990-05-10",
            "email": "ana.demo@example.com",
            "phone": "2221234567",
        },
        "relationship": "self",
        "patient": None,
        "study_id": "ST-003",
    }
    saved = interaction(client, "convert-draft-session", "save_draft", data)
    assert saved.status_code == 200

    created = interaction(client, "convert-draft-session", "preregister", data)
    assert created.status_code == 200
    assert created.json()["case"] is not None
    with SessionLocal() as session:
        identity = session.scalar(
            select(ChannelIdentity).where(ChannelIdentity.identifier == "convert-draft-session")
        )
    assert identity.person_id is not None
    assert "draft" not in identity.session_state


def test_draft_creates_no_person_or_event_and_nullable_identity_exposes_no_case(client):
    owner = preregister(client, session_id="case-owner-session")
    owner_case_id = owner["case"]["id"]
    client.cookies.clear()
    with SessionLocal() as session:
        people_before = session.scalar(select(func.count()).select_from(Person))
        events_before = session.scalar(select(func.count()).select_from(Event))

    saved = interaction(
        client,
        "nullable-draft-session",
        "save_draft",
        {"requester": {"full_name": "Nombre incompleto"}},
    )
    assert saved.status_code == 200

    with SessionLocal() as session:
        identity = session.scalar(
            select(ChannelIdentity).where(ChannelIdentity.identifier == "nullable-draft-session")
        )
        people_after = session.scalar(select(func.count()).select_from(Person))
        events_after = session.scalar(select(func.count()).select_from(Event))
    assert identity is not None
    assert identity.person_id is None
    assert people_after == people_before
    assert events_after == events_before

    denied = client.get(f"/cases/{owner_case_id}")
    assert denied.status_code == 403
    assert owner_case_id not in denied.text


def test_expired_draft_is_not_recovered_or_exposed_to_another_session(client):
    saved = interaction(
        client,
        "expiring-draft-session",
        "save_draft",
        {"requester": {"full_name": "Dato privado de borrador"}},
    )
    assert saved.status_code == 200
    with SessionLocal() as session:
        identity = session.scalar(
            select(ChannelIdentity).where(ChannelIdentity.identifier == "expiring-draft-session")
        )
        identity.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        session.commit()

    expired = interaction(client, "expiring-draft-session", "continue_case")
    assert expired.status_code == 200
    assert expired.json()["draft"] is None
    assert expired.json()["case"] is None
    assert "Dato privado" not in expired.text

    other = interaction(client, "different-draft-session", "continue_case")
    assert other.status_code == 200
    assert other.json()["draft"] is None
    assert "Dato privado" not in other.text


def test_cancel_confirmed_case_changes_status_and_emits_event(client):
    created = preregister(client, session_id="cancel-confirmed-session")
    case = created["case"]
    clinic = interaction(
        client,
        "cancel-confirmed-session",
        "select_clinic",
        {"case_id": case["id"], "expected_version": 1, "clinic_id": "CL-001"},
    ).json()["case"]
    slot = interaction(
        client,
        "cancel-confirmed-session",
        "select_slot",
        {"case_id": case["id"], "expected_version": clinic["version"], "slot_id": first_slot(client)["id"]},
    ).json()["case"]
    confirmed = interaction(
        client,
        "cancel-confirmed-session",
        "confirm_case",
        {"case_id": case["id"], "expected_version": slot["version"]},
    ).json()["case"]

    cancelled = interaction(
        client,
        "cancel-confirmed-session",
        "cancel_case",
        {"case_id": case["id"], "expected_version": confirmed["version"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["case"]["status"] == "cancelado"
    assert cancelled.json()["case"]["version"] == confirmed["version"] + 1
    assert cancelled.json()["missing_steps"] == []

    timeline = client.get(f"/cases/{case['id']}/timeline")
    assert timeline.status_code == 200
    assert [event["type"] for event in timeline.json()["events"]].count("tramite_cancelado") == 1


def test_cancel_with_stale_version_returns_409(client):
    created = preregister(client, session_id="stale-cancel-session")
    case = created["case"]
    interaction(
        client,
        "stale-cancel-session",
        "select_clinic",
        {"case_id": case["id"], "expected_version": 1, "clinic_id": "CL-001"},
    )

    response = interaction(
        client,
        "stale-cancel-session",
        "cancel_case",
        {"case_id": case["id"], "expected_version": 1},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "version_conflict"
    with SessionLocal() as session:
        cancelled_events = session.scalar(
            select(func.count()).select_from(Event).where(
                Event.case_id == case["id"], Event.type == "tramite_cancelado"
            )
        )
    assert cancelled_events == 0


def test_cancel_already_cancelled_is_idempotent(client):
    created = preregister(client, session_id="idempotent-cancel-session")
    case = created["case"]
    data = {"case_id": case["id"], "expected_version": 1}
    key = "cancel-case-once"

    first = interaction(client, "idempotent-cancel-session", "cancel_case", data, key)
    duplicate = interaction(client, "idempotent-cancel-session", "cancel_case", data, key)
    second_key = interaction(
        client,
        "idempotent-cancel-session",
        "cancel_case",
        {"case_id": case["id"], "expected_version": 2},
        "cancel-case-again",
    )

    assert first.status_code == 200
    assert duplicate.json() == first.json()
    assert second_key.status_code == 200
    assert second_key.json()["events"] == []
    with SessionLocal() as session:
        cancelled_events = session.scalar(
            select(func.count()).select_from(Event).where(
                Event.case_id == case["id"], Event.type == "tramite_cancelado"
            )
        )
    assert cancelled_events == 1


def test_cancel_draft_discards_it_without_event(client):
    interaction(
        client,
        "discard-draft-session",
        "save_draft",
        {"requester": {"full_name": "Borrador a descartar"}},
    )
    with SessionLocal() as session:
        events_before = session.scalar(select(func.count()).select_from(Event))

    cancelled = interaction(client, "discard-draft-session", "cancel_case", {})
    resumed = interaction(client, "discard-draft-session", "continue_case")
    with SessionLocal() as session:
        events_after = session.scalar(select(func.count()).select_from(Event))

    assert cancelled.status_code == 200
    assert cancelled.json()["draft"] is None
    assert cancelled.json()["events"] == []
    assert resumed.json()["draft"] is None
    assert events_after == events_before

