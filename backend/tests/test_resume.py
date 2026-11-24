from concurrent.futures import ThreadPoolExecutor
import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Case, ChannelIdentity, Event, Person
from test_whatsapp import web_interaction, whatsapp


def begin(client, email):
    response = client.post("/resume/request", json={"channel": "web", "email": email})
    assert response.status_code == 202
    return response.json()


def verify(client, email):
    challenge = begin(client, email)["challenge_id"]
    code = client.get("/demo/mailbox", params={"email": email}).json()["messages"][0]["code"]
    response = client.post("/resume/confirm", json={"challenge_id": challenge, "code": code})
    assert response.status_code == 200, response.text
    return challenge, response.json()["items"]


def choose(client, challenge, item, key="selection"):
    return client.post("/resume/select", json={
        "challenge_id": challenge, "kind": item["kind"], "id": item["id"],
        "expected_version": item["version"], "idempotency_key": key,
    })


def whatsapp_draft(client):
    phone = "+522225557777"
    for content in ("agendar", "Ana Demo", "10/05/1990", "draft@example.com"):
        assert whatsapp(client, phone, content=content).status_code == 200
    return phone


def test_email_response_is_neutral_and_selection_requires_otp(client):
    present = begin(client, "luis.demo@example.com")
    absent = begin(client, "unlisted@example.com")
    assert {**present, "challenge_id": None} == {**absent, "challenge_id": None}
    assert choose(client, present["challenge_id"], {"kind": "case", "id": "C-1001", "version": 1}).status_code == 403
    actual = client.get("/demo/mailbox", params={"email": "luis.demo@example.com"}).json()["messages"][0]["code"]
    incorrect = "111111" if actual != "111111" else "222222"
    for remaining in (2, 1, 0):
        responses = [client.post("/resume/confirm", json={
            "challenge_id": entry["challenge_id"], "code": incorrect,
        }) for entry in (present, absent)]
        assert responses[0].status_code == responses[1].status_code
        assert responses[0].json() == responses[1].json()
        assert responses[0].json()["attempts_remaining"] == remaining


def test_verified_list_only_includes_owners_cases(client):
    challenge, items = verify(client, "luis.demo@example.com")
    assert [item["id"] for item in items] == ["C-1001"]
    forbidden = choose(client, challenge, {**items[0], "id": "C-1002"})
    assert forbidden.status_code == 403
    assert choose(client, challenge, items[0]).json()["case"]["abandoned"] is False
    assert client.get("/cases/C-1001").status_code == 200


def test_whatsapp_uses_verified_case_without_reassigning_phone(client):
    phone = "+522225558888"
    response = client.post("/resume/request", headers={"X-Channel-Key": "demo-whatsapp-key"}, json={
        "channel": "whatsapp", "phone": phone, "email": "luis.demo@example.com",
    })
    challenge = response.json()["challenge_id"]
    code = client.get("/demo/mailbox", params={"email": "luis.demo@example.com"}).json()["messages"][0]["code"]
    items = client.post("/resume/confirm", json={"challenge_id": challenge, "code": code}).json()["items"]
    assert choose(client, challenge, items[0]).status_code == 200
    action = whatsapp(client, phone, action="continue_case", data={"resume_challenge_id": challenge})
    assert action.json()["case"]["id"] == "C-1001"
    assert whatsapp(client, phone, action="continue_case").json()["case"] is None
    other = TestClient(app)
    assert whatsapp(other, phone, action="continue_case", data={"resume_challenge_id": challenge}).status_code == 403


def test_whatsapp_draft_moves_to_web_once_even_with_concurrent_selection(client):
    phone = whatsapp_draft(client)
    other = TestClient(app)
    challenge_a, items_a = verify(client, "draft@example.com")
    challenge_b, items_b = verify(other, "draft@example.com")
    assert items_a == items_b
    assert items_a[0]["channel"] == "whatsapp"
    with ThreadPoolExecutor(max_workers=2) as workers:
        a = workers.submit(choose, client, challenge_a, items_a[0])
        b = workers.submit(choose, other, challenge_b, items_b[0])
        replies = [a.result(), b.result()]
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    winner = 0 if replies[0].status_code == 200 else 1
    winning_client, challenge = [(client, challenge_a), (other, challenge_b)][winner]
    assert replies[winner].json()["draft"]["requester"]["full_name"] == "Ana Demo"
    assert choose(winning_client, challenge, items_a[0]).json() == replies[winner].json()
    stale = whatsapp(client, phone, action="answer", data={"value": "self"})
    assert stale.json()["case"] is None
    assert "Para quién" not in stale.text


