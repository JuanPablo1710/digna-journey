from datetime import datetime

from pydantic import ValidationError

from ...catalog import CLINICS, MEXICO_CITY, STUDIES
from ...db import SessionLocal
from ...errors import APIError
from ..resume import ConfirmData, RequestData, SelectData, _challenge, confirm_resume, request_resume, select_resume


ACTIONS = {"resume_menu", "resume_email", "resume_email_value", "resume_code", "resume_select"}


def _reply(text, replies=(), **state):
    return {
        "case": None, "events": [], "missing_steps": [], "trust_level": 0,
        "messages": [{"text": text, "quick_replies": list(replies)}],
        **state,
    }


def _choice(label, action, **payload):
    return {"label": label, "action": action, "payload": payload}


def _item_choice(item):
    study = next((entry["name"] for entry in STUDIES if entry["id"] == item["study_id"]), "Estudio por elegir")
    clinic = next((entry["name"] for entry in CLINICS if entry["id"] == item["clinic_id"]), "Clínica por elegir")
    patient = item["patient_name"] or "Paciente por indicar"
    status = item["status"].replace("_", " ")
    activity = datetime.fromisoformat(item["updated_at"]).astimezone(MEXICO_CITY).strftime("%d/%m %H:%M")
    return _choice(f"{study} · {clinic} · Para: {patient} · {status} · {item['channel']} · {activity} (CDMX)",
                   "resume_select", kind=item["kind"], id=item["id"], expected_version=item["version"])


def handle_chat_resume(request, cookie, channel_key, background, response):
    action = request.action
    if action == "resume_menu":
        return _reply("¿Cómo quieres retomar tu trámite?", [_choice("Con mi correo", "resume_email")])
    if action == "resume_email":
        return _reply("Escribe el correo del solicitante.", resume_input="email")
    try:
        if action == "resume_email_value":
            result = request_resume(RequestData(channel="whatsapp", email=request.content or "",
                                                 phone=request.identifier),
                                    background, response, cookie, channel_key)
            return _reply(result["message"] + " Escribe el código de seis dígitos.",
                          resume_input="code", resume_challenge_id=result["challenge_id"])
        challenge_id = request.data.get("resume_challenge_id")
        with SessionLocal() as session:
            challenge = _challenge(session, challenge_id, cookie)
            if challenge.channel != "whatsapp" or challenge.scope.get("phone") != request.identifier:
                raise APIError(403, "resume_denied", "No se pudo verificar la solicitud.")
        if action == "resume_code":
            result = confirm_resume(ConfirmData(challenge_id=challenge_id, code=request.content or ""), cookie)
            if not result["items"]:
                return _reply("No hay trámites ni borradores disponibles.")
            return _reply("Elige un trámite o borrador.", [_item_choice(item) for item in result["items"]])
        select_resume(SelectData(
            challenge_id=challenge_id, kind=request.data.get("kind"), id=request.data.get("id"),
            expected_version=request.data.get("expected_version"), idempotency_key=request.idempotency_key,
        ), cookie)
        return None  # The regular conversation renders the selected case or next draft question.
    except ValidationError as exc:
        raise APIError(422, "invalid_resume_input", "Revisa el dato e inténtalo de nuevo.") from exc
