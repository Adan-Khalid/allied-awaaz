import json
import os
import secrets
import time

# Default: in-memory SQLite. Set AWAAZ_TEST_DATABASE_URL to run the same suite against Postgres.
os.environ["AWAAZ_DATABASE_URL"] = os.getenv("AWAAZ_TEST_DATABASE_URL", "sqlite://")
os.environ["AWAAZ_MQTT_ENABLED"] = "false"
os.environ["AWAAZ_SEED_DEMO"] = "false"
os.environ["AWAAZ_LLM_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
from app.main import app
from app.models import Device, Merchant
from app.notify import MemoryNotifier, set_notifier
from app.security import rate_limiter, sign_device_request

DEVICE_ID = "awz-test-001"
DEVICE_SECRET = "test-secret"


@pytest.fixture()
def notifier():
    n = MemoryNotifier()
    set_notifier(n)
    return n


@pytest.fixture()
def db(notifier):
    rate_limiter._windows.clear()
    dbmod.Base.metadata.drop_all(dbmod.engine)
    dbmod.Base.metadata.create_all(dbmod.engine)
    s = dbmod.SessionLocal()
    m = Merchant(name="Ahmed Pharmacy", category="pharmacy", city="Islamabad", phone_masked="0300-xxx-4417")
    s.add(m)
    s.flush()
    s.add(Device(id=DEVICE_ID, merchant_id=m.id, secret=DEVICE_SECRET, online=True))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c


def signed(client, method, path, body=None, *, secret=DEVICE_SECRET, ts=None, nonce=None, device=DEVICE_ID):
    raw = b"" if body is None else json.dumps(body).encode()
    ts = ts or str(int(time.time()))
    nonce = nonce or secrets.token_hex(8)
    headers = {"X-Device-Id": device, "X-Timestamp": ts, "X-Nonce": nonce,
               "X-Signature": sign_device_request(secret, method, path, ts, nonce, raw),
               "Content-Type": "application/json"}
    return client.request(method, path, content=raw, headers=headers)
