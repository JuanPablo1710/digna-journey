from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...catalog import CLINICS, MEXICO_CITY, STUDIES, get_demo_slots
from ...models import Case, Event, Note, Person, User
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


def _supporting_events(session, folio, route, core):
    """Historical events only. They never grant verification or create live lockouts."""
    additions = []

    def record(kind, channel, when, *, actor_role=None, **payload):
        additions.append((kind, channel, when, payload, actor_role))

    first = core[0][2]
    record("consentimiento_aceptado", route[0], first - timedelta(minutes=25))
    for channel in route:
        channel_times = [when for _, current, when, _ in core if current == channel]
        entered = channel_times[0]
        record("canal_iniciado", channel, entered - timedelta(minutes=20))
        if channel == "web":
            continue
        if channel == "whatsapp":
            record("mensaje_recibido", channel, entered - timedelta(minutes=18), type="texto")
            record("mensaje_enviado", channel, entered - timedelta(minutes=17), type="texto")
            record("verificacion_solicitada", channel, entered - timedelta(minutes=15), method="email_otp")
            if folio in {"C-1002", "C-1005", "C-1006"}:
                attempts = 3 if folio == "C-1005" else 1
                for attempt in range(attempts):
                    record("verificacion_fallida", channel, entered - timedelta(minutes=14 - attempt),
                           method="email_otp", locked=attempt == 2)
            # The historical block in C-1005 ended before the later success.
            if folio == "C-1005":
                record("verificacion_solicitada", channel, entered - timedelta(minutes=1), method="email_otp")
                verified_at = entered - timedelta(seconds=2)
            else:
                verified_at = entered - timedelta(minutes=10)
            record("verificacion_exitosa", channel, verified_at, method="email_otp")
            record("identidad_vinculada", channel, verified_at + timedelta(seconds=1))
            record("mensaje_enviado", channel, channel_times[-1] + timedelta(minutes=1), type="texto")
        else:
            call_id = f"seed-call-{folio}"
            record("llamada_iniciada", channel, entered - timedelta(minutes=12), call_id=call_id)
            record("verificacion_solicitada", channel, entered - timedelta(minutes=10),
                   call_id=call_id, method="agent_assisted")
            record("verificacion_exitosa", channel, entered - timedelta(minutes=8),
                   call_id=call_id, method="agent_assisted")
            record("identidad_vinculada", channel, entered - timedelta(minutes=7), call_id=call_id)
            record("contexto_consultado", channel, entered - timedelta(minutes=5), call_id=call_id)
            note_id = f"N-SEED-{folio}"
            note_time = entered - timedelta(minutes=4)
            if session.get(Note, note_id) is None:
                session.add(Note(id=note_id, case_id=folio, author_user_id="U-0001",
                                 text="Seguimiento ficticio registrado por el asesor.", created_at=note_time))
            record("nota_agregada", channel, note_time, call_id=call_id)
            # Each simulated call finishes promptly, even when the case is abandoned later.
            last_action = max(when for kind, current, when, _ in core
                              if current == channel and kind != "tramite_abandonado")
            record("llamada_finalizada", channel, last_action + timedelta(minutes=3), call_id=call_id)
    denials = {
        "C-1001": ("web", "verification_required", "paciente"),
        "C-1003": ("web", "session_expired", "paciente"),
        "C-1007": ("callcenter", "role_denied", "admin"),
        "C-1008": ("callcenter", "verification_required", "asesor"),
    }
    if folio in denials:
        channel, reason, role = denials[folio]
        entered = next(when for _, current, when, _ in core if current == channel)
        record("acceso_denegado", channel, entered - timedelta(minutes=11),
               actor_role=role, reason=reason)
    return additions


def _seed_case(session, row, anchor, index):
    folio, requester, patient, study, clinic, status, abandoned, route = row
    start = anchor - timedelta(days=4 - index % 3, hours=index)
    if folio == "C-1007":
        start = anchor - timedelta(hours=8)
    existing = session.get(Case, folio)
    if existing is not None:
        start = existing.created_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
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
    timestamps = []
    for position, (kind, channel, _) in enumerate(events):
        same_call = position > 0 and channel == events[position - 1][1] == "callcenter"
        delay = 60 if kind == "tramite_abandonado" else 3 if same_call else 45
        timestamps.append(timestamps[-1] + timedelta(minutes=delay) if timestamps else start)
    if existing is None:
        session.add(Case(
            id=folio, requester_id=requester, patient_id=patient, relationship=relationship,
            study_id=study, clinic_id=clinic, slot_id=slot["id"] if slot else None,
            slot_datetime=datetime.fromisoformat(slot["starts_at"]) if slot else None,
            steps=steps, status=status, abandoned=abandoned, current_channel=route[-1],
            last_channel=route[-1], version=len(events), created_at=start, updated_at=timestamps[-1],
        ))
        session.flush()
    core = [(kind, channel, when, payload) for (kind, channel, payload), when in zip(events, timestamps)]
    history = [(f"evt_seed_{folio}_{position:02d}", kind, channel, when, payload, None)
               for position, (kind, channel, when, payload) in enumerate(core, 1)]
    history.extend((f"evt_seed_extra_{folio}_{position:02d}", *entry)
                   for position, entry in enumerate(_supporting_events(session, folio, route, core), 1))
    identifiers = {entry[0] for entry in history}
    stored = set(session.scalars(select(Event.event_id).where(Event.event_id.in_(identifiers))))
    result = []
    for event_id, kind, channel, timestamp, payload, actor_role in history:
        if event_id in stored:
            continue
        role = actor_role or ("asesor" if channel == "callcenter" else "paciente")
        actor_id = {"asesor": "U-0001", "admin": "U-0002"}.get(role, f"seed-{requester}")
        result.append(Event(
            event_id=event_id, type=kind, case_id=folio,
            person_id=requester, channel=channel, actor_id=actor_id,
            actor_role=role, timestamp=timestamp, payload=payload,
        ))
    return result


def seed_demo(session: Session, anchor=None) -> None:
    """Carga datos ficticios sin duplicar filas y deja el commit al llamador."""
    anchor = anchor or demo_day()
    for identifier, username, password, role in DEMO_USERS:
        if session.get(User, identifier) is None and session.scalar(select(User.id).where(User.username == username)) is None:
            session.add(User(id=identifier, username=username, password_hash=hash_password(password), role=role))
    for identifier, name, email, phone, birth in DEMO_PEOPLE:
        if session.get(Person, identifier) is None:
            session.add(Person(id=identifier, full_name=name, birth_date=date.fromisoformat(birth),
                               email=email, phone=phone, is_provisional=False, created_at=anchor - timedelta(days=30)))
    session.flush()
    events = [event for index, row in enumerate(DEMO_CASES) for event in _seed_case(session, row, anchor, index)]
    session.add_all(sorted(events, key=lambda event: (event.timestamp, event.event_id)))


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
            "## Historial de ejemplo\n\n"
            "- C-1002, C-1005 y C-1006 incluyen mensajes de WhatsApp e intentos de verificación fallidos. C-1005 incluye un bloqueo histórico.\n"
            "- C-1007, C-1008 y C-1009 incluyen llamadas terminadas, consultas de contexto y notas internas ficticias.\n"
            "- C-1001, C-1003, C-1007 y C-1008 incluyen accesos denegados por verificación, sesión vencida o rol.\n"
            "- El historial se fecha en los días anteriores al reset. Los mensajes registran solo el tipo y las verificaciones históricas no habilitan acceso.\n\n"
            "Ana no está sembrada. Quedan libres `ana.demo@example.com` y `+522220000001`.\n")
