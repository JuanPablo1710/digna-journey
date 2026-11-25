import asyncio
import json
import logging
import socket
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from time import perf_counter
from urllib.parse import urlencode

import httpx
import uvicorn
from sqlalchemy import select

from app.db import SessionLocal
from app.dev import GRACEFUL_SHUTDOWN_SECONDS
from app.main import app
from app.models import Verification
from app.modules.events import append_event
from app.modules.events.stream import POLL_SECONDS
from app.modules.identity.service import utc_now
from app.security import create_patient_token
from test_agent import call, owner, token, verify


@asynccontextmanager
async def connection(headers, *, case_id=None):
    incoming, outgoing = asyncio.Queue(), asyncio.Queue()
    incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    query_string = urlencode({"case_id": case_id}) if case_id else ""
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http", "path": "/stream",
        "raw_path": b"/stream", "query_string": query_string.encode(), "root_path": "",
        "headers": [(key.lower().encode(), val.encode()) for key, val in headers.items()],
        "client": ("test", 9000), "server": ("test", 80),
    }
    assert "token" not in query_string and headers["Authorization"] not in query_string
    task = asyncio.create_task(app(scope, incoming.get, outgoing.put))
    try:
        started = await asyncio.wait_for(outgoing.get(), 3)
        assert started["status"] == 200
        assert (b"content-type", b"text/event-stream; charset=utf-8") in started["headers"]
        baseline = (await asyncio.wait_for(outgoing.get(), 3))["body"].decode()
        assert ": conectado" in baseline
        yield outgoing
    finally:
        incoming.put_nowait({"type": "http.disconnect"})
        await asyncio.wait_for(task, 3)


def write_event(session, event_type, case_id="C-1001"):
    append_event(session, event_type=event_type, channel="web", actor_id="luis.demo@example.com",
                 case_id=case_id, person_id=owner(case_id),
                 payload={"full_name": "Luis Demo", "birth_date": "1985-04-12",
                          "phone": "+522221111111", "secret": "Nota privada 983421"})


async def next_event(queue):
    frame = (await asyncio.wait_for(queue.get(), 4))["body"].decode()
    lines = frame.splitlines()
    return int(lines[0].removeprefix("id: ")), json.loads(lines[1].removeprefix("data: "))


def test_stream_uses_bearer_only_and_redacts_access_log(client, caplog):
    admin = token(client, "admin", "Admin#2026")["Authorization"].split()[1]
    assert client.get("/stream").status_code == 401
    assert client.get("/stream", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/stream", params={"token": admin}).status_code == 401
    patient = {"Authorization": f"Bearer {create_patient_token(owner())}"}
    assert client.get("/stream", headers=patient).status_code == 403
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "test", "GET",
                                                 f"/stream?token={admin}", "1.1", 401)
    assert 'GET /stream HTTP/1.1' in caplog.text
    assert admin not in caplog.text


def test_login_and_shutdown_with_24_open_streams(client):
    login = {"username": "admin", "password": "Admin#2026"}
    headers = token(client, login["username"], login["password"])

    async def scenario():
        server = uvicorn.Server(uvicorn.Config(
            app, lifespan="off", ws="none", access_log=False, log_level="critical",
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        ))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            serving = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(5):
                    while not server.started:
                        if serving.done():
                            await serving
                        await asyncio.sleep(0.01)
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5,
                ) as network, AsyncExitStack() as streams:
                    async def subscribe():
                        response = await streams.enter_async_context(network.stream("GET", "/stream", headers=headers))
                        assert response.status_code == 200
                        lines = response.aiter_lines()
                        assert (await anext(lines)).startswith("id: ")
                        return lines

                    subscriptions = await asyncio.gather(*(subscribe() for _ in range(24)))
                    await asyncio.sleep(POLL_SECONDS)
                    assert len(server.server_state.tasks) == len(subscriptions)

                    started = perf_counter()
                    response = await network.post("/auth/login", json=login, timeout=1)
                    elapsed = perf_counter() - started
                    assert response.status_code == 200
                    assert response.json()["role"] == "admin"
                    assert elapsed < 1, f"Login tardó {elapsed:.3f} s con 24 streams abiertos"

                    server.should_exit = True
                    await asyncio.wait_for(asyncio.shield(serving), 4)
            finally:
                server.should_exit = True
                await asyncio.wait_for(serving, 5)

    asyncio.run(scenario())


def test_sse_masks_committed_events_and_resumes_without_duplicates(client):
    headers = token(client, "admin", "Admin#2026")

    async def scenario():
        async with connection(headers) as queue:
            with SessionLocal() as failed:
                write_event(failed, "verificacion_fallida")
                failed.flush()
                await asyncio.sleep(POLL_SECONDS * 2)
                assert queue.empty()
                failed.rollback()
            with SessionLocal.begin() as session:
                write_event(session, "nota_agregada")
            cursor, event = await next_event(queue)
            assert set(event) == {"type", "case_id", "channel", "timestamp", "summary"}
            assert event["type"] == "nota_agregada" and "L*** D." in event["summary"]
            for value in ("Luis Demo", "luis.demo@example.com", "+522221111111", "1985-04-12", "983421", "Nota privada"):
                assert value not in json.dumps(event)
        with SessionLocal.begin() as session:
            write_event(session, "cita_confirmada")
        async with connection({**headers, "Last-Event-ID": str(cursor)}) as queue:
            new_cursor, event = await next_event(queue)
            assert new_cursor > cursor and event["type"] == "cita_confirmada"

    asyncio.run(scenario())


def test_advisor_sse_filters_and_closes_when_verification_expires(client):
    headers = token(client)
    person_id = owner()
    assert client.get("/stream?case_id=C-1001", headers=headers).status_code == 403
    assert verify(client, headers, person_id).status_code == 200
    assert client.get("/stream?case_id=C-1002", headers=headers).status_code == 403

    async def scenario():
        async with connection(headers, case_id="C-1001") as queue:
            with SessionLocal.begin() as session:
                write_event(session, "cita_confirmada", "C-1002")
                write_event(session, "horario_propuesto")
            _, event = await next_event(queue)
            assert event["case_id"] == "C-1001" and event["type"] == "horario_propuesto"
            with SessionLocal.begin() as session:
                grant = session.scalar(select(Verification).where(Verification.person_id == person_id))
                grant.valid_until = utc_now() - timedelta(seconds=1)
            message = await asyncio.wait_for(queue.get(), 4)
            assert message["body"] == b"" and not message.get("more_body")

    asyncio.run(scenario())
    assert client.get("/stream?case_id=C-1001", headers=headers).status_code == 403


def test_advisor_sse_closes_when_call_ends(client):
    headers = token(client)
    call_id = call(client, headers).json()["call_id"]
    assert verify(client, headers, owner(), call_id=call_id).status_code == 200

    async def scenario():
        async with connection(headers, case_id="C-1001") as queue:
            assert call(client, headers, "call_ended", call_id=call_id).status_code == 200
            message = await asyncio.wait_for(queue.get(), 4)
            assert message["body"] == b"" and not message.get("more_body")

    asyncio.run(scenario())
