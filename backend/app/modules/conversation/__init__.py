
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...catalog import CLINICS, STUDIES, get_demo_slots
from ...errors import APIError
from ...models import Case, ChannelIdentity, Event, Person, Verification
from ...schemas import InteractionRequest
from ..cases import case_view, change_channel, check_version, create_case, missing_steps, update_case
from ..events import append_event
from ..drafts import discard_draft_record, save_draft_record
from ..identity.service import (
    VERIFICATION_TTL,
    aware,
    confirm_verification,
    new_id,
    normalize_birth_date,
    normalize_email,
    recognize_identity,
    request_verification,
    trust_level,
    utc_now,
)


def _identity(session: Session, identifier: str) -> ChannelIdentity | None:
    return session.scalar(
        select(ChannelIdentity).where(
            ChannelIdentity.channel == "whatsapp",
            ChannelIdentity.identifier == identifier,
        )
    )


def _conversation(identity: ChannelIdentity | None) -> dict[str, Any]:
    if identity is None:
        return {}
    value = (identity.session_state or {}).get("conversation")
    return dict(value) if isinstance(value, dict) else {}


def _save_conversation(identity: ChannelIdentity, conversation: dict[str, Any]) -> None:
    identity.session_state = {**(identity.session_state or {}), "conversation": conversation}


def _quick(label: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"label": label, "action": action, "payload": payload or {}}


def _message(text: str, quick_replies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"text": text, "quick_replies": quick_replies or []}


def _initial_messages() -> list[dict[str, Any]]:
    return [
        _message(
            "Hola. Esta es una demostración con datos ficticios. Al continuar aceptas el aviso de privacidad simulado.",
            [
                _quick("Cotizar estudio", "start_quote"),
                _quick("Agendar cita", "start_booking"),
            ],
        )
    ]


def _study_replies(case: Case | None = None) -> list[dict[str, Any]]:
    return [
        _quick(
            study["name"],
            "select_study",
            {
                "study_id": study["id"],
                **({"case_id": case.id, "expected_version": case.version} if case else {}),
            },
        )
        for study in STUDIES
    ]


def _clinic_replies(case: Case) -> list[dict[str, Any]]:
    return [
        _quick(
            clinic["name"],
            "select_clinic",
            {"case_id": case.id, "expected_version": case.version, "clinic_id": clinic["id"]},
        )
        for clinic in CLINICS
    ]


def _slot_replies(case: Case) -> list[dict[str, Any]]:
    if not case.clinic_id:
        return []
    slots = [slot for slot in get_demo_slots() if slot["clinic_id"] == case.clinic_id]
    return [
        _quick(
            datetime.fromisoformat(slot["starts_at"].replace("Z", "+00:00")).strftime("%d/%m %H:%M"),
            "select_slot",
            {"case_id": case.id, "expected_version": case.version, "slot_id": slot["id"]},
        )
        for slot in slots[:6]
    ]


def _active_case(session: Session, person_id: str | None) -> Case | None:
    selected = session.info.get("resume_case_ids")
    if selected:
        case = session.get(Case, selected[-1])
        if case is not None and case.status != "cancelado":
            return case
    if person_id is None:
        return None
    return session.scalar(
        select(Case)
        .where(Case.requester_id == person_id, Case.status != "cancelado")
        .order_by(Case.created_at.desc())
        .limit(1)
    )


def _case_trust(session, channel, identifier, case=None):
    if case is not None and case.id in session.info.get("resume_case_ids", []):
        return 2
    return trust_level(session, channel=channel, identifier=identifier, case=case)


def _summary(case: Case) -> str:
    study = next((item["name"] for item in STUDIES if item["id"] == case.study_id), "estudio por elegir")
    clinic = next((item["name"] for item in CLINICS if item["id"] == case.clinic_id), "clínica por elegir")
    missing = missing_steps(case.steps)
    missing_labels = {
        "study": "estudio",
        "patient_data": "datos del paciente",
        "clinic": "clínica",
        "slot": "horario",
        "confirmed": "confirmación",
    }
    pending = ", ".join(missing_labels[item] for item in missing) if missing else "ninguno"
    return f"Tu trámite es {study} en {clinic}. Falta: {pending}."


