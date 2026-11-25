from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, Event, Person, Verification
from app.modules.adapters import app as app_adapter
from app.security import create_patient_token
from test_agent import call, owner, token, verify
from test_whatsapp import ana_web_case, latest_code, web_interaction, whatsapp


APP_KEY = {"X-Channel-Key": "demo-app-key"}


def login_app(client, email):
    body = {"channel": "app", "identifier": email}
    requested = client.post("/identity/verify/request", headers=APP_KEY, json={**body, "method": "email_otp"})
    assert requested.status_code == 200, requested.text
    confirmed = client.post("/identity/verify/confirm", headers=APP_KEY, json={**body, "code": latest_code(email)})
    assert confirmed.status_code == 200, confirmed.text
    return {**APP_KEY, "Authorization": f"Bearer {confirmed.json()['access_token']}"}


def app_action(client, auth, email, action, data, key=None):
    return client.post("/channels/app/interactions", headers=auth, json={
        "identifier": email, "identifier_type": "account", "kind": "action", "action": action,
        "idempotency_key": key or str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    })


def case_action(client, auth, email, item, action, *, key=None, **fields):
    return app_action(client, auth, email, action, {
        "case_id": item["id"], "expected_version": item["version"], **fields,
    }, key)


def open_case(client, auth, item, email, key=None):
    return case_action(client, auth, email, item, "continue_case", key=key)


