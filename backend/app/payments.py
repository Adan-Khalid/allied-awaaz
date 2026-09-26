"""Payment domain service. The only code allowed to change payment state."""
from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .db import utcnow
from .models import Device, ExceptionCase, Merchant, PaymentEvent, PaymentRequest, audit
from .notify import build_payment_message, get_notifier
from .security import fresh, gateway_signature

PKT = timedelta(hours=5)  # Pakistan Standard Time, no DST

ALLOWED = {
    ("CREATED", "PENDING"), ("CREATED", "SUCCEEDED"), ("CREATED", "FAILED"),
    ("PENDING", "SUCCEEDED"), ("PENDING", "FAILED"),
    # Money that settles after the QR expired is still real money: accept and flag it.
    ("EXPIRED", "SUCCEEDED"),
}
TERMINAL = {"SUCCEEDED", "FAILED"}


class PaymentError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ requests

def create_request(db: Session, merchant: Merchant, device: Device | None, amount_rupees: int) -> PaymentRequest:
    if not isinstance(amount_rupees, int) or amount_rupees < 1:
        raise PaymentError("invalid_amount", "amount must be a positive whole number of rupees")
    if amount_rupees > settings.max_payment_rupees:
        raise PaymentError("amount_over_limit", f"amount exceeds device limit of {settings.max_payment_rupees}")
    now = utcnow()
    p = PaymentRequest(
        merchant_id=merchant.id,
        device_id=device.id if device else None,
        amount_minor=amount_rupees * 100,
        reference=f"AWZ{secrets.token_hex(4).upper()}",
        created_at=now,
        expires_at=now + timedelta(seconds=settings.payment_ttl_s),
    )
    db.add(p)
    audit(db, f"device:{device.id}" if device else "system", "payment.request.created", p.id,
          amount_minor=p.amount_minor, reference=p.reference)
    db.flush()
    return p


def qr_payload(p: PaymentRequest) -> str:
    """SIMULATED payload: a link to the demo payer page.

    Production: an SBP-compliant Raast P2M dynamic QR string (EMVCo TLV, Raast MAI
    tags 28-30) issued by ABL's acquiring switch. The terminal treats the payload as
    opaque, so swapping formats needs no firmware change."""
    return f"{settings.public_base_url}/pay/{p.pay_token}"


def expire_stale(db: Session, merchant_id: str) -> int:
    now = utcnow()
    rows = db.scalars(select(PaymentRequest).where(
        PaymentRequest.merchant_id == merchant_id, PaymentRequest.status == "CREATED",
        PaymentRequest.expires_at < now)).all()
    for p in rows:
        p.status = "EXPIRED"
    return len(rows)


# ------------------------------------------------------------------ gateway events

@dataclass
class IngestResult:
    status: str  # applied | duplicate
    payment: PaymentRequest
    late: bool = False


def ingest_gateway_event(db: Session, raw_body: bytes, ts: str, signature: str) -> IngestResult:
    """Single entry point for payment truth. Verifies, deduplicates, validates, applies, notifies."""
    expected = gateway_signature(settings.gateway_signing_key, ts, raw_body)
    if not hmac.compare_digest(expected, (signature or "").lower()):
        raise PaymentError("bad_signature", "gateway signature invalid")
    if not fresh(ts):
        raise PaymentError("stale_event", "gateway event outside freshness window")
    try:
        ev = json.loads(raw_body)
        event_id, etype, pid = str(ev["event_id"]), str(ev["type"]), str(ev["payment_id"])
        new_status, amount_minor = str(ev["status"]), int(ev["amount_minor"])
    except (KeyError, ValueError, TypeError) as exc:
        raise PaymentError("malformed_event", str(exc)) from exc

    if db.scalar(select(PaymentEvent.id).where(PaymentEvent.event_id == event_id)):
        p = db.get(PaymentRequest, pid)
        return IngestResult("duplicate", p)

    p = db.get(PaymentRequest, pid)
    if p is None:
        raise PaymentError("unknown_payment", pid)
    if amount_minor != p.amount_minor:
        audit(db, "gateway", "payment.event.rejected", p.id, reason="amount_mismatch",
              expected=p.amount_minor, got=amount_minor)
        db.commit()
        raise PaymentError("amount_mismatch", "event amount does not match request")
    if (p.status, new_status) not in ALLOWED:
        raise PaymentError("invalid_transition", f"{p.status} -> {new_status}")

    late = p.status == "EXPIRED"
    p.status = new_status
    if new_status == "SUCCEEDED":
        p.settled_at = utcnow()
        p.payer_bank = ev.get("payer_bank")
        p.payer_masked = ev.get("payer_masked")
    db.add(PaymentEvent(event_id=event_id, payment_id=p.id, type=etype, payload=ev))
    audit(db, "gateway", "payment.event.applied", p.id, event_id=event_id, status=new_status, late=late)

    if new_status in TERMINAL:
        _auto_resolve_cases(db, p)
    if p.device_id and new_status in {"SUCCEEDED", "FAILED", "PENDING"}:
        device = db.get(Device, p.device_id)
        if device is not None:
            msg = build_payment_message(device, p)
            if new_status == "SUCCEEDED":
                p.announced = True
            db.commit()
            get_notifier().publish(device.id, msg)
            return IngestResult("applied", p, late)
    db.commit()
    return IngestResult("applied", p, late)


def _auto_resolve_cases(db: Session, p: PaymentRequest) -> None:
    """Closes the loop on PENDING_AT_PAYER cases once the gateway reports a final state."""
    cases = db.scalars(select(ExceptionCase).where(
        ExceptionCase.payment_id == p.id, ExceptionCase.status == "OPEN",
        ExceptionCase.type == "PENDING_AT_PAYER")).all()
    for c in cases:
        c.status = "AUTO_RESOLVED"
        c.resolved_at = utcnow()
        c.resolution = f"gateway reported {p.status}"
        audit(db, "system", "case.auto_resolved", c.id, payment_id=p.id, final=p.status)


# ------------------------------------------------------------------ deterministic queries

def pkt_day_start_utc(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    local = now + PKT
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - PKT


def last_succeeded(db: Session, merchant_id: str) -> PaymentRequest | None:
    return db.scalars(select(PaymentRequest).where(
        PaymentRequest.merchant_id == merchant_id, PaymentRequest.status == "SUCCEEDED")
        .order_by(PaymentRequest.settled_at.desc()).limit(1)).first()


def today_summary(db: Session, merchant_id: str) -> tuple[int, int]:
    """(count, total_rupees) of SUCCEEDED payments since local midnight."""
    count, total = db.execute(select(func.count(), func.coalesce(func.sum(PaymentRequest.amount_minor), 0)).where(
        PaymentRequest.merchant_id == merchant_id, PaymentRequest.status == "SUCCEEDED",
        PaymentRequest.settled_at >= pkt_day_start_utc())).one()
    return int(count), int(total) // 100


def find_payments(db: Session, merchant_id: str, amount_minor: int, window_min: int) -> list[PaymentRequest]:
    since = utcnow() - timedelta(minutes=window_min)
    return list(db.scalars(select(PaymentRequest).where(
        PaymentRequest.merchant_id == merchant_id, PaymentRequest.amount_minor == amount_minor,
        PaymentRequest.created_at >= since).order_by(PaymentRequest.created_at.desc())).all())