def _case_prompt(case: Case) -> list[dict[str, Any]]:
    pending = missing_steps(case.steps)
    if not pending:
        return [_message(_summary(case), [_quick("Empezar otro trámite", "new_case"), _quick("Hablar con un asesor", "talk_to_agent")])]
    next_step = pending[0]
    if next_step == "study":
        return [_message("Elige el estudio que necesitas:", _study_replies(case))]
    if next_step == "patient_data":
        return [_message("Faltan los datos del paciente para continuar.")]
    if next_step == "clinic":
        return [_message("Elige una clínica:", _clinic_replies(case))]
    if next_step == "slot":
        return [_message("Elige un horario:", _slot_replies(case))]
    return [
        _message(
            _summary(case),
            [_quick("Confirmar cita", "confirm_case", {"case_id": case.id, "expected_version": case.version})],
        )
    ]


def _recognized_prompt(person: Person) -> list[dict[str, Any]]:
    name = person.full_name or "Contacto sin registrar"
    return [_message(f"Hola {name}. Tienes un trámite pendiente. Para continuar necesito verificar que eres tú. ¿Cuál es tu fecha de nacimiento?")]


def _input_value(request: InteractionRequest) -> str:
    value = request.data.get("value") if request.kind == "action" else request.content
    return str(value or "").strip()


def _received_type(request: InteractionRequest, stage: str | None) -> str:
    value = _input_value(request)
    if stage in {"awaiting_dob", "collect_birth_date", "collect_patient_birth_date"} or re.fullmatch(
        r"(?:\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", value
    ):
        return "dob_enviada"
    if stage == "awaiting_otp" or (len(value) == 6 and value.isdigit()):
        return "otp_enviado"
    return "accion" if request.kind == "action" else "texto"


def _response(
    session: Session,
    *,
    identity: ChannelIdentity | None,
    case: Case | None,
    level: int,
    messages: list[dict[str, Any]],
    event_types: list[str] | None = None,
) -> dict[str, Any]:
    if case is None:
        case_data = None
        missing: list[str] = []
    elif level >= 2:
        case_data = case_view(session, case)
        missing = missing_steps(case.steps)
    else:
        case_data = {"id": case.id, "pending": True}
        missing = []
    return {
        "trust_level": level,
        "case": case_data,
        "missing_steps": missing,
        "messages": messages,
        "events": event_types or [],
    }


def reset_conversation(session: Session, identifier: str, *, demo_mode: bool) -> dict[str, Any]:
    if not demo_mode:
        raise APIError(403, "demo_mode_required", "Reiniciar la conversación solo está disponible en modo demo.")
    now = utc_now()
    identity = _identity(session, identifier)
    if identity is not None:
        discard_draft_record(session, identity)
        identity.session_state = {}
        identity.last_seen_at = now
    verifications = session.scalars(
        select(Verification).where(
            Verification.channel == "whatsapp",
            Verification.identifier == identifier,
            Verification.valid_until.is_not(None),
            Verification.valid_until > now,
        )
    ).all()
    for verification in verifications:
        verification.valid_until = now
    level = 1 if identity is not None and identity.person_id is not None else 0
    return _response(session, identity=identity, case=None, level=level, messages=_initial_messages())


def _expire_origin_if_needed(identity: ChannelIdentity) -> None:
    state = dict(identity.session_state or {})
    if state.get("started_unknown") is not True:
        return
    if utc_now() - aware(identity.last_seen_at) <= VERIFICATION_TTL:
        return
    state["origin_case_ids"] = []
    state["origin_expired"] = True
    identity.session_state = state


def _first_contact(session: Session, identifier: str, person_id: str | None) -> None:
    exists = session.scalar(
        select(Event.seq).where(
            Event.channel == "whatsapp",
            Event.actor_id == identifier,
            Event.type == "canal_iniciado",
        )
    )
    if exists is not None:
        return
    append_event(session, event_type="canal_iniciado", channel="whatsapp", actor_id=identifier, person_id=person_id)
    append_event(
        session,
        event_type="consentimiento_aceptado",
        channel="whatsapp",
        actor_id=identifier,
        person_id=person_id,
        payload={"accepted_at": utc_now().isoformat().replace("+00:00", "Z")},
    )


