from sqlalchemy import select

from app.db import SessionLocal
from app.models import Case, ChannelIdentity, Draft, Event, MailboxMessage, Person, ResumeChallenge, Verification
from app.modules.demo import reset
from app.modules.resume import _deliver
from test_web_core import interaction


def snapshot():
    with SessionLocal() as session:
        return {
            model.__tablename__: [tuple(row) for row in session.execute(
                select(*model.__table__.columns).order_by(*model.__table__.primary_key)
            )]
            for model in (Case, Event, Person)
        }


def test_command_and_endpoint_share_repeatable_seed(client, capsys):
    assert reset.main() == 0
    first = snapshot()
    report = reset.REPORT_PATH.read_text(encoding="utf-8")
    assert capsys.readouterr().out.strip() == report.strip()
    assert client.post("/demo/reset").status_code == 200
    assert snapshot() == first
    assert reset.REPORT_PATH.read_text(encoding="utf-8") == report
    assert len(first["cases"]) == 9
    with SessionLocal() as session:
        case = session.get(Case, "C-1002")
        assert (case.requester_id, case.patient_id, case.relationship, case.status) == (
            "P-1002", "P-1003", "hijo_a", "horario_propuesto",
        )


def test_reset_removes_ana_mailbox_drafts_and_lockouts(client):
    session_id = "ana-before-reset"
    created = interaction(client, session_id, "preregister", {
        "requester": {"full_name": "Ana Demo", "birth_date": "1990-05-10",
                      "email": "ana.demo@example.com", "phone": "+522220000001"},
        "relationship": "self",
    })
    assert created.status_code == 200
    challenge = client.post("/resume/request", json={"channel": "web", "email": "ana.demo@example.com"})
    assert challenge.status_code == 202
    assert client.get("/demo/mailbox", params={"email": "ana.demo@example.com"}).json()["messages"]
    assert interaction(client, "draft-before-reset", "save_draft", {
        "requester": {"email": "ana.demo@example.com"},
    }).status_code == 200
    dob = {"channel": "whatsapp", "identifier": "+522221111111", "method": "dob_check", "birth_date": "2000-01-01"}
    for status in (422, 422, 429):
        assert client.post("/identity/verify/request", json=dob).status_code == status
    assert client.post("/demo/reset").status_code == 200
    _deliver(challenge.json()["challenge_id"], "ana.demo@example.com", "012345", True)
    with SessionLocal() as session:
        for model in (ChannelIdentity, Draft, MailboxMessage, ResumeChallenge, Verification):
            assert session.scalar(select(model).limit(1)) is None
        assert session.scalar(select(Person.id).where(
            (Person.email == "ana.demo@example.com") | (Person.phone == "+522220000001"),
        )) is None
        assert session.get(Case, created.json()["case"]["id"]) is None
        assert not [event for event in session.scalars(select(Event))
                    if "ana-before-reset" in event.actor_id or "ana.demo@example.com" in str(event.payload)]
    assert client.post("/identity/verify/request", json=dob).json()["attempts_remaining"] == 2


def test_reset_revokes_web_cookie_and_staff_token(client):
    session_id = "old-session"
    assert interaction(client, session_id, "start_quote").status_code == 200
    old_token = client.post("/auth/login", json={"username": "asesor", "password": "Asesor#2026"}).json()["access_token"]
    result = client.post("/demo/reset")
    assert "Max-Age=0" in result.headers["set-cookie"]
    client.cookies.set("web_session", session_id)
    assert interaction(client, session_id, "start_quote").status_code == 403
    assert interaction(client, session_id, "continue_case").json()["reset_session"] is True
    assert client.get("/agent/lookup?email=luis.demo@example.com",
                      headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
