"""Relational model. Financial truth lives here, never on the device or in the LLM."""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mer"))
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    city: Mapped[str] = mapped_column(String(60))
    phone_masked: Mapped[str] = mapped_column(String(20))
    rm_name: Mapped[str] = mapped_column(String(80), default="Unassigned")
    onboarded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    devices: Mapped[list["Device"]] = relationship(back_populates="merchant")


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    # Shared secret for HMAC request signing and MQTT message verification.
    # Production: key lives in the device secure element; server copy encrypted under KMS.
    secret: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    mqtt_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    firmware: Mapped[str] = mapped_column(String(20), default="0.1.0")
    merchant: Mapped[Merchant] = relationship(back_populates="devices")


class PaymentRequest(Base):
    """One transaction-specific request (dynamic QR).
    CREATED -> PENDING -> SUCCEEDED | FAILED ; CREATED | PENDING -> EXPIRED"""
    __tablename__ = "payment_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("txn"))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # paisa
    currency: Mapped[str] = mapped_column(String(3), default="PKR")
    reference: Mapped[str] = mapped_column(String(24), index=True)
    pay_token: Mapped[str] = mapped_column(String(48), unique=True, default=lambda: secrets.token_urlsafe(24))
    status: Mapped[str] = mapped_column(String(12), default="CREATED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    payer_bank: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payer_masked: Mapped[str | None] = mapped_column(String(24), nullable=True)
    announced: Mapped[bool] = mapped_column(Boolean, default=False)


class PaymentEvent(Base):
    """Every verified gateway event. Unique event_id gives idempotency and replay protection."""
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payment_requests.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class UsedNonce(Base):
    __tablename__ = "used_nonces"
    __table_args__ = (UniqueConstraint("principal", "nonce"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    principal: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(64))
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ExceptionCase(Base):
    """Opened by the Payment Exception Agent.
    Types: CLAIM_NOT_FOUND, PENDING_AT_PAYER, PAYMENT_FAILED."""
    __tablename__ = "exception_cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("case"))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    type: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")  # OPEN | AUTO_RESOLVED | CLOSED
    claimed_amount_minor: Mapped[int] = mapped_column(BigInteger)
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payment_requests.id"), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON)
    agent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRun(Base):
    """Explainability trace: one row per agent invocation, with every step it took."""
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("run"))
    agent: Mapped[str] = mapped_column(String(24))  # merchant | activation
    merchant_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    understood_by: Mapped[str | None] = mapped_column(String(16), nullable=True)  # rules | llm | direct
    steps: Mapped[list] = mapped_column(JSON, default=list)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pending_action: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Intervention(Base):
    """Drafted by the Merchant Activation Agent.
    PENDING_APPROVAL -> APPROVED -> EXECUTED, or PENDING_APPROVAL -> REJECTED.
    Nothing reaches a merchant without a named staff approval."""
    __tablename__ = "interventions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("int"))
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    reason_code: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(24))  # rm_call | field_visit | whatsapp | ops_review
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING_APPROVAL", index=True)
    agent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(80))  # device:<id> | staff:<name> | gateway | agent:<run>
    action: Mapped[str] = mapped_column(String(48))
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


def audit(db, actor: str, action: str, subject: str | None = None, **detail) -> None:
    db.add(AuditLog(actor=actor, action=action, subject=subject, detail=detail))
