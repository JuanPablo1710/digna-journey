from datetime import datetime, time, timedelta, timezone
from typing import TypedDict
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from .errors import APIError


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

router = APIRouter(prefix="/catalog", tags=["catalog"])
MEXICO_CITY = ZoneInfo("America/Mexico_City")


def get_demo_slots(now: datetime | None = None) -> list[dict[str, str]]:
    current = (now or datetime.now(timezone.utc)).astimezone(MEXICO_CITY)
    slots: list[dict[str, str]] = []
    for clinic in CLINICS:
        for day_offset in range(1, 4):
            slot_date = current.date() + timedelta(days=day_offset)
            for hour in range(9, 14):
                local_start = datetime.combine(slot_date, time(hour), tzinfo=MEXICO_CITY)
                starts_at = local_start.astimezone(timezone.utc)
                slots.append(
                    {
                        "id": f"SL-{clinic['id']}-{slot_date:%Y%m%d}-{hour:02d}",
                        "clinic_id": clinic["id"],
                        "starts_at": starts_at.isoformat().replace("+00:00", "Z"),
                    }
                )
    return slots


@router.get("/studies")
def list_studies() -> list[Study]:
    return STUDIES


@router.get("/clinics")
def list_clinics() -> list[Clinic]:
    return CLINICS


@router.get("/slots")
def list_slots(clinic_id: str = Query()) -> list[dict[str, str]]:
    if not any(clinic["id"] == clinic_id for clinic in CLINICS):
        raise APIError(404, "clinic_not_found", "La clínica solicitada no existe.")
    return [slot for slot in get_demo_slots() if slot["clinic_id"] == clinic_id]

