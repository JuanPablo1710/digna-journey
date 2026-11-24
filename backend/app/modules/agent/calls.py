from sqlalchemy import select

from ...errors import APIError
from ...models import Event


def call_event(session, call_id, event_type):
    return session.scalar(select(Event).where(
        Event.channel == "callcenter", Event.type == event_type,
        Event.payload["call_id"].as_string() == call_id,
    ).order_by(Event.seq.desc()).limit(1))


def owned_call(session, call_id, agent_id, *, active=True):
    start = call_event(session, call_id, "llamada_iniciada")
    if start is None or start.actor_id != agent_id:
        raise APIError(403, "call_denied", "La llamada no pertenece a esta sesión de asesor.")
    if active and call_event(session, call_id, "llamada_finalizada"):
        raise APIError(409, "call_ended", "La llamada ya terminó.")
    return start


def active_call(session, agent_id):
    starts = session.scalars(select(Event).where(
        Event.channel == "callcenter", Event.type == "llamada_iniciada", Event.actor_id == agent_id,
    ).order_by(Event.seq.desc()))
    return next((start for start in starts
                 if not call_event(session, start.payload["call_id"], "llamada_finalizada")), None)