def _finish_unknown_profile(
    session: Session,
    identity: ChannelIdentity,
    conversation: dict[str, Any],
) -> tuple[Case, list[dict[str, Any]]]:
    data = conversation.get("data", {})
    requester = session.get(Person, identity.person_id)
    requester.full_name = data["full_name"]
    requester.birth_date = normalize_birth_date(data["birth_date"])
    requester.email = normalize_email(data["email"])
    relationship = data["relationship"]
    if relationship == "self":
        patient = requester
    else:
        patient = Person(
            id=new_id("P"),
            full_name=data["patient_name"],
            birth_date=normalize_birth_date(data["patient_birth_date"]),
            email=None,
            phone=None,
            is_provisional=True,
        )
        session.add(patient)
    case, _ = create_case(
        session,
        requester=requester,
        patient=patient,
        relationship=relationship,
        channel="whatsapp",
        actor_id=identity.identifier,
    )
    state = dict(identity.session_state or {})
    origin_case_ids = list(state.get("origin_case_ids", []))
    origin_case_ids.append(case.id)
    state.update({"started_unknown": True, "origin_case_ids": origin_case_ids})
    conversation = {"stage": "choosing_study", "case_id": case.id, "data": {}}
    state["conversation"] = conversation
    identity.session_state = state
    return case, [_message("Tus datos quedaron guardados. Ahora elige un estudio:", _study_replies(case))]


def _collect_unknown_data(
    session: Session,
    identity: ChannelIdentity,
    request: InteractionRequest,
) -> tuple[Case | None, list[dict[str, Any]]]:
    conversation = _conversation(identity)
    stage = conversation.get("stage") or "collect_full_name"
    data = dict(conversation.get("data") or {})
    value = _input_value(request)

    if stage == "collect_full_name":
        if len(value) < 2:
            return None, [_message("Escribe tu nombre completo.")]
        data["full_name"] = value
        next_stage, prompt = "collect_birth_date", "¿Cuál es tu fecha de nacimiento? Escríbela como DD/MM/AAAA."
    elif stage == "collect_birth_date":
        try:
            data["birth_date"] = normalize_birth_date(value).isoformat()
        except APIError:
            return None, [_message("La fecha no es válida. Escríbela como DD/MM/AAAA.")]
        next_stage, prompt = "collect_email", "¿Cuál es tu correo electrónico?"
    elif stage == "collect_email":
        try:
            data["email"] = normalize_email(value)
        except APIError:
            return None, [_message("El correo no es válido. Inténtalo de nuevo.")]
        next_stage, prompt = "collect_for_whom", "¿Para quién es el estudio?"
    elif stage == "collect_for_whom":
        normalized = value.lower()
        if normalized in {"self", "para mí", "para mi", "mi"}:
            data["relationship"] = "self"
            conversation.update({"stage": "complete", "data": data})
            _save_conversation(identity, conversation)
            return _finish_unknown_profile(session, identity, conversation)
        if normalized in {"other", "otra", "otra persona"}:
            next_stage, prompt = "collect_relationship", "Indica el parentesco."
        else:
            return None, [_message("¿Para quién es el estudio?", [_quick("Para mí", "answer", {"value": "self"}), _quick("Otra persona", "answer", {"value": "other"})])]
    elif stage == "collect_relationship":
        relationships = {
            "hijo_a": "hijo_a",
            "hijo": "hijo_a",
            "hija": "hijo_a",
            "madre_padre": "madre_padre",
            "madre": "madre_padre",
            "padre": "madre_padre",
            "pareja": "pareja",
            "otro": "otro",
        }
        relationship = relationships.get(value.lower())
        if relationship is None:
            return None, [_message("Elige el parentesco:", [_quick("Hijo o hija", "answer", {"value": "hijo_a"}), _quick("Madre o padre", "answer", {"value": "madre_padre"}), _quick("Pareja", "answer", {"value": "pareja"}), _quick("Otro", "answer", {"value": "otro"})])]
        data["relationship"] = relationship
        next_stage, prompt = "collect_patient_name", "¿Cuál es el nombre completo del paciente?"
    elif stage == "collect_patient_name":
        if len(value) < 2:
            return None, [_message("Escribe el nombre completo del paciente.")]
        data["patient_name"] = value
        next_stage, prompt = "collect_patient_birth_date", "¿Cuál es la fecha de nacimiento del paciente? Usa DD/MM/AAAA."
    elif stage == "collect_patient_birth_date":
        try:
            data["patient_birth_date"] = normalize_birth_date(value).isoformat()
        except APIError:
            return None, [_message("La fecha no es válida. Escríbela como DD/MM/AAAA.")]
        conversation.update({"stage": "complete", "data": data})
        _save_conversation(identity, conversation)
        return _finish_unknown_profile(session, identity, conversation)
    else:
        return None, [_message("No te entendí. Elige una opción:", [_quick("Cotizar estudio", "start_quote"), _quick("Agendar cita", "start_booking")])]

    conversation.update({"stage": next_stage, "data": data})
    _save_conversation(identity, conversation)
    if next_stage == "collect_for_whom":
        return None, [_message(prompt, [_quick("Para mí", "answer", {"value": "self"}), _quick("Otra persona", "answer", {"value": "other"})])]
    if next_stage == "collect_relationship":
        return None, [_message(prompt, [_quick("Hijo o hija", "answer", {"value": "hijo_a"}), _quick("Madre o padre", "answer", {"value": "madre_padre"}), _quick("Pareja", "answer", {"value": "pareja"}), _quick("Otro", "answer", {"value": "otro"})])]
    return None, [_message(prompt)]


