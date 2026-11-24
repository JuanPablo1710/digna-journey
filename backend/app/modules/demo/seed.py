from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...catalog import CLINICS, MEXICO_CITY, STUDIES, get_demo_slots
from ...models import Case, Event, Person, User
from ...security import hash_password


DEMO_USERS = (
    ("U-0001", "asesor", "Asesor#2026", "asesor"),
    ("U-0002", "admin", "Admin#2026", "admin"),
)
DEMO_PEOPLE = (
    ("P-1001", "Luis Demo", "luis.demo@example.com", "+522221111111", "1985-04-12"),
    ("P-1002", "Marta Demo", "marta.demo@example.com", "+522229999999", "1982-08-20"),
    ("P-1003", "Pablo Demo", "pablo.demo@example.com", "+522229999999", "2012-03-15"),
    ("P-1004", "Elena Demo", "elena.demo@example.com", "+522220000004", "1993-01-09"),
    ("P-1005", "Diego Demo", "diego.demo@example.com", "+522220000005", "1989-06-21"),
    ("P-1006", "Sofía Demo", "sofia.demo@example.com", "+522220000006", "1991-10-03"),
    ("P-1007", "Bruno Demo", "bruno.demo@example.com", "+522220000007", "1987-02-17"),
    ("P-1008", "Irene Demo", "irene.demo@example.com", "+522220000008", "1995-07-28"),
    ("P-1009", "Raúl Demo", "raul.demo@example.com", "+522220000009", "1980-11-11"),
)
# Folio, solicitante, paciente, estudio, clínica, estado, abandono, recorrido.
DEMO_CASES = (
    ("C-1001", "P-1001", "P-1001", "ST-003", "CL-001", "clinica_elegida", True, ("web",)),
    ("C-1002", "P-1002", "P-1003", "ST-001", "CL-002", "horario_propuesto", False, ("web", "whatsapp")),
    ("C-1003", "P-1003", "P-1003", "ST-004", "CL-001", "horario_propuesto", False, ("web",)),
    ("C-1004", "P-1004", "P-1004", "ST-002", None, "cotizando", False, ("web",)),
    ("C-1005", "P-1005", "P-1005", "ST-005", None, "datos_completos", False, ("whatsapp",)),
    ("C-1006", "P-1006", "P-1006", "ST-003", "CL-003", "clinica_elegida", False, ("web", "whatsapp")),
    ("C-1007", "P-1007", "P-1007", "ST-002", "CL-001", "cita_confirmada", False, ("web", "whatsapp", "callcenter")),
    ("C-1008", "P-1008", "P-1008", "ST-005", "CL-002", "cancelado", False, ("web", "callcenter")),
    ("C-1009", "P-1009", "P-1009", "ST-004", "CL-003", "horario_propuesto", True, ("web", "whatsapp", "callcenter")),
)


def demo_day():
    local_day = datetime.now(MEXICO_CITY).date()
    return datetime.combine(local_day, time(), tzinfo=MEXICO_CITY).astimezone(timezone.utc)


