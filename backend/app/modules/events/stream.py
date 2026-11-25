import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from ...db import SessionLocal
from ...errors import APIError
from ...models import Case, Event, Person
from ..agent import verified_requesters
from ..auth import audit_staff_denial, bearer, validate_staff
from .safe import safe_event


router = APIRouter(tags=["stream"])
STAFF = {"admin", "asesor"}
POLL_SECONDS = 0.35
HEARTBEAT_TICKS = 40


class StreamAccessLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access logger supplies the request target as argument 3.
        # Also redact obsolete or accidental query credentials.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, target, protocol, status = record.args
            if isinstance(target, str) and target.partition("?")[0] == "/stream":
                record.args = (client, method, "/stream", protocol, status)
        return True


logging.getLogger("uvicorn.access").addFilter(StreamAccessLogFilter())


def _scope(session, credentials, case_id):
    user = validate_staff(session, credentials, STAFF)
    if user.role == "admin":
        return None
    owners = verified_requesters(session, user)
    if case_id:
        case = session.get(Case, case_id)
        if not case or case.requester_id not in owners:
            raise APIError(403, "verification_required", "Verifica al solicitante del trámite para continuar.")
        return {case.id}
    if not owners:
        raise APIError(403, "verification_required", "Verifica al solicitante para recibir actualizaciones.")
    return set(session.scalars(select(Case.id).where(Case.requester_id.in_(owners))))


def _start_cursor(credentials, case_id, previous):
    with SessionLocal() as session:
        try:
            _scope(session, credentials, case_id)
        except APIError as exc:
            if exc.status_code == 403:
                audit_staff_denial(session, credentials, "callcenter", exc.error,
                                   case=session.get(Case, case_id) if case_id else None)
                session.commit()
            raise
        latest = session.scalar(select(func.max(Event.seq))) or 0
        return latest if previous is None else min(previous, latest)


def _committed_batch(credentials, case_id, cursor):
    # Independent, short-lived reader connections can only see committed rows.
    with SessionLocal() as session:
        scope = _scope(session, credentials, case_id)
        query = select(Event).where(Event.seq > cursor)
        if scope is not None:
            query = query.where(Event.case_id.in_(scope))
        events = session.scalars(query.order_by(Event.seq).limit(100)).all()
        return [
            (event.seq, safe_event(event, session.get(Person, event.person_id) if event.person_id else None))
            for event in events
        ]


async def stream_events(request, credentials, case_id, cursor) -> AsyncIterator[str]:
    idle_ticks = 0
    yield f"id: {cursor}\n: conectado\n\n"
    while not await request.is_disconnected():
        try:
            items = await run_in_threadpool(_committed_batch, credentials, case_id, cursor)
        except (APIError, OperationalError):
            # Expired staff sessions and revoked call grants cut the existing flow.
            return
        for cursor, event in items:
            if await request.is_disconnected():
                return
            yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        if items:
            idle_ticks = 0
        else:
            idle_ticks += 1
            if idle_ticks == HEARTBEAT_TICKS:
                yield ": activo\n\n"
                idle_ticks = 0
            await asyncio.sleep(POLL_SECONDS)


@router.get("/stream")
async def stream(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    case_id: Annotated[str | None, Query(max_length=100)] = None,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID", ge=0, le=2**63 - 1)] = None,
):
    cursor = await run_in_threadpool(_start_cursor, credentials, case_id, last_event_id)
    return StreamingResponse(
        stream_events(request, credentials, case_id, cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
