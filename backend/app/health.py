"""Merchant health: deterministic, explainable signals. No model scores a merchant.

Each flag carries the exact numbers that triggered it, so a relationship manager
can see *why* a merchant was flagged before approving anything."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import Device, ExceptionCase, Merchant, PaymentRequest

WEIGHTS = {
    "NEVER_ACTIVATED": 50,
    "DORMANT": 45,
    "DECLINING": 30,
    "DEVICE_OFFLINE": 25,
    "EXCEPTION_SPIKE": 20,
}


@dataclass
class Flag:
    code: str
    detail: str
    evidence: dict


@dataclass
class HealthReport:
    merchant_id: str
    merchant_name: str
    score: int
    status: str  # HEALTHY | WATCH | AT_RISK
    primary_reason: str | None
    flags: list[Flag] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _count(db: Session, merchant_id: str, since, until=None) -> int:
    q = select(func.count()).where(PaymentRequest.merchant_id == merchant_id,
                                   PaymentRequest.status == "SUCCEEDED", PaymentRequest.settled_at >= since)
    if until is not None:
        q = q.where(PaymentRequest.settled_at < until)
    return int(db.scalar(q) or 0)


def compute_health(db: Session, m: Merchant) -> HealthReport:
    now = utcnow()
    d7, d35 = now - timedelta(days=7), now - timedelta(days=35)
    txn_7d = _count(db, m.id, d7)
    baseline_weekly = round(_count(db, m.id, d35, d7) / 4, 1)
    last = db.scalar(select(func.max(PaymentRequest.settled_at)).where(
        PaymentRequest.merchant_id == m.id, PaymentRequest.status == "SUCCEEDED"))
    days_since_last = None if last is None else (now - last).days
    volume_7d = int(db.scalar(select(func.coalesce(func.sum(PaymentRequest.amount_minor), 0)).where(
        PaymentRequest.merchant_id == m.id, PaymentRequest.status == "SUCCEEDED",
        PaymentRequest.settled_at >= d7)) or 0) // 100
    exceptions_14d = int(db.scalar(select(func.count()).where(
        ExceptionCase.merchant_id == m.id, ExceptionCase.opened_at >= now - timedelta(days=14))) or 0)
    onboarded_days = (now - m.onboarded_at).days

    offline_hours = None
    devices = db.scalars(select(Device).where(Device.merchant_id == m.id, Device.active.is_(True))).all()
    if devices:
        hours = []
        for d in devices:
            if d.online:
                hours.append(0.0)
            elif d.last_seen_at is None:
                hours.append(float(onboarded_days * 24))
            else:
                hours.append(round((now - d.last_seen_at).total_seconds() / 3600, 1))
        offline_hours = min(hours)

    metrics = {
        "txn_7d": txn_7d, "baseline_weekly_txn": baseline_weekly, "volume_7d_rupees": volume_7d,
        "days_since_last_payment": days_since_last, "exceptions_14d": exceptions_14d,
        "device_offline_hours": offline_hours, "onboarded_days": onboarded_days,
    }

    flags: list[Flag] = []
    if last is None and onboarded_days >= 14:
        flags.append(Flag("NEVER_ACTIVATED", f"No digital payment in {onboarded_days} days since onboarding",
                          {"onboarded_days": onboarded_days}))
    if days_since_last is not None and days_since_last >= 7:
        flags.append(Flag("DORMANT", f"No payment for {days_since_last} days",
                          {"days_since_last_payment": days_since_last, "baseline_weekly_txn": baseline_weekly}))
    elif baseline_weekly >= 5 and txn_7d < 0.5 * baseline_weekly:
        drop = round(100 * (1 - txn_7d / baseline_weekly))
        flags.append(Flag("DECLINING", f"Weekly payments down {drop}% ({txn_7d} vs usual {baseline_weekly})",
                          {"txn_7d": txn_7d, "baseline_weekly_txn": baseline_weekly, "drop_pct": drop}))
    if offline_hours is not None and offline_hours >= 24:
        flags.append(Flag("DEVICE_OFFLINE", f"Terminal offline for {offline_hours:.0f} hours",
                          {"device_offline_hours": offline_hours}))
    if exceptions_14d >= 3:
        flags.append(Flag("EXCEPTION_SPIKE", f"{exceptions_14d} payment exceptions in 14 days",
                          {"exceptions_14d": exceptions_14d}))

    score = max(0, 100 - sum(WEIGHTS[f.code] for f in flags))
    status = "HEALTHY" if score >= 80 else "WATCH" if score >= 50 else "AT_RISK"
    primary = max(flags, key=lambda f: WEIGHTS[f.code]).code if flags else None
    return HealthReport(m.id, m.name, score, status, primary, flags, metrics)