def _seed_case(session, row, anchor, index):
    folio, requester, patient, study, clinic, status, abandoned, route = row
    start = anchor - timedelta(days=4 - index % 3, hours=index)
    has_slot = status in {"horario_propuesto", "cita_confirmada"}
    slots = [slot for slot in get_demo_slots(anchor) if slot["clinic_id"] == clinic]
    slot = slots[index % len(slots)] if has_slot else None
    relationship = "self" if requester == patient else "hijo_a"
    steps = dict(study=bool(study), patient_data=status != "cotizando", clinic=bool(clinic),
                 slot=has_slot, confirmed=status == "cita_confirmada")
    events = [("tramite_creado", route[0], {"relationship": relationship})]
    if study:
        events.append(("estudio_seleccionado", route[0], {"study_id": study}))
    if steps["patient_data"]:
        events.append(("datos_paciente_capturados", route[0], {"relationship": relationship}))
    if clinic:
        channel = route[1] if len(route) > 1 else route[0]
        if channel != route[0]:
            events.append(("canal_cambiado", channel, {"from": route[0], "to": channel}))
        events.append(("clinica_seleccionada", channel, {"clinic_id": clinic}))
    if slot:
        events.append(("horario_propuesto", events[-1][1], {"slot_id": slot["id"], "starts_at": slot["starts_at"]}))
    if events[-1][1] != route[-1]:
        events.append(("canal_cambiado", route[-1], {"from": events[-1][1], "to": route[-1]}))
    if status == "cita_confirmada":
        events.append(("cita_confirmada", route[-1], {}))
    if status == "cancelado":
        events.append(("tramite_cancelado", route[-1], {}))
    if abandoned:
        events.append(("tramite_abandonado", route[-1], {}))
    timestamps = [
        start + timedelta(minutes=45 * position + (15 if kind == "tramite_abandonado" else 0))
        for position, (kind, _, _) in enumerate(events)
    ]
    session.add(Case(
        id=folio, requester_id=requester, patient_id=patient, relationship=relationship,
        study_id=study, clinic_id=clinic, slot_id=slot["id"] if slot else None,
        slot_datetime=datetime.fromisoformat(slot["starts_at"]) if slot else None,
        steps=steps, status=status, abandoned=abandoned, current_channel=route[-1],
        last_channel=route[-1], version=len(events), created_at=start, updated_at=timestamps[-1],
    ))
    session.flush()
    for position, ((kind, channel, payload), timestamp) in enumerate(zip(events, timestamps), 1):
        session.add(Event(
            event_id=f"evt_seed_{folio}_{position:02d}", type=kind, case_id=folio,
            person_id=requester, channel=channel, actor_id="U-0001" if channel == "callcenter" else f"seed-{requester}",
            actor_role="asesor" if channel == "callcenter" else "paciente", timestamp=timestamp, payload=payload,
        ))


def seed_demo(session: Session, anchor=None) -> None:
    """Carga datos ficticios sin duplicar filas y deja el commit al llamador."""
    anchor = anchor or demo_day()
    for identifier, username, password, role in DEMO_USERS:
        if session.scalar(select(User.id).where(User.username == username)) is None:
            session.add(User(id=identifier, username=username, password_hash=hash_password(password), role=role))
    for identifier, name, email, phone, birth in DEMO_PEOPLE:
        if session.get(Person, identifier) is None:
            session.add(Person(id=identifier, full_name=name, birth_date=date.fromisoformat(birth),
                               email=email, phone=phone, is_provisional=False, created_at=anchor - timedelta(days=30)))
    session.flush()
    for index, row in enumerate(DEMO_CASES):
        if session.get(Case, row[0]) is None:
            _seed_case(session, row, anchor, index)


def demo_report(anchor):
    names = {identifier: name for identifier, name, *_ in DEMO_PEOPLE}
    studies = {item["id"]: item["name"] for item in STUDIES}
    clinics = {item["id"]: item["name"].replace(" (demo)", "") for item in CLINICS}

    def table(headers, rows):
        return "\n".join([
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ])

    people = table(("Nombre", "Correo", "Teléfono", "Nacimiento"), (row[1:] for row in DEMO_PEOPLE))
    cases = table(("Folio", "Solicitante", "Paciente", "Estudio", "Clínica", "Estado", "Canales"), (
        (folio, names[requester], names[patient], studies[study], clinics.get(clinic, "—"),
         status + (" · abandonado" if abandoned else ""), " → ".join(route))
        for folio, requester, patient, study, clinic, status, abandoned, route in DEMO_CASES
    ))
    credentials = table(("Rol", "Usuario", "Contraseña"), (
        (role, username, password) for _, username, password, role in DEMO_USERS
    ))
    local_day = anchor.astimezone(MEXICO_CITY).date()
    tomorrow = (local_day + timedelta(days=1)).isoformat()
    last_day = (local_day + timedelta(days=3)).isoformat()
    return (f"# Datos de demo\n\n## Personas\n\n{people}\n\n## Trámites\n\n{cases}\n\n"
            f"## Credenciales ficticias\n\n{credentials}\n\n"
            f"Catálogo de demo con 45 horarios del {tomorrow} al {last_day}, de 09:00 a 13:00 hora de Ciudad de México por clínica.\n\n"
            "Ana no está sembrada. Quedan libres `ana.demo@example.com` y `+522220000001`.\n")