def test_whatsapp_email_resume_in_chat(client):
    phone = "+522225559991"
    menu = whatsapp(client, phone, action="resume_menu").json()
    method = menu["messages"][0]["quick_replies"][0]
    assert method["label"] == "Con mi correo"
    assert whatsapp(client, phone, action=method["action"]).json()["resume_input"] == "email"
    requested = whatsapp(client, phone, action="resume_email_value", content="luis.demo@example.com").json()
    assert requested["resume_input"] == "code"
    assert requested["case"] is None
    challenge = {"resume_challenge_id": requested["resume_challenge_id"]}
    code = client.get("/demo/mailbox", params={"email": "luis.demo@example.com"}).json()["messages"][0]["code"]
    confirmed = whatsapp(client, phone, action="resume_code", content=code, data=challenge).json()
    replies = confirmed["messages"][0]["quick_replies"]
    assert "Luis Demo" in replies[0]["label"]
    selected = whatsapp(client, phone, action=replies[0]["action"], data={**challenge, **replies[0]["payload"]})
    assert selected.status_code == 200, selected.text
    assert selected.json()["case"]["id"] == "C-1001"
    assert code not in json.dumps(confirmed)
    with SessionLocal() as session:
        payloads = session.scalars(select(Event.payload).where(Event.channel == "whatsapp")).all()
    assert code not in json.dumps(payloads)


def test_whatsapp_chat_offers_and_imports_a_draft(client):
    source = TestClient(app)
    saved = web_interaction(source, "draft-source", "save_draft", {
        "requester": {"email": "draft-chat@example.com", "full_name": "Marta Demo",
                      "birth_date": "1982-08-20"},
        "relationship": "hijo_a",
    })
    assert saved.status_code == 200, saved.text
    phone = "+522225559992"
    requested = whatsapp(client, phone, action="resume_email_value", content="draft-chat@example.com").json()
    challenge = {"resume_challenge_id": requested["resume_challenge_id"]}
    code = client.get("/demo/mailbox", params={"email": "draft-chat@example.com"}).json()["messages"][0]["code"]
    confirmed = whatsapp(client, phone, action="resume_code", content=code, data=challenge).json()
    reply = confirmed["messages"][0]["quick_replies"][0]
    assert reply["payload"]["kind"] == "draft"
    selected = whatsapp(client, phone, action=reply["action"], data={**challenge, **reply["payload"]})
    assert selected.status_code == 200, selected.text
    assert "nombre completo del paciente" in selected.text.lower()
    assert web_interaction(source, "draft-source", "continue_case", {}).json()["draft"] is None


def test_requester_verifies_and_lists_cases_for_different_patients(client):
    challenge, items = verify(client, "marta.demo@example.com")
    identifier = choose(client, challenge, items[0]).json()["session_identifier"]
    requester = {"full_name": "Marta Demo", "birth_date": "1982-08-20",
                 "email": "marta.demo@example.com", "phone": "+522229999999"}
    created = {}
    for name in ("Pablo Demo", "Otro paciente"):
        result = web_interaction(client, identifier, "preregister", {
            "requester": requester, "relationship": "hijo_a", "study_id": "ST-001",
            "patient": {"full_name": name, "birth_date": "2012-03-15",
                        "email": "pablo.demo@example.com", "phone": "+522229999999"},
        })
        assert result.status_code == 200, result.text
        created[result.json()["case"]["id"]] = name
    with SessionLocal() as session:
        for case_id in created:
            case = session.get(Case, case_id)
            patient = session.get(Person, case.patient_id)
            assert patient.id != case.requester_id
            assert patient.email is None and patient.phone is None
            assert session.scalar(select(ChannelIdentity.id).where(ChannelIdentity.person_id == patient.id)) is None

    _, marta_items = verify(TestClient(app), "marta.demo@example.com")
    assert {item["id"]: item["patient_name"] for item in marta_items if item["id"] in created} == created
    _, pablo_items = verify(TestClient(app), "pablo.demo@example.com")
    assert not (created.keys() & {item["id"] for item in pablo_items})

    phone = requester["phone"]
    whatsapp(client, phone, content="hola")
    assert whatsapp(client, phone, content="20/08/1982").status_code == 200
    marta_code = client.get("/demo/mailbox", params={"email": requester["email"]}).json()["messages"][0]["code"]
    assert whatsapp(client, phone, content=marta_code).json()["trust_level"] == 2
    pablo_mail = client.get("/demo/mailbox", params={"email": "pablo.demo@example.com"}).json()
    wrong = client.post("/identity/verify/request", json={
        "channel": "whatsapp", "identifier": phone, "method": "dob_check", "birth_date": "2012-03-15",
    })
    assert wrong.status_code == 422
    assert client.get("/demo/mailbox", params={"email": "pablo.demo@example.com"}).json() == pablo_mail
