from fastapi.testclient import TestClient

from app.main import create_app
from test_web_core import interaction, preregister


def test_new_device_revokes_old_cookie(client):
    identifier = "old-device"
    case = preregister(client, session_id=identifier)["case"]
    path = f"/cases/{case['id']}"
    assert client.get(path).status_code == 200
    assert client.get("/demo/new-device").status_code == 204

    reset = client.post("/demo/new-device")
    assert reset.status_code == 204
    assert "Max-Age=0" in reset.headers["set-cookie"]
    assert client.cookies.get("web_session") is None

    client.cookies.set("web_session", identifier)
    assert client.get(path).status_code == 403
    assert client.get(f"{path}/timeline").status_code == 403
    assert interaction(client, identifier, "start_quote").status_code == 403
    resumed = interaction(client, identifier, "continue_case").json()
    assert resumed["reset_session"] is True
    assert resumed["case"] is None


def test_new_device_routes_absent_outside_demo():
    app = create_app(demo_mode=False)
    client = TestClient(app)
    assert client.get("/demo/new-device").status_code == 404
    assert client.post("/demo/new-device").status_code == 404
    assert "/demo/new-device" not in app.openapi()["paths"]
