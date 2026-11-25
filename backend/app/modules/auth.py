from datetime import datetime, timedelta, timezone
from hashlib import sha256

import jwt
from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..errors import APIError
from ..models import Person, User
from ..security import verify_hash
from .events import append_event


router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class LoginData(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=72)


@router.post("/login")
def login(data: LoginData) -> dict[str, str]:
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == data.username))
        if (
            user is None
            or user.role not in {"asesor", "admin"}
            or not user.password_hash
            or len(data.password.encode("utf-8")) > 72
            or not verify_hash(data.password, user.password_hash)
        ):
            raise APIError(401, "invalid_credentials", "Usuario o contraseña incorrectos.")
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {"sub": user.id, "role": user.role, "iat": now, "exp": now + timedelta(hours=8),
             "credential_version": sha256(user.password_hash.encode()).hexdigest()},
            settings.jwt_secret,
            algorithm="HS256",
        )
        return {"access_token": token, "role": user.role}


def _token_claims(credentials):
    if credentials is None:
        raise APIError(401, "authentication_required", "Inicia sesión para continuar.")
    try:
        claims = jwt.decode(
            credentials.credentials, settings.jwt_secret,
            algorithms=["HS256"], options={"require": ["sub", "role", "exp"]},
        )
    except jwt.InvalidTokenError as exc:
        raise APIError(401, "invalid_token", "La sesión no es válida o expiró.") from exc
    if not isinstance(claims["role"], str):
        raise APIError(401, "invalid_token", "La sesión no es válida o expiró.")
    return claims


def validate_staff(session, credentials, roles):
    claims = _token_claims(credentials)
    if claims["role"] not in roles:
        raise APIError(403, "role_denied", "Tu rol no permite realizar esta acción.")
    user = session.get(User, claims["sub"])
    if user is None or user.role != claims["role"]:
        raise APIError(403, "role_denied", "Tu rol no permite realizar esta acción.")
    if (not user.password_hash or
            claims.get("credential_version") != sha256(user.password_hash.encode()).hexdigest()):
        raise APIError(401, "invalid_token", "La sesión ya no está vigente. Inicia sesión de nuevo.")
    return user


def audit_staff_denial(session, credentials, channel, reason, *, case=None):
    claims = _token_claims(credentials)
    role, subject = claims["role"], claims["sub"]
    if role not in {"admin", "asesor", "paciente"}:
        return
    actor = session.get(Person if role == "paciente" else User, subject)
    append_event(
        session, event_type="acceso_denegado", channel=channel, actor_role=role,
        actor_id=actor.id if actor is not None else "anonymous",
        case_id=case.id if case else None,
        person_id=case.requester_id if case else actor.id if actor and role == "paciente" else None,
        payload={"reason": reason},
    )


def require_staff_role(role: str):
    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
        with SessionLocal() as session:
            try:
                return validate_staff(session, credentials, {role})
            except APIError as exc:
                if exc.status_code == 403:
                    audit_staff_denial(session, credentials, "admin" if role == "admin" else "callcenter", exc.error)
                    session.commit()
                raise

    return authorize


require_agent = require_staff_role("asesor")
require_admin = require_staff_role("admin")
