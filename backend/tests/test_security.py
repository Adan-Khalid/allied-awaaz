import time

from tests.conftest import signed


def test_valid_signature(client):
    r = signed(client, "GET", "/v1/device/config")
    assert r.status_code == 200 and r.json()["merchant_name"] == "Ahmed Pharmacy"


def test_bad_signature_rejected(client):
    assert signed(client, "GET", "/v1/device/config", secret="wrong").status_code == 401


def test_replayed_nonce_rejected(client):
    assert signed(client, "GET", "/v1/device/config", nonce="abc123").status_code == 200
    assert signed(client, "GET", "/v1/device/config", nonce="abc123").status_code == 401


def test_stale_timestamp_rejected(client):
    old = str(int(time.time()) - 3600)
    assert signed(client, "GET", "/v1/device/config", ts=old).status_code == 401


def test_unknown_device_rejected(client):
    assert signed(client, "GET", "/v1/device/config", device="awz-ghost").status_code == 401


def test_body_tampering_detected(client):
    import json, secrets
    from app.security import sign_device_request
    ts, nonce = str(int(time.time())), secrets.token_hex(8)
    sig = sign_device_request("test-secret", "POST", "/v1/device/payments", ts, nonce,
                              json.dumps({"amount_rupees": 100}).encode())
    r = client.post("/v1/device/payments", content=json.dumps({"amount_rupees": 99999}).encode(),
                    headers={"X-Device-Id": "awz-test-001", "X-Timestamp": ts, "X-Nonce": nonce,
                             "X-Signature": sig, "Content-Type": "application/json"})
    assert r.status_code == 401


def test_staff_auth(client):
    assert client.get("/v1/console/whoami").status_code == 422
    assert client.get("/v1/console/whoami", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.get("/v1/console/whoami", headers={"Authorization": "Bearer dev-sup-token"})
    assert r.json()["role"] == "supervisor"


def test_rate_limit(client):
    from app.config import settings
    codes = [signed(client, "GET", "/v1/device/config").status_code for _ in range(settings.device_rate_per_min + 1)]
    assert codes[-1] == 429 and set(codes[:-1]) == {200}
