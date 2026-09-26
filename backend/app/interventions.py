"""Merchant Activation Agent (bank-side) and the human approval gate.

The agent observes health signals, picks the intervention the playbook prescribes for
the primary reason, drafts it with the evidence attached, and stops. A named staff
member approves or rejects. Customer-facing messages need supervisor approval."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utcnow
from .health import compute_health
from .models import AgentRun, Intervention, Merchant, audit
from .security import Staff

OPEN_STATES = {"PENDING_APPROVAL", "APPROVED"}

# reason -> (channel, title template, message template)
PLAYBOOK: dict[str, tuple[str, str, str]] = {
    "DEVICE_OFFLINE": (
        "field_visit",
        "Terminal offline at {name}: schedule field check",
        "Visit {name} ({city}). Terminal offline for {device_offline_hours:.0f}h. Check power, SIM/Wi-Fi "
        "and placement. Confirm a test payment is announced before leaving.",
    ),
    "DORMANT": (
        "rm_call",
        "Dormant merchant: call {name}",
        "Call {name}. No digital payment for {days_since_last_payment} days (previously ~{baseline_weekly_txn}/week). "
        "Ask whether the terminal is in use, whether customers had payment problems, and offer a device refresh.",
    ),
    "DECLINING": (
        "whatsapp",
        "Declining usage at {name}: send reminder",
        "Assalam-o-Alaikum {name}. Allied Awaaz terminal par har digital payment ki confirmation seedha bank se "
        "aati hai. Customer se kahein QR scan karein, aur agar koi masla ho to bas terminal se poochein. "
        "Madad ke liye aapke RM {rm} haazir hain.",
    ),
    "EXCEPTION_SPIKE": (
        "ops_review",
        "Repeated payment exceptions at {name}: ops review",
        "Review {exceptions_14d} exception cases in 14 days for {name}. Check for repeated unpaid claims "
        "(possible screenshot fraud pattern) or payer-bank delays, then advise the merchant.",
    ),
    "NEVER_ACTIVATED": (
        "field_visit",
        "Never activated: onboarding visit to {name}",
        "Visit {name} ({city}). Onboarded {onboarded_days} days ago with no digital payment. Demonstrate a live "
        "test payment and the 'payment aayi?' voice check.",
    ),
}

APPROVER_ROLES = {"rm_call": {"rm", "supervisor"}, "field_visit": {"rm", "supervisor"},
                  "ops_review": {"rm", "supervisor"}, "whatsapp": {"supervisor"}}


def create_draft(db: Session, m: Merchant, reason_code: str, run_id: str | None) -> Intervention:
    if reason_code not in PLAYBOOK:
        raise ValueError(f"unknown reason {reason_code}")
    existing = db.scalar(select(Intervention).where(
        Intervention.merchant_id == m.id, Intervention.reason_code == reason_code,
        Intervention.status.in_(OPEN_STATES)))
    if existing:
        return existing
    report = compute_health(db, m)
    fields = {**report.metrics, "name": m.name, "city": m.city, "rm": m.rm_name}
    fields = {k: (0 if v is None else v) for k, v in fields.items()}
    channel, title, message = PLAYBOOK[reason_code]
    i = Intervention(
        merchant_id=m.id, reason_code=reason_code, channel=channel,
        title=title.format(**fields), message=message.format(**fields),
        evidence={"score": report.score, "status": report.status,
                  "flags": [f.__dict__ for f in report.flags], "metrics": report.metrics},
        status="PENDING_APPROVAL", agent_run_id=run_id,
    )
    db.add(i)
    db.flush()
    audit(db, f"agent:{run_id}", "intervention.drafted", i.id, merchant_id=m.id, reason=reason_code)
    return i


def run_sweep(db: Session, triggered_by: str) -> dict:
    """One activation-agent pass over the merchant base."""
    from .agent.tools import ToolContext, ToolError, call_tool

    merchants = db.scalars(select(Merchant)).all()
    who = triggered_by.split(":", 1)[-1]
    run = AgentRun(agent="activation", input_text=f"Sweep started by {who}", intent="ACTIVATION_SWEEP",
                   understood_by="direct", steps=[
                       {"step": "observe", "trigger": who, "merchants": len(merchants)},
                       {"step": "plan", "decision": "score every merchant, draft the playbook action for each flagged one",
                        "tools": ["get_merchant_health", "draft_intervention"]},
                   ])
    db.add(run)
    db.flush()
    ctx = ToolContext(db=db, agent="activation", run=run, actor=f"agent:{run.id}")
    drafted, examined = [], 0
    for m in merchants:
        examined += 1
        health = call_tool(ctx, "get_merchant_health", merchant_id=m.id)
        if health["status"] == "HEALTHY" or not health["primary_reason"]:
            continue
        try:
            r = call_tool(ctx, "draft_intervention", merchant_id=m.id, reason_code=health["primary_reason"])
            drafted.append(r["intervention_id"])
        except ToolError:
            continue
    run.outcome = "SWEEP_DONE"
    run.steps = [*run.steps, {"step": "respond", "examined": examined, "drafted": len(drafted)}]
    audit(db, triggered_by, "activation.sweep", run.id, examined=examined, drafted=len(drafted))
    db.commit()
    return {"run_id": run.id, "examined": examined, "drafted": drafted}


class DecisionError(Exception):
    pass


def decide(db: Session, i: Intervention, staff: Staff, approve: bool, note: str | None) -> Intervention:
    if i.status != "PENDING_APPROVAL":
        raise DecisionError(f"intervention is {i.status}")
    if approve and staff.role not in APPROVER_ROLES[i.channel]:
        raise DecisionError(f"{i.channel} requires role in {sorted(APPROVER_ROLES[i.channel])}")
    now = utcnow()
    i.decided_by, i.decided_at, i.decision_note = staff.name, now, note
    if not approve:
        i.status = "REJECTED"
        audit(db, f"staff:{staff.name}", "intervention.rejected", i.id, note=note)
        db.commit()
        return i
    i.status = "APPROVED"
    audit(db, f"staff:{staff.name}", "intervention.approved", i.id, note=note)
    _execute(db, i)
    db.commit()
    return i


def _execute(db: Session, i: Intervention) -> None:
    """Pilot integration points: ABL WhatsApp Business API, CRM task queue, ops case system.
    Here the dispatch is simulated and recorded."""
    target = {"whatsapp": "ABL WhatsApp Business (simulated)", "rm_call": "RM task queue (simulated)",
              "field_visit": "Field ops queue (simulated)", "ops_review": "Ops case queue (simulated)"}[i.channel]
    i.status = "EXECUTED"
    i.executed_at = utcnow()
    audit(db, "system", "intervention.executed", i.id, channel=i.channel, target=target)
