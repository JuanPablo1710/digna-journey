from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import create_app
from app.models import Case, Event, Person
from app.modules.admin.metrics import dashboard_counts, journeys
from app.modules.events import append_event
from app.security import create_patient_token
from test_agent import owner, token, verify


ADMIN = ("admin", "Admin#2026")


def test_seed_history_is_varied_and_masked_from_the_start(client):
    headers = token(client, *ADMIN)
    with SessionLocal() as session:
        history = session.scalars(select(Event).order_by(Event.seq)).all()
        kinds = {event.type for event in history}
        assert {
            "consentimiento_aceptado", "identidad_vinculada", "verificacion_solicitada",
            "verificacion_exitosa", "verificacion_fallida", "tramite_creado", "estudio_seleccionado",
            "datos_paciente_capturados", "clinica_seleccionada", "horario_propuesto",
            "cita_confirmada", "tramite_cancelado", "tramite_abandonado", "canal_iniciado",
            "canal_cambiado", "mensaje_recibido", "mensaje_enviado", "llamada_iniciada",
            "llamada_finalizada", "contexto_consultado", "nota_agregada", "acceso_denegado",
        } <= kinds
        assert any(event.payload["locked"] for event in history if event.type == "verificacion_fallida")
        assert sum(event.type == "acceso_denegado" for event in history) == 4
        assert all(set(event.payload) == {"type"} for event in history if event.type.startswith("mensaje_"))
        assert all(not {"otp", "code", "birth_date", "content", "text"} & set(event.payload) for event in history)
        assert all(event.case_id in {f"C-{index}" for index in range(1001, 1010)} for event in history)
    log = client.get("/admin/audit", headers=headers).json()["entries"]
    assert {"contexto_consultado", "acceso_denegado", "verificacion_solicitada",
            "verificacion_exitosa", "verificacion_fallida"} <= {entry["type"] for entry in log}
    assert any("Acceso denegado · sin verificación vigente" in entry["summary"] for entry in log)
    board = client.get("/admin/dashboard", headers=headers).json()
    assert {"mensaje_enviado", "canal_cambiado", "cita_confirmada"} <= {event["type"] for event in board["recent_events"]}
    assert board["journeys"]["C-1007"] == ["web", "whatsapp", "callcenter"]


def test_admin_masking(client):
    agent = token(client)
    person_id = owner()
    verify(client, agent, person_id, "2000-01-01")
    verify(client, agent, person_id)
    assert client.get(f"/agent/patients/{person_id}/context", headers=agent).status_code == 200
    with SessionLocal.begin() as session:
        append_event(session, event_type="verificacion_fallida", channel="whatsapp", actor_id="+522221111111",
                     person_id=person_id, case_id="C-1001",
                     payload={"otp": "983421", "birth_date": "1985-04-12", "note": "Interna secreta"})
    headers = token(client, *ADMIN)
    for path in ("/admin/dashboard", "/admin/cases", "/admin/audit"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        for forbidden in ("Luis Demo", "+522221111111", "luis.demo@example.com", "1985-04-12",
                          "983421", "Interna secreta", "actor_id", "birth_date"):
            assert forbidden not in response.text
    filtered = client.get("/admin/cases?status=clinica_elegida&channel=web", headers=headers).json()["cases"]
    assert {item["id"] for item in filtered} == {"C-1001", "C-1006"}
    masked = next(item["requester"] for item in filtered if item["id"] == "C-1001")
    assert masked == {"name": "L*** D.", "phone": "***1111", "email": "l***@example.com"}
    entries = client.get("/admin/audit", headers=headers).json()["entries"]
    consult = next(item for item in entries if item["type"] == "contexto_consultado")
    assert consult["person"] == masked
    assert consult["actor"] == {"role": "asesor", "id": "U-0001"}


def test_admin_endpoints_enforce_roles(client):
    agent = token(client)
    admin = token(client, *ADMIN)
    patient = {"Authorization": f"Bearer {create_patient_token(owner())}"}
    for path in ("/admin/dashboard", "/admin/cases", "/admin/audit"):
        for headers, code in (({}, 401), (agent, 403), (patient, 403), (admin, 200)):
            assert client.get(path, headers=headers).status_code == code
    assert client.get(f"/agent/patients/{owner()}/context", headers=admin).status_code == 403




def test_seed_is_non_destructive_and_repeatable(client):
    admin = token(client, *ADMIN)
    with SessionLocal.begin() as session:
        session.add(Person(id="P-KEEP", full_name="Persona propia", is_provisional=True))
        session.get(Case, "C-1001").abandoned = False
    assert TestClient(create_app(demo_mode=False)).post("/demo/seed", headers=admin).status_code == 404
    assert client.post("/demo/seed").status_code == 401
    snapshots = []
    for _ in range(2):
        assert client.post("/demo/seed", headers=admin).json() == {"status": "ok"}
        with SessionLocal() as session:
            snapshots.append(tuple(session.scalar(select(func.count()).select_from(model)) for model in (Person, Case, Event)))
            assert session.get(Person, "P-KEEP") is not None
            assert not session.get(Case, "C-1001").abandoned
    assert snapshots[0] == snapshots[1]


def test_recovery_requires_real_progress_after_channel_change():
    now = datetime.now(timezone.utc)
    cases = [SimpleNamespace(id=str(index), last_channel="whatsapp", abandoned=False, status="horario_propuesto")
             for index in range(5)]
    events = []

    def event(case_id, name, channel="web", **payload):
        events.append(SimpleNamespace(case_id=str(case_id), type=name, channel=channel, payload=payload, timestamp=now))

    for index in range(len(cases)):
        event(index, "tramite_creado")
    event(0, "datos_paciente_capturados")
    event(0, "canal_cambiado", "whatsapp", **{"from": "web", "to": "whatsapp"})
    event(0, "clinica_seleccionada", "whatsapp")
    event(1, "horario_propuesto")
    event(1, "canal_cambiado", "whatsapp", **{"from": "web", "to": "whatsapp"})
    event(1, "clinica_seleccionada", "whatsapp")
    event(2, "canal_cambiado", "web", **{"from": "web", "to": "web"})
    event(2, "horario_propuesto")
    event(3, "canal_cambiado", "whatsapp", **{"from": "web", "to": "whatsapp"})
    event(3, "tramite_cancelado", "whatsapp")
    event(4, "horario_propuesto", "whatsapp")
    routes, by_case = journeys(cases, events)
    assert routes["0"] == ["web", "whatsapp"]
    assert dashboard_counts(cases, routes, by_case)["recovered_across_channels"] == 1
