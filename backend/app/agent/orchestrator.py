"""Merchant-side agent: an explicit state machine, not a free-running LLM loop.

    OBSERVE     transcript (or keypad hotkey) + authenticated device/merchant context
    UNDERSTAND  deterministic rules first, closed-enum LLM fallback second
    PLAN        map intent to an allowlisted tool sequence, or ask to clarify/confirm
    ACT         call tools (validated, merchant-scoped, traced)
    VERIFY      re-read system state before claiming success
    RESPOND     fixed Urdu templates rendered from verified numbers only

Every run is persisted with its steps so the bank can see why the agent said what it said.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import AgentRun, Device, ExceptionCase, audit
from ..urdu import render
from . import llm
from .intents import Intent, Understanding, understand
from .tools import ToolContext, ToolError, call_tool

CONFIRM_TTL_S = 60


def _step(run: AgentRun, name: str, **data: Any) -> None:
    run.steps = [*run.steps, {"step": name, **data}]


def _reply(run: AgentRun, outcome: str, parts: list, action: dict | None = None,
           confirm: bool = False) -> dict:
    speech = render(parts)
    run.outcome = outcome
    _step(run, "respond", outcome=outcome, text=speech["display_text"])
    return {
        "run_id": run.id,
        "intent": run.intent,
        "understood_by": run.understood_by,
        "outcome": outcome,
        "display_text": speech["display_text"],
        "speech": {"clips": speech["clips"], "spoken_text": speech["spoken_text"]},
        "action": action,
        "requires_confirmation": confirm,
    }


def handle(db: Session, device: Device, text: str | None = None, intent: str | None = None,
           amount: int | None = None) -> dict:
    merchant = device.merchant
    run = AgentRun(agent="merchant", merchant_id=merchant.id, device_id=device.id, input_text=text, steps=[])
    db.add(run)
    db.flush()
    ctx = ToolContext(db=db, agent="merchant", run=run, merchant=merchant, device=device,
                      actor=f"agent:{run.id}")
    _step(run, "observe", text=text, hotkey=intent, device=device.id)

    # UNDERSTAND
    if intent:  # keypad hotkeys bypass NLU entirely
        try:
            u = Understanding(Intent(intent), amount, 1.0, source="direct")
        except ValueError:
            u = Understanding(Intent.UNKNOWN, source="direct")
    else:
        u = understand(text or "")
        if u.intent == Intent.UNKNOWN:
            fallback = llm.classify(text or "")
            if fallback is not None:
                u = fallback
    run.intent, run.understood_by = u.intent.value, u.source
    _step(run, "understand", intent=u.intent.value, amount=u.amount, confidence=u.confidence,
          source=u.source, notes=u.notes)

    try:
        result = _plan_and_act(ctx, u)
    except ToolError as exc:
        _step(run, "error", code=exc.code)
        result = _reply(run, "TOOL_ERROR", ["raqam_samajh_nahi"] if exc.code in {
            "invalid_argument", "amount_over_limit", "invalid_amount"} else ["sirf_payment_madad"])
    audit(db, f"device:{device.id}", "agent.run", run.id, intent=run.intent, outcome=run.outcome)
    db.commit()
    return result


def _plan_and_act(ctx: ToolContext, u: Understanding) -> dict:
    run = ctx.run
    i = u.intent

    if i == Intent.CREATE_PAYMENT:
        if u.amount is None:
            _step(run, "plan", decision="clarify", reason="no amount")
            return _reply(run, "CLARIFY_AMOUNT", ["raqam_samajh_nahi"])
        if u.source == "llm" or u.confidence < 0.7:
            # Human oversight: a model-inferred or low-confidence amount is shown, not acted on.
            run.pending_action = {"tool": "create_payment_request", "args": {"amount_rupees": u.amount},
                                  "expires": (utcnow() + timedelta(seconds=CONFIRM_TTL_S)).isoformat()}
            _step(run, "plan", decision="confirm_first", amount=u.amount)
            return _reply(run, "AWAITING_CONFIRMATION", [u.amount, "rupay", "confirm_karein"],
                          action={"type": "confirm_amount", "amount_rupees": u.amount, "run_id": run.id},
                          confirm=True)
        _step(run, "plan", decision="create_payment", tools=["create_payment_request", "get_payment_status"])
        return _create(ctx, u.amount)

    if i == Intent.CHECK_CLAIM:
        if u.amount is None:
            _step(run, "plan", decision="clarify", reason="claim without amount")
            return _reply(run, "CLARIFY_AMOUNT", ["raqam_samajh_nahi"])
        _step(run, "plan", decision="investigate_claim", tools=["find_payments", "get_payment_status",
                                                                "open_exception_case"])
        return _investigate_claim(ctx, u.amount)

    if i == Intent.LAST_PAYMENT:
        _step(run, "plan", decision="lookup", tools=["get_last_payment"])
        r = call_tool(ctx, "get_last_payment")
        if not r["found"]:
            return _reply(run, "NO_PAYMENTS", ["koi_payment_nahi_hui"])
        return _reply(run, "LAST_PAYMENT", ["aakhri_payment", r["payment"]["amount_rupees"], "rupay", "thi"])

    if i == Intent.TODAY_SUMMARY:
        _step(run, "plan", decision="lookup", tools=["get_today_summary"])
        r = call_tool(ctx, "get_today_summary")
        if r["count"] == 0:
            return _reply(run, "TODAY_SUMMARY", ["aaj_koi_payment_nahi"])
        return _reply(run, "TODAY_SUMMARY",
                      ["aaj", r["count"], "payments_mein", r["total_rupees"], "rupay", "receive_hue"])

    if i == Intent.DEVICE_STATUS:
        _step(run, "plan", decision="lookup", tools=["get_device_status"])
        call_tool(ctx, "get_device_status")
        return _reply(run, "DEVICE_STATUS", ["device_online"])

    if i == Intent.HELP:
        _step(run, "plan", decision="help")
        return _reply(run, "HELP", ["help"])

    _step(run, "plan", decision="refuse", reason="outside allowed scope")
    return _reply(run, "OUT_OF_SCOPE", ["sirf_payment_madad"])


def _create(ctx: ToolContext, amount: int) -> dict:
    run = ctx.run
    created = call_tool(ctx, "create_payment_request", amount_rupees=amount)
    # VERIFY: the request exists, belongs to this merchant, has the exact amount and is payable.
    check = call_tool(ctx, "get_payment_status", txn_id=created["txn_id"])
    ok = check["status"] == "CREATED" and check["amount_rupees"] == amount
    _step(run, "verify", ok=ok, status=check["status"], amount=check["amount_rupees"])
    if not ok:
        return _reply(run, "VERIFY_FAILED", ["sirf_payment_madad"])
    return _reply(run, "QR_READY", [amount, "rupay", "ka_qr_tayyar_hai"], action={
        "type": "show_qr", "txn_id": created["txn_id"], "reference": created["reference"],
        "qr_payload": created["qr_payload"], "amount_rupees": amount, "expires_at": created["expires_at"],
    })


def _investigate_claim(ctx: ToolContext, amount: int) -> dict:
    run = ctx.run
    window = settings.claim_window_min
    found = call_tool(ctx, "find_payments", amount_rupees=amount, window_min=window)
    matches = found["matches"]
    by_status: dict[str, list[dict]] = {}
    for m in matches:
        by_status.setdefault(m["status"], []).append(m)

    if "SUCCEEDED" in by_status:
        m = by_status["SUCCEEDED"][0]
        check = call_tool(ctx, "get_payment_status", txn_id=m["txn_id"])
        _step(run, "verify", ok=check["status"] == "SUCCEEDED", txn=m["txn_id"])
        minutes = max(0, int((utcnow() - _parse(check["settled_at"])).total_seconds() // 60))
        when = ["abhi_abhi_receive_ho_chuki"] if minutes < 1 else [minutes, "minute_pehle_receive_ho_chuki"]
        return _reply(run, "CLAIM_RECEIVED", [amount, "rupay", "ki_payment", *when],
                      action={"type": "claim_result", "result": "RECEIVED", "txn_id": m["txn_id"],
                              "reference": check["reference"], "payer_bank": check["payer_bank"]})

    if "PENDING" in by_status:
        m = by_status["PENDING"][0]
        check = call_tool(ctx, "get_payment_status", txn_id=m["txn_id"])
        _step(run, "verify", ok=check["status"] == "PENDING", txn=m["txn_id"])
        if check["status"] == "SUCCEEDED":  # settled between the two reads
            return _investigate_claim(ctx, amount)
        case_id = _existing_open_case(ctx, m["txn_id"]) or call_tool(
            ctx, "open_exception_case", case_type="PENDING_AT_PAYER", amount_rupees=amount,
            payment_id=m["txn_id"], evidence={"matches": matches, "window_min": window})["case_id"]
        return _reply(run, "CLAIM_PENDING", [amount, "rupay", "ki_payment", "abhi_pending_hai", "maal_abhi_na_dein"],
                      action={"type": "claim_result", "result": "PENDING", "txn_id": m["txn_id"],
                              "reference": check["reference"], "case_id": case_id})

    if "FAILED" in by_status:
        m = by_status["FAILED"][0]
        case = call_tool(ctx, "open_exception_case", case_type="PAYMENT_FAILED", amount_rupees=amount,
                         payment_id=m["txn_id"], evidence={"matches": matches, "window_min": window})
        _step(run, "verify", ok=True, txn=m["txn_id"])
        return _reply(run, "CLAIM_FAILED", ["payment_fail_hui"],
                      action={"type": "claim_result", "result": "FAILED", "txn_id": m["txn_id"],
                              "case_id": case["case_id"]})

    case = call_tool(ctx, "open_exception_case", case_type="CLAIM_NOT_FOUND", amount_rupees=amount,
                     payment_id=None, evidence={"matches": matches, "window_min": window})
    _step(run, "verify", ok=True, matches=len(matches))
    return _reply(run, "CLAIM_NOT_RECEIVED",
                  ["pichle", window, "minute_mein", amount, "rupay", "ki_koi_payment_nahi_aayi",
                   "maal_abhi_na_dein", "case_darj"],
                  action={"type": "claim_result", "result": "NOT_RECEIVED", "case_id": case["case_id"]})


def _existing_open_case(ctx: ToolContext, payment_id: str) -> str | None:
    from sqlalchemy import select
    return ctx.db.scalar(select(ExceptionCase.id).where(
        ExceptionCase.payment_id == payment_id, ExceptionCase.status == "OPEN"))


def _parse(iso: str):
    from datetime import datetime
    return datetime.fromisoformat(iso)


def confirm(db: Session, device: Device, run_id: str) -> dict:
    """Merchant pressed # on the terminal to approve a pending, agent-proposed action."""
    run = db.get(AgentRun, run_id)
    if run is None or run.device_id != device.id or not run.pending_action:
        return {"ok": False, "error": "nothing_to_confirm"}
    pending = run.pending_action
    from datetime import datetime
    if datetime.fromisoformat(pending["expires"]) < utcnow():
        run.pending_action = None
        db.commit()
        return {"ok": False, "error": "confirmation_expired"}
    run.pending_action = None
    _step(run, "human_confirmed", by=f"device:{device.id}")
    ctx = ToolContext(db=db, agent="merchant", run=run, merchant=device.merchant, device=device,
                      actor=f"agent:{run.id}")
    try:
        result = _create(ctx, int(pending["args"]["amount_rupees"]))
    except ToolError as exc:
        _step(run, "error", code=exc.code)
        result = _reply(run, "TOOL_ERROR", ["raqam_samajh_nahi"])
    audit(db, f"device:{device.id}", "agent.confirmed", run.id)
    db.commit()
    return {"ok": True, **result}
