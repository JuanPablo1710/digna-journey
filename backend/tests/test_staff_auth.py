import jwt

from app.config import settings
from app.security import create_patient_token


def test_staff_login_accepts_seed_credentials_and_issues_eight_hour_tokens(client):
    for username, password, role in (
        ("asesor", "Asesor#2026", "asesor"),
        ("admin", "Admin#2026", "admin"),
    ):
        result = client.post("/auth/login", json={"username": username, "password": password})
        assert result.status_code == 200
        body = result.json()
        claims = jwt.decode(body["access_token"], settings.jwt_secret, algorithms=["HS256"])
        assert claims["role"] == body["role"] == role
        assert claims["exp"] - claims["iat"] == 8 * 3600
    denied = client.post("/auth/login", json={"username": "asesor", "password": "incorrecta"})
    assert denied.status_code == 401


def test_staff_lookup_is_advisor_only_and_masked(client):
    path = "/agent/lookup?email=marta.demo@example.com"
    assert client.get(path).status_code == 401
    patient = create_patient_token("P-0001")
    assert client.get(path, headers={"Authorization": f"Bearer {patient}"}).status_code == 403
    for username, password, expected in (
        ("asesor", "Asesor#2026", 200), ("admin", "Admin#2026", 403),
    ):
        login = client.post("/auth/login", json={"username": username, "password": password})
        token = login.json()["access_token"]
        result = client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert result.status_code == expected
        if expected == 200:
            assert result.json()["matches"][0]["masked_name"] == "M*** D."
            assert "Marta Demo" not in result.text
