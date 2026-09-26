"""SIMULATED ABL merchant payment gateway. Clearly labelled; not the Raast API.

It plays the role of the acquiring switch: when the demo payer taps PAY, it emits
signed events that go through exactly the same verification path
(payments.ingest_gateway_event) a real bank webhook would use.

Scenarios
  success  PENDING then SUCCEEDED immediately
  slow     PENDING now, SUCCEEDED after AWAAZ_SIM_SLOW_DELAY_S
  stuck    PENDING only (payer bank never confirms) for the "pending" demo
  fail     PENDING then FAILED
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, utcnow
from .models import PaymentRequest
from .payments import PaymentError, ingest_gateway_event
from .security import gateway_signature

log = logging.getLogger(__name__)
SCENARIOS = {"success", "slow", "stuck", "fail"}
_PAYER_BANKS = ["HBL", "Meezan Bank", "UBL", "MCB", "easypaisa", "JazzCash", "Allied Bank"]


def signed_event(payment: PaymentRequest, status: str) -> tuple[bytes, str, str]:
    body = json.dumps({
        "event_id": f"evt_{secrets.token_hex(10)}",
        "type": f"payment.{status.lower()}",
        "payment_id": payment.id,
        "reference": payment.reference,
        "amount_minor": payment.amount_minor,
        "status": status,
        "payer_bank": secrets.choice(_PAYER_BANKS),
        "payer_masked": f"03xx-xxx{secrets.randbelow(9000) + 1000}",
        "occurred_at": utcnow().isoformat() + "Z",
        "simulated": True,
    }, separators=(",", ":")).encode()
    ts = str(int(time.time()))
    return body, ts, gateway_signature(settings.gateway_signing_key, ts, body)


def _emit(db: Session, payment_id: str, status: str) -> None:
    p = db.get(PaymentRequest, payment_id)
    body, ts, sig = signed_event(p, status)
    ingest_gateway_event(db, body, ts, sig)


def _delayed(payment_id: str, status: str, delay: float) -> None:
    def run():
        with SessionLocal() as db:
            try:
                _emit(db, payment_id, status)
            except PaymentError as exc:
                log.info("delayed sim event skipped: %s", exc.code)
    threading.Timer(delay, run).start()


def pay(db: Session, token: str, scenario: str) -> PaymentRequest:
    if scenario not in SCENARIOS:
        raise PaymentError("bad_scenario", scenario)
    p = db.scalar(select(PaymentRequest).where(PaymentRequest.pay_token == token))
    if p is None:
        raise PaymentError("unknown_payment", "invalid payment link")
    if p.status == "CREATED" and p.expires_at < utcnow():
        p.status = "EXPIRED"
        db.commit()
    if p.status != "CREATED":
        raise PaymentError("not_payable", f"payment is {p.status}")

    _emit(db, p.id, "PENDING")
    if scenario == "success":
        _emit(db, p.id, "SUCCEEDED")
    elif scenario == "fail":
        _emit(db, p.id, "FAILED")
    elif scenario == "slow":
        _delayed(p.id, "SUCCEEDED", settings.sim_slow_delay_s)
    db.refresh(p)
    return p
