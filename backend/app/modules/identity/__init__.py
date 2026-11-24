
from fastapi import APIRouter, Cookie, Response

from ...db import SessionLocal
from ...errors import APIError
from ...schemas import VerificationConfirmData, VerificationRequestData
from .service import confirm_verification, request_verification


router = APIRouter(prefix="/identity", tags=["identity"])
SESSION_COOKIE = "web_session"


def _raise_service_error(result: dict) -> None:
    error = result.get("_error")
    if error:
        status_code, code, message, extra = error
        raise APIError(status_code, code, message, extra)


@router.post("/verify/request")
def request_identity_verification(
    data: VerificationRequestData,
    web_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    if data.channel == "web" and not web_session:
        raise APIError(403, "web_session_required", "Inicia una sesión web antes de verificar el correo.")
    with SessionLocal() as session:
        with session.begin():
            result = request_verification(
                session,
                channel=data.channel,
                identifier=data.identifier,
                method=data.method,
                birth_date=data.birth_date,
            )
        _raise_service_error(result)
        return result


@router.post("/verify/confirm")
def confirm_identity_verification(
    data: VerificationConfirmData,
    response: Response,
    web_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
):
    with SessionLocal() as session:
        with session.begin():
            result = confirm_verification(
                session,
                channel=data.channel,
                identifier=data.identifier,
                code=data.code,
                web_session=web_session,
            )
        _raise_service_error(result)
    new_session = result.pop("_new_session", None)
    if new_session:
        response.set_cookie(
            SESSION_COOKIE,
            new_session,
            max_age=1800,
            httponly=True,
            samesite="lax",
        )
        result["session_identifier"] = new_session
    return result