def _request_otp_after_dob(
    session: Session,
    identifier: str,
    birth_date_value: str,
) -> tuple[ChannelIdentity | None, list[dict[str, Any]], bool]:
    try:
        birth_date = normalize_birth_date(birth_date_value)
    except APIError:
        return _identity(session, identifier), [_message("La fecha no es válida. Escríbela como DD/MM/AAAA.")], False
    dob_result = request_verification(
        session,
        channel="whatsapp",
        identifier=identifier,
        method="dob_check",
        birth_date=birth_date,
    )
    if dob_result.get("_error"):
        return _identity(session, identifier), [_message(dob_result["_error"][2] + " Inténtalo de nuevo.")], False
    session.flush()
    otp_result = request_verification(
        session,
        channel="whatsapp",
        identifier=identifier,
        method="email_otp",
    )
    identity = _identity(session, identifier)
    conversation = _conversation(identity)
    conversation["stage"] = "awaiting_otp"
    _save_conversation(identity, conversation)
    return identity, [_message(f"Enviamos un código al correo {otp_result['masked_email']}. Escríbelo aquí. Nunca lo enviamos por WhatsApp.")], True


def _confirm_otp(
    session: Session,
    identity: ChannelIdentity,
    code: str,
) -> tuple[Case | None, list[dict[str, Any]], bool]:
    if len(code) != 6 or not code.isdigit():
        return None, [_message("El código debe tener 6 dígitos.")], False
    result = confirm_verification(session, channel="whatsapp", identifier=identity.identifier, code=code)
    error = result.get("_error")
    if error:
        _, error_code, message, extra = error
        if "attempts_remaining" in extra:
            message += f" Intentos restantes: {extra['attempts_remaining']}."
        if error_code == "temporarily_locked":
            message = "La verificación está bloqueada temporalmente. Intenta más tarde."
        return None, [_message(message)], False
    conversation = _conversation(identity)
    conversation["stage"] = "verified"
    _save_conversation(identity, conversation)
    case = _active_case(session, identity.person_id)
    if case is None:
        return None, [_message("Identidad verificada. Puedes empezar un trámite nuevo.", [_quick("Agendar cita", "new_case")])], True
    return case, [_message(_summary(case), [_quick("Continuar", "continue_case"), _quick("Empezar otro trámite", "new_case"), _quick("Hablar con un asesor", "talk_to_agent")])], True


