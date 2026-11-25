from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Event, Person, Verification
from app.security import create_patient_token
from test_agent import call, owner, token, verify
from test_whatsapp import ana_web_case, latest_code, whatsapp


APP_KEY = {"X-Channel-Key": "demo-app-key"}


def login_app(client, email):
    body = {"channel": "app", "identifier": email}
    requested = client.post("/identity/verify/request", headers=APP_KEY, json={**body, "method": "email_otp"})
    assert requested.status_code == 200, requested.text
    confirmed = client.post("/identity/verify/confirm", headers=APP_KEY, json={**body, "code": latest_code(email)})
    assert confirmed.status_code == 200, confirmed.text
    return {**APP_KEY, "Authorization": f"Bearer {confirmed.json()['access_token']}"}


def open_case(client, auth, item, email, key=None):
    return client.post("/channels/app/interactions", headers=auth, json={
        "identifier": email, "identifier_type": "account", "kind": "action", "action": "continue_case",
        "idempotency_key": key or str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {"case_id": item["id"], "expected_version": item["version"]},
    })


def test_ana_full_flow(client):
    assert client.post("/demo/reset").status_code == 200
    email, phone = "ana.demo@example.com", "+522220000001"
    with SessionLocal() as session:
        assert session.scalar(select(Person).where(Person.email == email)) is None
    web = ana_web_case(client, phone=phone)
    assert web["status"] == "clinica_elegida"
    person_id = owner(web["id"])

    assert whatsapp(client, phone, content="hola").json()["trust_level"] == 1
    whatsapp(client, phone, content="10/05/1990")
    assert whatsapp(client, phone, content=latest_code(email)).json()["trust_level"] == 2
    continued = whatsapp(client, phone, action="continue_case").json()
    slot = continued["messages"][0]["quick_replies"][0]
    scheduled = whatsapp(client, phone, action=slot["action"], data=slot["payload"]).json()["case"]
    assert scheduled["id"] == web["id"] and scheduled["status"] == "horario_propuesto"

    advisor = token(client)
    call_id = call(client, advisor, phone=phone).json()["call_id"]
    assert verify(client, advisor, person_id, birth="1990-05-10", call_id=call_id).status_code == 200
    context = client.get(f"/agent/patients/{person_id}/context", headers=advisor).json()["cases"][0]
    assert context["slot_id"] == scheduled["slot_id"] and context["requester"]["email"] == email
    confirmed = client.patch(f"/cases/{web['id']}", headers=advisor, json={
        "expected_version": context["version"], "fields": {"confirmed": True},
    }).json()["case"]
    assert confirmed["status"] == "cita_confirmada"
    assert call(client, advisor, kind="call_ended", call_id=call_id).status_code == 200

    app_session = login_app(client, email)
    rows = client.get("/me/cases", headers=app_session).json()["cases"]
    assert [item["id"] for item in rows] == [web["id"]]
    response = open_case(client, app_session, rows[0], email, "open-ana")
    assert response.status_code == 200, response.text
    app = response.json()
    assert app["case"]["status"] == "cita_confirmada"
    assert app["case"]["slot_datetime"] == confirmed["slot_datetime"]
    assert app["missing_steps"] == []
    assert all(app["case"]["steps"].values())
    assert {item["channel"] for item in app["timeline"]} == {"web", "whatsapp", "callcenter", "app"}
    assert open_case(client, app_session, rows[0], email, "open-ana").json() == app
    with SessionLocal() as session:
        events = session.scalars(select(Event).where(
            Event.case_id == web["id"], Event.type == "canal_cambiado",
        ).order_by(Event.seq)).all()
        assert [(event.payload["from"], event.payload["to"]) for event in events] == [
            ("web", "whatsapp"), ("whatsapp", "callcenter"), ("callcenter", "app"),
        ]
        assert session.scalars(select(Person.id).where(Person.email == email)).all() == [person_id]


def test_app_scope_relationship_and_expiry(client):
    assert client.get("/me/cases", headers=APP_KEY).status_code == 401
    assert client.post("/identity/verify/request", json={
        "channel": "app", "identifier": "marta.demo@example.com", "method": "email_otp",
    }).status_code == 403
    web_token = create_patient_token(owner("C-1002"))
    assert client.get("/me/cases", headers={**APP_KEY, "Authorization": f"Bearer {web_token}"}).status_code == 403
    email = "marta.demo@example.com"
    app_session = login_app(client, email)
    cases = client.get("/me/cases", headers=app_session).json()["cases"]
    assert len(cases) == 1
    assert cases[0]["id"] == "C-1002" and cases[0]["patient_name"] == "Pablo Demo"
    assert cases[0]["relationship"] == "hijo_a"
    assert "birth_date" not in cases[0] and "patient_id" not in cases[0]
    unauthorized = open_case(client, app_session, {**cases[0], "id": "C-1003"}, email)
    assert unauthorized.status_code == 404
    stale = open_case(client, app_session, {**cases[0], "version": cases[0]["version"] + 1}, email)
    assert stale.status_code == 409
    with SessionLocal.begin() as session:
        grant = session.scalar(select(Verification).where(Verification.channel == "app", Verification.status == "succeeded"))
        grant.valid_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    fresh_session = login_app(client, email)
    assert client.get("/me/cases", headers=app_session).status_code == 401
    assert client.get("/me/cases", headers=fresh_session).status_code == 200
    with SessionLocal.begin() as session:
        session.add(Person(id="P-DUP-APP", email=email, phone="+522229999999",
                           full_name="Otra cuenta", is_provisional=True))
    ambiguous = client.post("/identity/verify/request", headers=APP_KEY, json={
        "channel": "app", "identifier": email, "method": "email_otp",
    })
    assert ambiguous.status_code == 409
    assert "Otra cuenta" not in ambiguous.text
