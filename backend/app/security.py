import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

from .config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_hash(value: str, value_hash: str) -> bool:
    return bcrypt.checkpw(value.encode("utf-8"), value_hash.encode("utf-8"))


def create_patient_token(person_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": person_id, "role": "paciente", "iat": now, "exp": now + timedelta(hours=8)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def mask_name(value: str | None) -> str:
    if not value:
        return "Contacto sin registrar"
    parts = value.strip().split()
    first = f"{parts[0][0]}***" if parts and parts[0] else "***"
    last = f" {parts[-1][0]}." if len(parts) > 1 and parts[-1] else ""
    return f"{first}{last}"


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return "Correo sin registrar"
    local, domain = value.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def mask_phone(value: str | None) -> str:
    if not value:
        return "Teléfono sin registrar"
    return f"***{value[-4:]}"


def masked_person(person) -> dict[str, str] | None:
    """Allowlisted projection shared by dashboard, audit and SSE."""
    if person is None:
        return None
    return {
        "name": mask_name(person.full_name),
        "phone": mask_phone(person.phone),
        "email": mask_email(person.email),
    }

