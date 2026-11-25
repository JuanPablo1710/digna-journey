from datetime import timezone

from ...security import masked_person


CHANNELS = {"web", "whatsapp", "callcenter", "app"}
EVENT_LABELS = {
    "contacto_creado": "Contacto creado",
    "identidad_vinculada": "Identidad vinculada",
    "identidad_fusionada": "Identidades fusionadas",
    "verificacion_solicitada": "Verificación solicitada",
    "verificacion_exitosa": "Verificación exitosa",
    "verificacion_fallida": "Verificación fallida",
    "consentimiento_aceptado": "Consentimiento aceptado",
    "tramite_creado": "Trámite creado",
    "estudio_seleccionado": "Estudio seleccionado",
    "datos_paciente_capturados": "Datos del paciente capturados",
    "clinica_seleccionada": "Clínica seleccionada",
    "horario_propuesto": "Horario propuesto",
    "cita_confirmada": "Cita confirmada",
    "cita_reagendada": "Cita reagendada",
    "tramite_cancelado": "Trámite cancelado",
    "tramite_abandonado": "Trámite abandonado",
    "tramite_reanudado": "Trámite reanudado",
    "canal_iniciado": "Canal iniciado",
    "canal_cambiado": "Cambio de canal",
    "mensaje_recibido": "Mensaje recibido",
    "mensaje_enviado": "Mensaje enviado",
    "llamada_iniciada": "Llamada iniciada",
    "llamada_finalizada": "Llamada finalizada",
    "nota_agregada": "Nota interna registrada",
    "contexto_consultado": "Contexto consultado",
    "acceso_denegado": "Acceso denegado",
}
DENIAL_REASONS = {
    "verification_required": "sin verificación vigente",
    "role_denied": "rol no permitido",
    "role_not_allowed": "rol no permitido",
    "session_expired": "sesión vencida",
}


def utc_iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_event(event, person=None):
    safe_type = event.type if event.type in EVENT_LABELS else "actividad_registrada"
    summary = EVENT_LABELS.get(safe_type, "Actividad registrada")
    if safe_type == "acceso_denegado":
        reason = (event.payload or {}).get("reason")
        if isinstance(reason, str) and reason in DENIAL_REASONS:
            summary += f" · {DENIAL_REASONS[reason]}"
    contact = masked_person(person)
    if contact:
        summary += f" · {contact['name']}"
    return {
        "type": safe_type,
        "case_id": event.case_id,
        "channel": event.channel if event.channel in CHANNELS or event.channel == "admin" else None,
        "timestamp": utc_iso(event.timestamp),
        "summary": summary,
    }
