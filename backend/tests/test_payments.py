import json
import time

from app.config import settings
from app.models import PaymentRequest
from app.security import gateway_signature, hmac_hex, mqtt_canonical
from tests.conftest import DEVICE_SECRET, signed


def _create(client, amount=1250):
    r = signed(client, "POST", "/v1/device/payments", {"amount_rupees": amount})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "QR_READY"
    return body["action"]


def _token(action):
    return action["qr_payload"].rsplit("/", 1)[1]


def test_create_and_pay_success_notifies_device_with_valid_signature(client, db, notifier):
    action = _create(client)
    assert action["amount_rupees"] == 1250
    r = client.post(f"/sim/pay/{_token(action)}", json={"scenario": "success"})
    assert r.json()["status"] == "SUCCEEDED"

    msgs = [m for _, m in notifier.sent]
    assert [m["status"] for m in msgs] == ["PENDING", "SUCCEEDED"]
    assert msgs[1]["seq"] > msgs[0]["seq"]
    m = msgs[-1]
    expected = hmac_hex(DEVICE_SECRET, mqtt_canonical(1, m["type"], m["seq"], m["ts"], m["txn"],
                                                      m["amount_minor"], m["status"]))
    assert m["sig"] == expected and m["amount_minor"] == 125000

    st = signed(client, "GET", f"/v1/device/payments/{action['txn_id']}").json()
    assert st["status"] == "SUCCEEDED"
    assert st["speech"]["clips"] == ["n_1", "hazaar", "n_2", "sau", "n_50", "rupay", "receive_ho_gaye"]


def _event(payment, status, event_id="evt_x", amount=None):
    body = json.dumps({"event_id": event_id, "type": "payment." + status.lower(), "payment_id": payment.id,
                       "amount_minor": payment.amount_minor if amount is None else amount,
                       "status": status}).encode()
    ts = str(int(time.time()))
    return body, {"X-Gw-Timestamp": ts, "X-Gw-Signature": gateway_signature(settings.gateway_signing_key, ts, body),
                  "Content-Type": "application/json"}


def test_webhook_rejects_bad_signature(client, db):
    action = _create(client)
    p = db.get(PaymentRequest, action["txn_id"])
    body, headers = _event(p, "SUCCEEDED")
    headers["X-Gw-Signature"] = "00" * 32
    assert client.post("/v1/gateway/events", content=body, headers=headers).status_code == 401


def test_webhook_rejects_amount_mismatch(client, db):
    action = _create(client)
    p = db.get(PaymentRequest, action["txn_id"])
    body, headers = _event(p, "SUCCEEDED", amount=1)
    assert client.post("/v1/gateway/events", content=body, headers=headers).status_code == 409
    db.refresh(p)
    assert p.status == "CREATED"


def test_webhook_idempotent(client, db, notifier):
    action = _create(client)
    p = db.get(PaymentRequest, action["txn_id"])
    body, headers = _event(p, "SUCCEEDED", event_id="evt_dup")
    assert client.post("/v1/gateway/events", content=body, headers=headers).json()["status"] == "applied"
    assert client.post("/v1/gateway/events", content=body, headers=headers).json()["status"] == "duplicate"
    assert len(notifier.sent) == 1


def test_invalid_transition_rejected(client, db):
    action = _create(client)
    p = db.get(PaymentRequest, action["txn_id"])
    body, headers = _event(p, "FAILED", event_id="e1")
    client.post("/v1/gateway/events", content=body, headers=headers)
    body, headers = _event(p, "SUCCEEDED", event_id="e2")
    assert client.post("/v1/gateway/events", content=body, headers=headers).status_code == 409


def test_limits_enforced(client):
    r = signed(client, "POST", "/v1/device/payments", {"amount_rupees": settings.max_payment_rupees + 1})
    assert r.json()["outcome"] == "TOOL_ERROR"


def test_cannot_pay_twice(client):
    action = _create(client)
    client.post(f"/sim/pay/{_token(action)}", json={"scenario": "success"})
    assert client.post(f"/sim/pay/{_token(action)}", json={"scenario": "success"}).status_code == 409
