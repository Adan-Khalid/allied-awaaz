"""Bank-side console API (staff bearer tokens). Backs the Next.js console."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..health import compute_health
from ..interventions import DecisionError, decide, run_sweep
from ..models import AgentRun, AuditLog, Device, ExceptionCase, Intervention, Merchant, PaymentRequest
from ..security import Staff, authenticated_staff

router = APIRouter(prefix="/v1/console", tags=["console"])


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _intervention(i: Intervention, name: str | None = None) -> dict:
    return {"id": i.id, "merchant_id": i.merchant_id, "merchant_name": name, "reason_code": i.reason_code,
            "channel": i.channel, "title": i.title, "message": i.message, "evidence": i.evidence,
            "status": i.status, "agent_run_id": i.agent_run_id, "created_at": i.created_at.isoformat(),
            "decided_by": i.decided_by, "decision_note": i.decision_note,
            "decided_at": i.decided_at.isoformat() if i.decided_at else None}


@router.get("/whoami")
def whoami(staff: Staff = Depends(authenticated_staff)):
    return {"name": staff.name, "role": staff.role}


@router.get("/merchants")
def merchants(staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    out = []
    for m in db.scalars(select(Merchant).order_by(Merchant.name)).all():
        h = compute_health(db, m)
        out.append({"id": m.id, "name": m.name, "category": m.category, "city": m.city, "rm_name": m.rm_name,
                    "score": h.score, "status": h.status, "primary_reason": h.primary_reason,
                    "flags": [f.code for f in h.flags], "metrics": h.metrics})
    order = {"AT_RISK": 0, "WATCH": 1, "HEALTHY": 2}
    return sorted(out, key=lambda r: (order[r["status"]], r["score"]))


@router.get("/merchants/{merchant_id}")
def merchant_detail(merchant_id: str, staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    m = db.get(Merchant, merchant_id)
    if m is None:
        raise HTTPException(404, "not found")
    recent = db.scalars(select(PaymentRequest).where(PaymentRequest.merchant_id == m.id)
                        .order_by(PaymentRequest.created_at.desc()).limit(25)).all()
    devices = db.scalars(select(Device).where(Device.merchant_id == m.id)).all()
    return {
        "merchant": {"id": m.id, "name": m.name, "category": m.category, "city": m.city,
                     "phone_masked": m.phone_masked, "rm_name": m.rm_name, "onboarded_at": m.onboarded_at.isoformat()},
        "health": compute_health(db, m).as_dict(),
        "devices": [{"id": d.id, "online": d.online, "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
                     "firmware": d.firmware} for d in devices],
        "recent_payments": [{"txn_id": p.id, "amount_rupees": p.amount_minor // 100, "status": p.status,
                             "reference": p.reference, "created_at": p.created_at.isoformat(),
                             "payer_bank": p.payer_bank} for p in recent],
    }


@router.get("/exceptions")
def exceptions(status: str | None = None, staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    q = select(ExceptionCase, Merchant.name).join(Merchant, Merchant.id == ExceptionCase.merchant_id)
    if status:
        q = q.where(ExceptionCase.status == status)
    rows = db.execute(q.order_by(ExceptionCase.opened_at.desc()).limit(200)).all()
    return [{"id": c.id, "merchant_id": c.merchant_id, "merchant_name": name, "type": c.type, "status": c.status,
             "claimed_amount_rupees": c.claimed_amount_minor // 100, "payment_id": c.payment_id,
             "agent_run_id": c.agent_run_id, "opened_at": c.opened_at.isoformat(),
             "resolution": c.resolution} for c, name in rows]


@router.post("/activation/sweep")
def sweep(staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    return run_sweep(db, f"staff:{staff.name}")


@router.get("/interventions")
def interventions(status: str | None = None, staff: Staff = Depends(authenticated_staff),
                  db: Session = Depends(get_db)):
    q = select(Intervention, Merchant.name).join(Merchant, Merchant.id == Intervention.merchant_id)
    if status:
        q = q.where(Intervention.status == status)
    return [_intervention(i, n) for i, n in db.execute(q.order_by(Intervention.created_at.desc())).all()]


@router.post("/interventions/{intervention_id}/{verdict}")
def decide_intervention(intervention_id: str, verdict: str, body: Decision,
                        staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    if verdict not in {"approve", "reject"}:
        raise HTTPException(404, "unknown verdict")
    i = db.get(Intervention, intervention_id)
    if i is None:
        raise HTTPException(404, "not found")
    try:
        decide(db, i, staff, verdict == "approve", body.note)
    except DecisionError as exc:
        raise HTTPException(403 if "requires role" in str(exc) else 409, str(exc)) from exc
    return _intervention(i)


@router.get("/agent-runs")
def agent_runs(merchant_id: str | None = None, limit: int = 50, staff: Staff = Depends(authenticated_staff),
               db: Session = Depends(get_db)):
    q = select(AgentRun)
    if merchant_id:
        q = q.where(AgentRun.merchant_id == merchant_id)
    rows = db.scalars(q.order_by(AgentRun.created_at.desc()).limit(min(limit, 200))).all()
    return [_run(r) for r in rows]


def _run(r: AgentRun) -> dict:
    return {"id": r.id, "agent": r.agent, "merchant_id": r.merchant_id, "device_id": r.device_id,
            "input_text": r.input_text, "intent": r.intent, "understood_by": r.understood_by,
            "outcome": r.outcome, "steps": r.steps, "created_at": r.created_at.isoformat()}


@router.get("/agent-runs/{run_id}")
def agent_run(run_id: str, staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    r = db.get(AgentRun, run_id)
    if r is None:
        raise HTTPException(404, "not found")
    return _run(r)


@router.get("/summary")
def summary(staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    from sqlalchemy import func
    statuses = {"HEALTHY": 0, "WATCH": 0, "AT_RISK": 0}
    for m in db.scalars(select(Merchant)).all():
        statuses[compute_health(db, m).status] += 1
    pending = db.scalar(select(func.count()).select_from(Intervention).where(Intervention.status == "PENDING_APPROVAL"))
    open_cases = db.scalar(select(func.count()).select_from(ExceptionCase).where(ExceptionCase.status == "OPEN"))
    return {"merchants": statuses, "pending_approvals": int(pending or 0), "open_exceptions": int(open_cases or 0)}


@router.get("/audit")
def audit_log(limit: int = 100, staff: Staff = Depends(authenticated_staff), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 500))).all()
    return [{"at": a.at.isoformat(), "actor": a.actor, "action": a.action, "subject": a.subject,
             "detail": a.detail} for a in rows]
