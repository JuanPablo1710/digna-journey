from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app, create_app
from app.models import Case, Event, User
from app.security import create_patient_token, hash_password
from test_whatsapp import ana_web_case, latest_code, whatsapp


def token(client, username="asesor", password="Asesor#2026"):
    response = client.post("/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def second_agent(client):
    with SessionLocal.begin() as session:
        session.add(User(id="second-agent", username="segundo", role="asesor", password_hash=hash_password("demo123")))
    return token(client, "segundo", "demo123")


def call(client, auth, kind="call_started", phone=None, call_id=None):
    return client.post("/channels/callcenter/interactions", headers={
        **auth, "X-Channel-Key": "demo-callcenter-key",
    }, json={
        "identifier": phone or "hidden", "identifier_type": "phone" if phone else "session",
        "kind": kind, "idempotency_key": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"call_id": call_id} if call_id else {},
    })


def verify(client, auth, person, birth="1985-04-12", call_id=None):
    return client.post("/agent/verify", headers=auth, json={
        "person_id": person, "method": "agent_assisted", "birth_date": birth, "call_id": call_id,
    })


def owner(case_id="C-1001"):
    with SessionLocal() as session:
        return session.get(Case, case_id).requester_id


def test_rbac_matrix(client):
    agent = token(client)
    admin = token(client, "admin", "Admin#2026")
    person = owner()
    patient = {"Authorization": f"Bearer {create_patient_token(person)}"}
    assert client.get("/agent/lookup?email=luis.demo@example.com", headers=agent).status_code == 200
    for headers, result in (({}, 401), (patient, 403), (admin, 403)):
        assert client.get(f"/agent/patients/{person}/context", headers=headers).status_code == result
        assert verify(client, headers, person).status_code == result
        assert client.post("/agent/cases/C-1001/notes", headers=headers, json={"text": "Nota"}).status_code == result
        assert client.patch("/cases/C-1001", headers=headers,
                            json={"expected_version": 1, "fields": {"confirmed": True}}).status_code == result
    assert client.get("/admin/dashboard", headers=agent).status_code == 404


def test_agent_access_requires_verification_and_audits(client):
    auth = token(client)
    other = second_agent(client)
    person = owner()
    path = f"/agent/patients/{person}/context"
    assert client.get(path, headers=auth).status_code == 403
    assert verify(client, auth, person).status_code == 200
    assert client.get(path, headers=other).status_code == 403
    result = client.get(path, headers=auth)
    assert result.status_code == 200
    assert result.json()["cases"][0]["requester"]["full_name"] == "Luis Demo"
    with SessionLocal() as session:
        denied, *_, consulted = session.scalars(select(Event).where(
            Event.type.in_(["acceso_denegado", "contexto_consultado"]),
        ).order_by(Event.seq)).all()
    assert denied.payload["reason"] == "verification_required"
    assert consulted.type == "contexto_consultado" and consulted.actor_role == "asesor"
    assert consulted.person_id == person


def test_hidden_call_is_bound_only_after_verification_and_ends_grant(client):
    auth = token(client)
    other = second_agent(client)
    person = owner()
    opened = call(client, auth).json()
    call_id = opened["call_id"]
    assert opened["trust_level"] == 0
    assert client.get("/agent/lookup?email=luis.demo@example.com", headers=auth).status_code == 200
    with SessionLocal() as session:
        assert session.scalar(select(Event).where(Event.type == "identidad_vinculada")) is None
    assert verify(client, auth, person).status_code == 422
    assert verify(client, other, person, call_id=call_id).status_code == 403
    assert call(client, other, "call_ended", call_id=call_id).status_code == 403
    assert verify(client, auth, person, call_id=call_id).status_code == 200
    assert verify(client, auth, owner("C-1002"), birth="1982-08-20", call_id=call_id).status_code == 409
    path = f"/agent/patients/{person}/context"
    timeline = client.get(path, headers=auth).json()["timeline"]
    assert {"llamada_iniciada", "identidad_vinculada", "canal_cambiado", "contexto_consultado"} <= {
        event["type"] for event in timeline if event["payload"].get("call_id") == call_id
    }
    assert call(client, auth, "call_ended", call_id=call_id).status_code == 200
    assert client.get(path, headers=auth).status_code == 403
    assert verify(client, auth, person, call_id=call_id).status_code == 409


def test_shared_dob_attempts_between_agents_and_whatsapp(client):
    auth = token(client)
    other = second_agent(client)
    person = owner()
    wrong = "1990-01-01"
    assert verify(client, auth, person, wrong).json()["attempts_remaining"] == 2
    assert verify(client, other, person).status_code == 200
    assert verify(client, auth, person, wrong).json()["attempts_remaining"] == 2
    dob = {"channel": "whatsapp", "identifier": "+522221111111", "method": "dob_check", "birth_date": wrong}
    assert client.post("/identity/verify/request", json=dob).json()["attempts_remaining"] == 1
    locked = verify(client, other, person, wrong)
    assert locked.status_code == 429 and locked.json()["retry_after_seconds"] > 0
    assert verify(client, auth, person).status_code == 429
    assert client.post("/identity/verify/request", json={**dob, "birth_date": "1985-04-12"}).status_code == 429
    assert client.post(f"/agent/patients/{person}/unlock", headers=auth).status_code == 200
    assert client.post("/identity/verify/request", json={**dob, "birth_date": "1985-04-12"}).status_code == 200


def test_unlock_route_absent_when_demo_is_disabled():
    production = TestClient(create_app(demo_mode=False))
    assert production.post("/agent/patients/person/unlock").status_code == 404


def test_ana_from_web_through_whatsapp_to_callcenter(client):
    case = ana_web_case(client)
    phone = "+522221234567"
    whatsapp(client, phone, content="hola")
    whatsapp(client, phone, content="10/05/1990")
    code = latest_code("ana.demo@example.com")
    assert whatsapp(client, phone, content=code).json()["trust_level"] == 2
    continued = whatsapp(client, phone, action="continue_case").json()
    reply = continued["messages"][0]["quick_replies"][0]
    assert reply["label"].endswith("09:00")
    slot = whatsapp(client, phone, action=reply["action"], data=reply["payload"]).json()["case"]
    auth = token(client)
    call_id = call(client, auth, phone=phone).json()["call_id"]
    person = owner(case["id"])
    assert verify(client, auth, person, birth="1990-05-10", call_id=call_id).status_code == 200
    path = f"/agent/patients/{person}/context"
    context = client.get(path, headers=auth).json()
    assert context["cases"][0]["slot_id"] == slot["slot_id"]
    notes = client.post(f"/agent/cases/{case['id']}/notes", headers=auth, json={"text": "Solo para el asesor"})
    assert notes.status_code == 201
    confirmed = client.patch(f"/cases/{case['id']}", headers=auth,
                             json={"expected_version": slot["version"], "fields": {"confirmed": True}})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["case"]["status"] == "cita_confirmada"
    timeline = client.get(path, headers=auth).json()["timeline"]
    assert {"web", "whatsapp", "callcenter"} <= {event["channel"] for event in timeline}
    for kind in ("cita_confirmada", "nota_agregada", "contexto_consultado"):
        assert any(event["type"] == kind and event["payload"]["call_id"] == call_id for event in timeline)
    patient = client.get(f"/cases/{case['id']}/timeline")
    assert patient.status_code == 200
    assert "Solo para el asesor" not in patient.text and "nota_agregada" not in patient.text
