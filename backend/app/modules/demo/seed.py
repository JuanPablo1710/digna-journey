from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...catalog import get_demo_slots
from ...models import Case, Person, User
from ...security import hash_password


DEMO_USERS = (
    {"id": "U-0001", "username": "asesor", "password": "Asesor#2026", "role": "asesor"},
    {"id": "U-0002", "username": "admin", "password": "Admin#2026", "role": "admin"},
)

DEMO_PEOPLE = (
    {
        "id": "P-1001",
        "full_name": "Luis Demo",
        "birth_date": "1985-04-12",
        "email": "luis.demo@example.com",
        "phone": "+522221111111",
    },
    {
        "id": "P-1002",
        "full_name": "Marta Demo",
        "birth_date": "1982-08-20",
        "email": "marta.demo@example.com",
        "phone": "+522229999999",
    },
    {
        "id": "P-1003",
        "full_name": "Pablo Demo",
        "birth_date": "2012-03-15",
        "email": "pablo.demo@example.com",
        "phone": "+522229999999",
    },
)


def seed_demo(session: Session) -> None:
    """Carga datos ficticios de forma idempotente."""
    for demo_user in DEMO_USERS:
        exists = session.scalar(select(User).where(User.username == demo_user["username"]))
        if exists is None:
            session.add(
                User(
                    id=demo_user["id"],
                    username=demo_user["username"],
                    password_hash=hash_password(demo_user["password"]),
                    role=demo_user["role"],
                    person_id=None,
                )
            )

    for demo_person in DEMO_PEOPLE:
        if session.get(Person, demo_person["id"]) is None:
            session.add(
                Person(
                    id=demo_person["id"],
                    full_name=demo_person["full_name"],
                    birth_date=datetime.strptime(demo_person["birth_date"], "%Y-%m-%d").date(),
                    email=demo_person["email"],
                    phone=demo_person["phone"],
                    is_provisional=False,
                )
            )
    session.flush()

    if session.get(Case, "C-1001") is None:
        session.add(
            Case(
                id="C-1001",
                requester_id="P-1001",
                patient_id="P-1001",
                relationship="self",
                study_id="ST-003",
                clinic_id="CL-001",
                steps={"study": True, "patient_data": True, "clinic": True, "slot": False, "confirmed": False},
                status="clinica_elegida",
                abandoned=True,
                current_channel="web",
                last_channel="web",
                version=1,
            )
        )
    if session.get(Case, "C-1002") is None:
        session.add(
            Case(
                id="C-1002",
                requester_id="P-1002",
                patient_id="P-1002",
                relationship="self",
                study_id="ST-001",
                steps={"study": True, "patient_data": False, "clinic": False, "slot": False, "confirmed": False},
                status="cotizando",
                abandoned=False,
                current_channel="web",
                last_channel="web",
                version=1,
            )
        )
    if session.get(Case, "C-1003") is None:
        slot = get_demo_slots()[0]
        session.add(
            Case(
                id="C-1003",
                requester_id="P-1003",
                patient_id="P-1003",
                relationship="self",
                study_id="ST-004",
                clinic_id=slot["clinic_id"],
                slot_id=slot["id"],
                slot_datetime=datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00")),
                steps={"study": True, "patient_data": True, "clinic": True, "slot": True, "confirmed": False},
                status="horario_propuesto",
                abandoned=False,
                current_channel="web",
                last_channel="web",
                version=1,
            )
        )
    session.commit()

