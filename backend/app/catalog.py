from datetime import datetime, time, timedelta, timezone
from typing import TypedDict


class Study(TypedDict):
    id: str
    name: str
    price: int
    preparation: str


class Clinic(TypedDict):
    id: str
    name: str


STUDIES: list[Study] = [
    {"id": "ST-001", "name": "Biometría hemática", "price": 180, "preparation": "Ayuno ficticio de 8 horas."},
    {"id": "ST-002", "name": "Química sanguínea", "price": 250, "preparation": "Ayuno ficticio de 8 horas y beber agua simple."},
    {"id": "ST-003", "name": "Ultrasonido abdominal", "price": 420, "preparation": "Ayuno ficticio de 6 horas."},
    {"id": "ST-004", "name": "Radiografía de tórax", "price": 300, "preparation": "Retirar objetos metálicos del área; indicación ficticia."},
    {"id": "ST-005", "name": "Examen general de orina", "price": 120, "preparation": "Recolectar la primera muestra del día; indicación ficticia."},
]

CLINICS: list[Clinic] = [
    {"id": "CL-001", "name": "Clínica Puebla Centro (demo)"},
    {"id": "CL-002", "name": "Clínica Puebla Angelópolis (demo)"},
    {"id": "CL-003", "name": "Clínica Cholula (demo)"},
]


def get_demo_slots(now: datetime | None = None) -> list[dict[str, str]]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    slots: list[dict[str, str]] = []
    for clinic in CLINICS:
        for day_offset in range(1, 4):
            slot_date = current.date() + timedelta(days=day_offset)
            for hour in range(9, 14):
                starts_at = datetime.combine(slot_date, time(hour), tzinfo=timezone.utc)
                slots.append(
                    {
                        "id": f"SL-{clinic['id']}-{slot_date:%Y%m%d}-{hour:02d}",
                        "clinic_id": clinic["id"],
                        "starts_at": starts_at.isoformat().replace("+00:00", "Z"),
                    }
                )
    return slots