def _handle(
    session: Session,
    request: InteractionRequest,
    recognition: dict[str, Any],
    identity: ChannelIdentity | None,
) -> tuple[ChannelIdentity | None, Case | None, int, list[dict[str, Any]]]:
    conversation = _conversation(identity)
    stage = conversation.get("stage")
    value = _input_value(request)

    if session.info.get("resume_case_ids") and request.action == "continue_case":
        selected = _active_case(session, None)
        if selected is not None:
            return identity, selected, 2, _case_prompt(selected)
    if request.action == "continue_case" and stage and stage.startswith("collect_"):
        case, messages = _collect_unknown_data(session, identity, request.model_copy(update={"data": {}}))
        return identity, case, 0, messages
    if identity and (identity.session_state or {}).get("draft_transferred"):
        if request.action == "start_booking" or (request.kind == "message" and value.lower() == "agendar"):
            identity.session_state = {key: val for key, val in identity.session_state.items() if key != "draft_transferred"}
        else:
            return identity, None, 0, _initial_messages()

    if recognition["state"] == "ambiguous":
        if value and (stage == "awaiting_dob" or "/" in value or "-" in value):
            identity, messages, _ = _request_otp_after_dob(session, request.identifier, value)
            return identity, None, 1 if identity else 0, messages
        return None, None, 0, [_message("Hay más de una persona con este teléfono. Escribe tu fecha de nacimiento como DD/MM/AAAA para identificarte.")]

    person = session.get(Person, identity.person_id) if identity and identity.person_id else None
    active_case = _active_case(session, identity.person_id if identity else None)
    level = _case_trust(session, channel="whatsapp", identifier=request.identifier, case=active_case)

    if stage == "awaiting_dob" and level < 2:
        identity, messages, _ = _request_otp_after_dob(session, request.identifier, value)
        return identity, active_case, 1, messages
    if stage == "awaiting_otp" and level < 2:
        case, messages, succeeded = _confirm_otp(session, identity, value)
        return identity, case or active_case, 2 if succeeded else 1, messages

    if request.kind == "message":
        lowered = value.lower()
        if stage and stage.startswith("collect_"):
            case, messages = _collect_unknown_data(session, identity, request)
            level = trust_level(session, channel="whatsapp", identifier=request.identifier, case=case)
            return identity, case, level, messages
        if "cotizar" in lowered:
            request = request.model_copy(update={"kind": "action", "action": "start_quote"})
        elif "agendar" in lowered:
            request = request.model_copy(update={"kind": "action", "action": "start_booking"})
        elif "continuar" in lowered:
            request = request.model_copy(update={"kind": "action", "action": "continue_case"})
        elif "asesor" in lowered:
            request = request.model_copy(update={"kind": "action", "action": "talk_to_agent"})
        elif "cancelar" in lowered and active_case and level >= 2:
            return identity, active_case, level, [_message("¿Deseas cancelar este trámite?", [_quick("Confirmar cancelación", "cancel_case", {"case_id": active_case.id, "expected_version": active_case.version})])]
        elif "hola" in lowered or not lowered:
            if recognition["state"] == "unknown":
                return identity, None, 0, _initial_messages()
            if level < 2:
                conversation["stage"] = "awaiting_dob"
                _save_conversation(identity, conversation)
                return identity, active_case, 1, _recognized_prompt(person)
            return identity, active_case, 2, [_message(_summary(active_case), [_quick("Continuar", "continue_case"), _quick("Empezar otro trámite", "new_case"), _quick("Hablar con un asesor", "talk_to_agent")])] if active_case else [_message("No tienes un trámite activo.", [_quick("Agendar cita", "new_case")])]
        else:
            return identity, active_case, level, [_message("No te entendí. Elige una opción:", [_quick("Cotizar estudio", "start_quote"), _quick("Agendar cita", "start_booking")])]

    action = request.action
    if action == "start_quote":
        return identity, None, level, [_message("Elige un estudio para ver su precio ficticio:", _study_replies())]
    if action == "start_booking":
        if recognition["state"] == "unknown":
            conversation = {"stage": "collect_full_name", "data": {}}
            _save_conversation(identity, conversation)
            return identity, None, 0, [_message("Para agendar, escribe tu nombre completo.")]
        if level < 2:
            conversation["stage"] = "awaiting_dob"
            _save_conversation(identity, conversation)
            return identity, active_case, 1, _recognized_prompt(person)
        action = "new_case"
    if action == "talk_to_agent":
        return identity, active_case, level, [_message("La atención con asesor estará disponible en la siguiente etapa de esta demo.")]
    if action == "continue_case":
        if level < 2 or active_case is None:
            if recognition["state"] == "recognized":
                conversation["stage"] = "awaiting_dob"
                _save_conversation(identity, conversation)
                return identity, active_case, 1, _recognized_prompt(person)
            return identity, None, 0, _initial_messages()
        return identity, active_case, 2, _case_prompt(active_case)
    if action == "new_case":
        if level < 2:
            return identity, active_case, level, _recognized_prompt(person) if person and person.full_name else _initial_messages()
        if person is None or not person.full_name or not person.birth_date:
            return identity, active_case, level, [_message("Elige Agendar cita para iniciar un trámite con este número.")]
        new_case, _ = create_case(session, requester=person, patient=person, relationship="self", channel="whatsapp", actor_id=request.identifier)
        state = dict(identity.session_state or {})
        if state.get("started_unknown") is True:
            state["origin_case_ids"] = [*state.get("origin_case_ids", []), new_case.id]
            identity.session_state = state
        conversation = {"stage": "choosing_study", "case_id": new_case.id, "data": {}}
        _save_conversation(identity, conversation)
        return identity, new_case, 2, [_message("Empecemos otro trámite. Elige un estudio:", _study_replies(new_case))]
    if action == "select_study" and not request.data.get("case_id"):
        study = next((item for item in STUDIES if item["id"] == request.data.get("study_id")), None)
        if study is None:
            raise APIError(404, "study_not_found", "El estudio solicitado no existe.")
        return identity, None, level, [_message(f"{study['name']}: ${study['price']} MXN. {study['preparation']}", [_quick("Agendar cita", "start_booking")])]
    if action in {"select_study", "select_clinic", "select_slot", "confirm_case"}:
        case = session.get(Case, request.data.get("case_id"))
        if case is None:
            raise APIError(404, "case_not_found", "El trámite solicitado no existe.")
        level = _case_trust(session, channel="whatsapp", identifier=request.identifier, case=case)
        if identity is None or level < 2:
            raise APIError(403, "verification_required", "Necesitas verificar tu identidad para continuar.")
        update_case(
            session,
            case,
            action=action,
            expected_version=int(request.data.get("expected_version", 0)),
            channel="whatsapp",
            actor_id=request.identifier,
            idempotency_key=None,
            study_id=request.data.get("study_id"),
            clinic_id=request.data.get("clinic_id"),
            slot_id=request.data.get("slot_id"),
        )
        identity.last_seen_at = utc_now()
        return identity, case, 2, _case_prompt(case)
    if action == "cancel_case":
        case = session.get(Case, request.data.get("case_id"))
        if case is None:
            raise APIError(404, "case_not_found", "El trámite solicitado no existe.")
        level = _case_trust(session, channel="whatsapp", identifier=request.identifier, case=case)
        if identity is None or level < 2:
            raise APIError(403, "verification_required", "Necesitas verificar tu identidad para continuar.")
        check_version(session, case, int(request.data.get("expected_version", 0)))
        change_channel(session, case, channel="whatsapp", actor_id=request.identifier)
        if case.status != "cancelado":
            case.status = "cancelado"
            case.version += 1
            append_event(session, event_type="tramite_cancelado", channel="whatsapp", actor_id=request.identifier, case_id=case.id, person_id=case.requester_id)
        return identity, case, 2, [_message("El trámite fue cancelado.")]
    if action == "answer" and stage and stage.startswith("collect_"):
        case, messages = _collect_unknown_data(session, identity, request)
        level = trust_level(session, channel="whatsapp", identifier=request.identifier, case=case)
        return identity, case, level, messages
    return identity, active_case, level, [_message("No te entendí. Elige una opción:", [_quick("Cotizar estudio", "start_quote"), _quick("Agendar cita", "start_booking")])]


