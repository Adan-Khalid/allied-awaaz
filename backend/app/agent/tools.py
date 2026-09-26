"""The complete set of actions any agent can take. Nothing else is reachable.

Guarantees enforced here, independent of prompts:
  * merchant_id / device are injected from the authenticated context, never taken
    from model or user input, so a tool cannot touch another merchant's data;
  * every argument is type- and range-checked before execution;
  * each agent has its own allowlist (the merchant agent cannot draft interventions,
    the activation agent cannot create payments);
  * every call and its result is appended to the AgentRun trace.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import AgentRun, Device, ExceptionCase, Merchant, PaymentRequest, audit
from .. import payments


class ToolError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass
class ToolContext:
    db: Session
    agent: str               # "merchant" | "activation"
    run: AgentRun
    merchant: Merchant | None = None
    device: Device | None = None
    actor: str = "system"


def _int_arg(value: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ToolError("invalid_argument", f"{name} must be an integer in [{lo}, {hi}]")
    return value


def _require_merchant(ctx: ToolContext) -> Merchant:
    if ctx.merchant is None:
        raise ToolError("no_merchant_context")
    return ctx.merchant


def _payment_view(p: PaymentRequest) -> dict:
    return {
        "txn_id": p.id, "reference": p.reference, "amount_rupees": p.amount_minor // 100,
        "status": p.status, "created_at": p.created_at.isoformat(),
        "settled_at": p.settled_at.isoformat() if p.settled_at else None,
        "expires_at": p.expires_at.isoformat(),
        "payer_bank": p.payer_bank, "payer_masked": p.payer_masked,
    }


# ------------------------------------------------------------------ merchant agent tools

def create_payment_request(ctx: ToolContext, amount_rupees: int) -> dict:
    m = _require_merchant(ctx)
    amount = _int_arg(amount_rupees, "amount_rupees", 1, settings.max_payment_rupees)
    try:
        p = payments.create_request(ctx.db, m, ctx.device, amount)
    except payments.PaymentError as exc:
        raise ToolError(exc.code, str(exc)) from exc
    return _payment_view(p) | {"qr_payload": payments.qr_payload(p)}


def get_payment_status(ctx: ToolContext, txn_id: str) -> dict:
    m = _require_merchant(ctx)
    p = ctx.db.get(PaymentRequest, str(txn_id))
    if p is None or p.merchant_id != m.id:
        raise ToolError("not_found")
    return _payment_view(p)


def get_last_payment(ctx: ToolContext) -> dict:
    m = _require_merchant(ctx)
    p = payments.last_succeeded(ctx.db, m.id)
    return {"found": p is not None, "payment": _payment_view(p) if p else None}


def get_today_summary(ctx: ToolContext) -> dict:
    m = _require_merchant(ctx)
    count, total = payments.today_summary(ctx.db, m.id)
    return {"count": count, "total_rupees": total}


def find_payments(ctx: ToolContext, amount_rupees: int, window_min: int) -> dict:
    m = _require_merchant(ctx)
    amount = _int_arg(amount_rupees, "amount_rupees", 1, settings.max_payment_rupees)
    window = _int_arg(window_min, "window_min", 1, 120)
    payments.expire_stale(ctx.db, m.id)
    rows = payments.find_payments(ctx.db, m.id, amount * 100, window)
    return {"amount_rupees": amount, "window_min": window, "matches": [_payment_view(p) for p in rows]}


def open_exception_case(ctx: ToolContext, case_type: str, amount_rupees: int,
                        payment_id: str | None, evidence: dict) -> dict:
    m = _require_merchant(ctx)
    if case_type not in {"CLAIM_NOT_FOUND", "PENDING_AT_PAYER", "PAYMENT_FAILED"}:
        raise ToolError("invalid_argument", "case_type")
    amount = _int_arg(amount_rupees, "amount_rupees", 1, settings.max_payment_rupees)
    if payment_id is not None:
        p = ctx.db.get(PaymentRequest, payment_id)
        if p is None or p.merchant_id != m.id:
            raise ToolError("not_found", "payment")
    case = ExceptionCase(merchant_id=m.id, type=case_type, claimed_amount_minor=amount * 100,
                         payment_id=payment_id, evidence=evidence, agent_run_id=ctx.run.id)
    ctx.db.add(case)
    ctx.db.flush()
    audit(ctx.db, ctx.actor, "case.opened", case.id, type=case_type, amount_rupees=amount)
    return {"case_id": case.id, "type": case_type, "status": case.status}


def get_device_status(ctx: ToolContext) -> dict:
    d = ctx.device
    if d is None:
        raise ToolError("no_device_context")
    recent = d.last_seen_at is not None and d.last_seen_at > utcnow() - timedelta(minutes=5)
    return {"device_id": d.id, "online": bool(d.online or recent), "firmware": d.firmware}


# ------------------------------------------------------------------ activation agent tools

def get_merchant_health(ctx: ToolContext, merchant_id: str) -> dict:
    from ..health import compute_health
    m = ctx.db.get(Merchant, str(merchant_id))
    if m is None:
        raise ToolError("not_found")
    return compute_health(ctx.db, m).as_dict()


def draft_intervention(ctx: ToolContext, merchant_id: str, reason_code: str) -> dict:
    from ..interventions import create_draft
    m = ctx.db.get(Merchant, str(merchant_id))
    if m is None:
        raise ToolError("not_found")
    try:
        i = create_draft(ctx.db, m, reason_code, ctx.run.id)
    except ValueError as exc:
        raise ToolError("invalid_argument", str(exc)) from exc
    return {"intervention_id": i.id, "status": i.status, "channel": i.channel}


REGISTRY: dict[str, tuple[Callable[..., dict], set[str]]] = {
    "create_payment_request": (create_payment_request, {"merchant"}),
    "get_payment_status": (get_payment_status, {"merchant"}),
    "get_last_payment": (get_last_payment, {"merchant"}),
    "get_today_summary": (get_today_summary, {"merchant"}),
    "find_payments": (find_payments, {"merchant"}),
    "open_exception_case": (open_exception_case, {"merchant"}),
    "get_device_status": (get_device_status, {"merchant"}),
    "get_merchant_health": (get_merchant_health, {"activation"}),
    "draft_intervention": (draft_intervention, {"activation"}),
}


def call_tool(ctx: ToolContext, name: str, **kwargs: Any) -> dict:
    entry = REGISTRY.get(name)
    step: dict[str, Any] = {"step": "act", "tool": name, "args": kwargs}
    try:
        if entry is None or ctx.agent not in entry[1]:
            raise ToolError("tool_not_allowed", name)
        result = entry[0](ctx, **kwargs)
        step["ok"] = True
        step["result"] = result
        return result
    except ToolError as exc:
        step["ok"] = False
        step["error"] = exc.code
        raise
    finally:
        ctx.run.steps = [*ctx.run.steps, step]
