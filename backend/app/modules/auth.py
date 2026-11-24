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
from ..models import User
from ..security import verify_hash


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


def require_staff_role(role: str):
    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
        if credentials is None:
            raise APIError(401, "authentication_required", "Inicia sesión para continuar.")
        try:
            claims = jwt.decode(
                credentials.credentials, settings.jwt_secret,
                algorithms=["HS256"], options={"require": ["sub", "role", "exp"]},
            )
        except jwt.InvalidTokenError as exc:
            raise APIError(401, "invalid_token", "La sesión no es válida o expiró.") from exc
        if claims["role"] != role:
            raise APIError(403, "role_denied", "Tu rol no permite realizar esta acción.")
        with SessionLocal() as session:
            user = session.get(User, claims["sub"])
            if user is None or user.role != role:
                raise APIError(403, "role_denied", "Tu rol no permite realizar esta acción.")
            if (not user.password_hash or
                    claims.get("credential_version") != sha256(user.password_hash.encode()).hexdigest()):
                raise APIError(401, "invalid_token", "La sesión ya no está vigente. Inicia sesión de nuevo.")
            return user

    return authorize


require_agent = require_staff_role("asesor")
require_admin = require_staff_role("admin")
