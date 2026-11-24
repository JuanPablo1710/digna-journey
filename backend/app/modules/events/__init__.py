
from datetime import timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from ...models import Event


def append_event(
    session: Session,
    *,
    event_type: str,
    channel: str,
    actor_id: str,
    case_id: str | None = None,
    person_id: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> Event:
    event = Event(
        event_id=f"evt_{uuid4().hex[:12]}",
        type=event_type,
        case_id=case_id,
        person_id=person_id,
        channel=channel,
        actor_role="paciente",
        actor_id=actor_id,
        payload=payload or {},
        idempotency_key=idempotency_key,
    )
    session.add(event)
    return event


def public_event_view(event: Event) -> dict[str, Any]:
    timestamp = event.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    payload = {key: value for key, value in (event.payload or {}).items() if key != "_response"}
    return {
        "event_id": event.event_id,
        "type": event.type,
        "channel": event.channel,
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "payload": payload,
    }