def process_interaction(session: Session, request: InteractionRequest) -> dict[str, Any]:
    duplicate = session.scalar(select(Event).where(Event.idempotency_key == request.idempotency_key))
    if duplicate is not None:
        if duplicate.channel != "whatsapp" or duplicate.actor_id != request.identifier:
            raise APIError(409, "idempotency_conflict", "La clave ya se usó en otra interacción.")
        stored = (duplicate.payload or {}).get("_response")
        if isinstance(stored, dict):
            if duplicate.payload.get("_resume_challenge") != session.info.get("resume_challenge_id"):
                raise APIError(403, "resume_denied", "Verifica tu correo para continuar.")
            if session.info.get("resume_challenge_id") and duplicate.payload.get("_case_id"):
                case = session.get(Case, duplicate.payload["_case_id"])
                if case is not None and _case_trust(session, "whatsapp", request.identifier, case) >= 2:
                    return {**stored, "case": case_view(session, case)}
            return stored

    start_seq = session.scalar(select(func.max(Event.seq))) or 0
    recognition = recognize_identity(
        session,
        channel="whatsapp",
        identifier=request.identifier,
        identifier_type="phone",
    )
    session.flush()
    normalized_request = request.model_copy(update={"identifier": recognition["identifier"]})
    identity = _identity(session, recognition["identifier"])
    if identity is not None:
        bound = (identity.session_state or {}).get("resume_draft_challenge")
        if bound and bound != session.info.get("resume_challenge_id"):
            raise APIError(403, "resume_denied", "Verifica tu correo para continuar.")
        _expire_origin_if_needed(identity)
        if recognition["state"] == "unknown" and not identity.session_state:
            identity.session_state = {"started_unknown": True, "origin_case_ids": []}
    conversation = _conversation(identity)
    _first_contact(session, recognition["identifier"], identity.person_id if identity else None)
    received = append_event(
        session,
        event_type="mensaje_recibido",
        channel="whatsapp",
        actor_id=recognition["identifier"],
        person_id=identity.person_id if identity else None,
        payload={"type": _received_type(normalized_request, conversation.get("stage"))},
        idempotency_key=request.idempotency_key,
    )
    identity, case, level, messages = _handle(session, normalized_request, recognition, identity)
    if identity is not None:
        identity.last_seen_at = utc_now()
        current = _conversation(identity)
        if current != conversation:
            data = current.get("data") or {}
            if current.get("stage", "").startswith("collect_"):
                save_draft_record(session, identity, {
                    "requester": {key: data[key] for key in ("full_name", "birth_date", "email") if key in data}
                    | {"phone": identity.identifier},
                    "relationship": data.get("relationship"),
                    "patient": {"full_name": data.get("patient_name"), "birth_date": data.get("patient_birth_date")},
                })
            elif conversation.get("stage", "").startswith("collect_"):
                discard_draft_record(session, identity)
    for item in messages:
        append_event(
            session,
            event_type="mensaje_enviado",
            channel="whatsapp",
            actor_id=recognition["identifier"],
            case_id=case.id if case else None,
            person_id=identity.person_id if identity else None,
            payload={"type": "texto", "quick_reply_count": len(item.get("quick_replies", []))},
        )
    session.flush()
    event_types = session.scalars(select(Event.type).where(Event.seq > start_seq).order_by(Event.seq)).all()
    result = _response(
        session,
        identity=identity,
        case=case,
        level=level,
        messages=messages,
        event_types=list(event_types),
    )
    resume_id = session.info.get("resume_challenge_id")
    received.payload = {**(received.payload or {}),
                        "_response": {**result, "case": None} if resume_id else result,
                        "_case_id": case.id if resume_id and case else None,
                        "_resume_challenge": resume_id}
    return result
