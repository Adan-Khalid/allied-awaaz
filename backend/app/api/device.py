"""Terminal-facing API. Every route requires an HMAC-signed request (security.authenticated_device)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agent import orchestrator
from ..config import settings
from ..db import get_db
from ..models import Device, PaymentRequest
from ..security import authenticated_device
from ..speech import SttUnavailable, transcribe
from ..urdu import render

router = APIRouter(prefix="/v1/device", tags=["device"])


class CreatePayment(BaseModel):
    amount_rupees: int = Field(ge=1)


class Query(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    intent: str | None = Field(default=None, max_length=32)
    amount_rupees: int | None = Field(default=None, ge=1)  # keypad hotkeys, e.g. "C" = check claim for typed amount


class Confirm(BaseModel):
    run_id: str = Field(max_length=32)


@router.get("/config")
def config(device: Device = Depends(authenticated_device)):
    return {"device_id": device.id, "merchant_name": device.merchant.name,
            "max_payment_rupees": settings.max_payment_rupees, "payment_ttl_s": settings.payment_ttl_s}


@router.post("/payments")
def create_payment(body: CreatePayment, device: Device = Depends(authenticated_device),
                   db: Session = Depends(get_db)):
    """Keypad path. Runs through the same agent pipeline (direct intent) so it is traced and verified."""
    db.add(device)
    return orchestrator.handle(db, device, intent="CREATE_PAYMENT", amount=body.amount_rupees)


@router.get("/payments/{txn_id}")
def payment_status(txn_id: str, device: Device = Depends(authenticated_device), db: Session = Depends(get_db)):
    """Polling fallback when MQTT is unavailable. Authenticated HTTPS response, so it is trusted."""
    p = db.get(PaymentRequest, txn_id)
    if p is None or p.merchant_id != device.merchant_id:
        raise HTTPException(404, "not found")
    out = {"txn_id": p.id, "status": p.status, "amount_minor": p.amount_minor, "reference": p.reference}
    if p.status == "SUCCEEDED":
        out["speech"] = render([p.amount_minor // 100, "rupay", "receive_ho_gaye"])
    return out


@router.post("/query")
def query(body: Query, device: Device = Depends(authenticated_device), db: Session = Depends(get_db)):
    if not body.text and not body.intent:
        raise HTTPException(422, "text or intent required")
    db.add(device)
    return orchestrator.handle(db, device, text=body.text, intent=body.intent, amount=body.amount_rupees)


@router.post("/voice")
async def voice(request: Request, device: Device = Depends(authenticated_device), db: Session = Depends(get_db)):
    wav = await request.body()
    try:
        text = await run_in_threadpool(transcribe, wav)
    except SttUnavailable:
        speech = render(["raqam_samajh_nahi"])
        return {"outcome": "STT_UNAVAILABLE", "display_text": speech["display_text"],
                "speech": {"clips": speech["clips"], "spoken_text": speech["spoken_text"]},
                "action": None, "requires_confirmation": False}
    db.add(device)
    result = await run_in_threadpool(orchestrator.handle, db, device, text)
    return {**result, "transcript": text}


@router.post("/confirm")
def confirm(body: Confirm, device: Device = Depends(authenticated_device), db: Session = Depends(get_db)):
    db.add(device)
    return orchestrator.confirm(db, device, body.run_id)
