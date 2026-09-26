"""Authentication and integrity primitives.

Device -> backend (HTTPS):
    X-Device-Id, X-Timestamp (unix s), X-Nonce (random hex), X-Signature
    signature = HMAC-SHA256(device_secret, METHOD\nPATH\nTS\nNONCE\nSHA256HEX(BODY))
    Rejected if: unknown/inactive device, |now-ts| > skew, nonce reused, bad signature.

Gateway -> backend (webhook):
    X-Gw-Timestamp, X-Gw-Signature = HMAC-SHA256(gateway_key, TS + "." + BODY)
    plus unique event_id (idempotency) and state-machine validation in payments.py.

Backend -> device (MQTT):
    sig = HMAC-SHA256(device_secret, "v|type|seq|ts|txn|amount_minor|status")
    Device rejects bad sig, stale ts, or seq <= last seen seq.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, utcnow
from .models import Device, UsedNonce


def hmac_hex(key: str, msg: str | bytes) -> str:
    if isinstance(msg, str):
        msg = msg.encode()
    return hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def device_canonical(method: str, path: str, ts: str, nonce: str, body: bytes) -> str:
    return f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{sha256_hex(body)}"


def sign_device_request(secret: str, method: str, path: str, ts: str, nonce: str, body: bytes) -> str:
    return hmac_hex(secret, device_canonical(method, path, ts, nonce, body))


def gateway_signature(key: str, ts: str, body: bytes) -> str:
    return hmac_hex(key, ts.encode() + b"." + body)


def mqtt_canonical(v: int, type_: str, seq: int, ts: int, txn: str, amount_minor: int, status: str) -> str:
    return f"{v}|{type_}|{seq}|{ts}|{txn}|{amount_minor}|{status}"


def fresh(ts: str) -> bool:
    try:
        return abs(time.time() - int(ts)) <= settings.max_clock_skew_s
    except ValueError:
        return False


def consume_nonce(db: Session, principal: str, nonce: str) -> bool:
    """Returns False if (principal, nonce) was already used inside the retention window."""
    if not nonce or len(nonce) > 64:
        return False
    db.add(UsedNonce(principal=principal, nonce=nonce))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    # Opportunistic cleanup: nonces older than 2x skew can never validate again anyway.
    db.execute(delete(UsedNonce).where(UsedNonce.seen_at < utcnow() - timedelta(seconds=2 * settings.max_clock_skew_s)))
    return True


class _RateLimiter:
    """Fixed-window per-principal limiter. Pilot deployment moves this to the API gateway."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def allow(self, key: str, limit: int) -> bool:
        window = int(time.time() // 60)
        with self._lock:
            w, n = self._windows.get(key, (window, 0))
            if w != window:
                w, n = window, 0
            if n >= limit:
                return False
            self._windows[key] = (w, n + 1)
            return True


rate_limiter = _RateLimiter()


async def authenticated_device(
    request: Request,
    x_device_id: str = Header(...),
    x_timestamp: str = Header(...),
    x_nonce: str = Header(...),
    x_signature: str = Header(...),
    db: Session = Depends(get_db),
) -> Device:
    device = db.get(Device, x_device_id)
    if device is None or not device.active:
        raise HTTPException(401, "unknown device")
    if not fresh(x_timestamp):
        raise HTTPException(401, "stale timestamp")
    body = await request.body()
    expected = sign_device_request(device.secret, request.method, request.url.path, x_timestamp, x_nonce, body)
    if not hmac.compare_digest(expected, x_signature.lower()):
        raise HTTPException(401, "bad signature")
    if not consume_nonce(db, f"dev:{device.id}", x_nonce):
        raise HTTPException(401, "replayed nonce")
    if not rate_limiter.allow(f"dev:{device.id}", settings.device_rate_per_min):
        raise HTTPException(429, "rate limited")
    device.last_seen_at = utcnow()
    db.commit()
    return device


@dataclass(frozen=True)
class Staff:
    name: str
    role: str  # rm | supervisor


def _staff_table() -> dict[str, Staff]:
    table: dict[str, Staff] = {}
    for entry in settings.staff_tokens.split(","):
        parts = entry.strip().split(":", 2)
        if len(parts) == 3:
            table[parts[0]] = Staff(name=parts[2], role=parts[1])
    return table


def authenticated_staff(authorization: str = Header(...)) -> Staff:
    token = authorization.removeprefix("Bearer ").strip()
    staff = _staff_table().get(token)
    if staff is None:
        raise HTTPException(401, "invalid staff token")
    return staff