def test_ana_full_flow(client):
    assert client.post("/demo/reset").status_code == 200
    email, phone = "ana.demo@example.com", "+522220000001"
    with SessionLocal() as session:
        assert session.scalar(select(Person).where(Person.email == email)) is None
    web = web_interaction(client, "ana-full-flow", "preregister", {
        "requester": {"full_name": "Ana Demo", "email": email, "phone": phone, "birth_date": "1990-05-10"},
        "relationship": "self", "study_id": "ST-003",
    }).json()["case"]
    assert web["status"] == "datos_completos"
    person_id = owner(web["id"])

    assert whatsapp(client, phone, content="hola").json()["trust_level"] == 1
    whatsapp(client, phone, content="10/05/1990")
    assert whatsapp(client, phone, content=latest_code(email)).json()["trust_level"] == 2
    continued = whatsapp(client, phone, action="continue_case").json()
    clinic = continued["messages"][0]["quick_replies"][0]
    chosen = whatsapp(client, phone, action=clinic["action"], data=clinic["payload"]).json()["case"]
    assert chosen["id"] == web["id"] and chosen["status"] == "clinica_elegida"

    app_session = login_app(client, email)
    rows = client.get("/me/cases", headers=app_session).json()["cases"]
    assert [item["id"] for item in rows] == [web["id"]]
    response = open_case(client, app_session, rows[0], email, "open-ana")
    assert response.status_code == 200, response.text
    opened = response.json()
    assert opened["trust_level"] == 2
    assert opened["missing_steps"] == ["slot", "confirmed"]
    assert open_case(client, app_session, rows[0], email, "open-ana").json() == opened
    slots = client.get("/catalog/slots", params={"clinic_id": chosen["clinic_id"]}).json()
    slot = slots[0]
    assert datetime.fromisoformat(slot["starts_at"]).astimezone(ZoneInfo("America/Mexico_City")).hour == 9
    response = case_action(client, app_session, email, opened["case"], "select_slot", slot_id=slot["id"])
    assert response.status_code == 200, response.text
    scheduled = response.json()
    assert scheduled["case"]["status"] == "horario_propuesto"
    assert scheduled["missing_steps"] == ["confirmed"]
    assert {event["channel"] for event in scheduled["timeline"]} >= {"web", "whatsapp", "app"}

    advisor = token(client)
    call_id = call(client, advisor, phone=phone).json()["call_id"]
    assert verify(client, advisor, person_id, birth="1990-05-10", call_id=call_id).status_code == 200
    context = client.get(f"/agent/patients/{person_id}/context", headers=advisor).json()["cases"][0]
    assert context["slot_id"] == slot["id"] and context["requester"]["email"] == email
    confirmed = client.patch(f"/cases/{web['id']}", headers=advisor, json={
        "expected_version": context["version"], "fields": {"confirmed": True},
    }).json()["case"]
    assert confirmed["status"] == "cita_confirmada"
    assert call(client, advisor, kind="call_ended", call_id=call_id).status_code == 200

    admin = token(client, "admin", "Admin#2026")
    board = client.get("/admin/dashboard", headers=admin)
    assert board.status_code == 200
    journey = ["web", "whatsapp", "app", "callcenter"]
    assert board.json()["journeys"][web["id"]] == journey
    listing = client.get("/admin/cases", headers=admin).json()["cases"]
    row = next(item for item in listing if item["id"] == web["id"])
    assert row["channels"] == journey and row["status"] == "cita_confirmada"
    assert "Ana Demo" not in str(row) and email not in str(row)
    with SessionLocal() as session:
        events = session.scalars(select(Event).where(
            Event.case_id == web["id"], Event.type == "canal_cambiado",
        ).order_by(Event.seq)).all()
        assert [(event.payload["from"], event.payload["to"]) for event in events] == [
            ("web", "whatsapp"), ("whatsapp", "app"), ("app", "callcenter"),
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


def test_app_case_mutations_require_ownership_and_current_version(client):
    email = "ana.demo@example.com"
    web = ana_web_case(client)
    auth = login_app(client, email)
    opened = open_case(client, auth, web, email).json()["case"]
    assert opened["version"] == web["version"] + 1
    with SessionLocal() as session:
        other_version = session.get(Case, "C-1002").version
    for action, fields in (
        ("continue_case", {}), ("select_study", {"study_id": "ST-001"}),
        ("select_clinic", {"clinic_id": "CL-001"}), ("select_slot", {"slot_id": "SL-UNKNOWN"}),
        ("confirm_case", {}),
    ):
        other = case_action(client, auth, email, {"id": "C-1002", "version": other_version}, action, **fields)
        absent = case_action(client, auth, email, {"id": "C-NO-EXISTE", "version": other_version}, action, **fields)
        assert other.status_code == absent.status_code == 404
        assert other.json() == absent.json() == {
            "error": "case_not_found", "message": "No encontramos el trámite en esta cuenta.",
        }
    assert app_action(client, auth, email, "select_study", {"case_id": web["id"], "study_id": "ST-001"}).status_code == 422
    changed = case_action(client, auth, email, opened, "select_study", key="new-study", study_id="ST-001")
    assert changed.status_code == 200, changed.text
    assert changed.json()["case"]["version"] == opened["version"] + 1
    assert case_action(client, auth, email, opened, "select_study", key="new-study", study_id="ST-001").json() == changed.json()
    stale = case_action(client, auth, email, opened, "select_clinic", clinic_id="CL-002")
    assert stale.status_code == 409 and stale.json()["case"] == changed.json()["case"]
    with SessionLocal() as session:
        assert session.get(Case, "C-1002").version == other_version
        assert session.get(Case, web["id"]).version == changed.json()["case"]["version"]


def test_app_preregister_for_another_person_reuses_exact_match_and_confirms(client):
    email = "marta.demo@example.com"
    auth = login_app(client, email)
    data = {"study_id": "ST-001", "relationship": "hijo_a",
            "patient": {"full_name": "Pablo Demo", "birth_date": "15/03/2012"}}
    for invalid in ({**data, "patient": None}, {**data, "study_id": ""}, {**data, "requester": {"email": "pablo.demo@example.com"}}):
        assert app_action(client, auth, email, "preregister", invalid).status_code == 422
    created = app_action(client, auth, email, "preregister", data, "app-third-party")
    assert created.status_code == 200, created.text
    detail = created.json()
    item = detail["case"]
    assert item["version"] == 1 and item["patient_name"] == "Pablo Demo" and item["relationship"] == "hijo_a"
    assert set(detail["events"]) == {"tramite_creado", "datos_paciente_capturados", "estudio_seleccionado"}
    assert app_action(client, auth, email, "preregister", data, "app-third-party").json() == detail
    with SessionLocal() as session:
        seeded = session.get(Case, "C-1002")
        case = session.get(Case, item["id"])
        assert case.requester_id == seeded.requester_id and case.patient_id == seeded.patient_id
        assert len(session.scalars(select(Person).where(Person.full_name == "Pablo Demo")).all()) == 1
        events = session.scalars(select(Event).where(Event.case_id == case.id)).all()
        assert len(events) == 3
        assert all(not {"birth_date", "otp", "code", "content"} & event.payload.keys() for event in events)

    chosen = case_action(client, auth, email, item, "select_clinic", clinic_id="CL-001")
    assert chosen.status_code == 200, chosen.text
    slots = client.get("/catalog/slots", params={"clinic_id": "CL-001"}).json()
    hours = {datetime.fromisoformat(slot["starts_at"]).astimezone(ZoneInfo("America/Mexico_City")).hour for slot in slots}
    assert hours == {9, 10, 11, 12, 13}
    scheduled = case_action(client, auth, email, chosen.json()["case"], "select_slot", slot_id=slots[0]["id"])
    assert scheduled.status_code == 200, scheduled.text
    patient_email = "pablo.demo@example.com"
    patient_session = login_app(client, patient_email)
    patient_items = client.get("/me/cases", headers=patient_session).json()["cases"]
    patient_item = next(row for row in patient_items if row["id"] == item["id"])
    confirmed = case_action(client, patient_session, patient_email, patient_item, "confirm_case")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["case"]["status"] == "cita_confirmada" and confirmed.json()["missing_steps"] == []


def test_app_activity_renews_only_a_valid_session(client, monkeypatch):
    email = "marta.demo@example.com"
    auth = login_app(client, email)
    now = datetime.now(timezone.utc)
    current = now + timedelta(minutes=25)
    monkeypatch.setattr(app_adapter, "utc_now", lambda: current)
    listing = client.get("/me/cases", headers=auth)
    assert listing.status_code == 200
    assert datetime.fromisoformat(listing.headers["X-App-Valid-Until"]) == current + timedelta(minutes=30)
    current = now + timedelta(minutes=45)
    opened = open_case(client, auth, listing.json()["cases"][0], email)
    assert opened.status_code == 200 and opened.json()["trust_level"] == 2
    renewed = datetime.fromisoformat(opened.headers["X-App-Valid-Until"])
    assert renewed == current + timedelta(minutes=30)
    current = renewed + timedelta(seconds=1)
    for expired in (client.get("/me/cases", headers=auth), open_case(client, auth, opened.json()["case"], email)):
        assert expired.status_code == 401 and expired.json()["error"] == "session_expired"
        assert "X-App-Valid-Until" not in expired.headers


def test_app_actions_and_session_renewal_are_documented_in_openapi(client):
    document = client.get("/openapi.json").json()
    action_schema = document["paths"]["/channels/app/interactions"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert set(action_schema["discriminator"]["mapping"]) == {
        "continue_case", "select_study", "select_clinic", "select_slot", "confirm_case", "preregister",
    }
    assert "study_id" in document["components"]["schemas"]["AppPreregisterData"]["required"]
    assert "expected_version" in document["components"]["schemas"]["CaseActionData"]["required"]
    assert "X-App-Valid-Until" in document["paths"]["/me/cases"]["get"]["responses"]["200"]["headers"]
