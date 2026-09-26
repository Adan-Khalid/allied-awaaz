"""Demo payer page + simulated gateway + the real-shaped gateway webhook."""
from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import gateway_sim
from ..db import get_db
from ..models import Merchant, PaymentRequest
from ..payments import PaymentError, ingest_gateway_event

router = APIRouter(tags=["simulator"])


class SimPay(BaseModel):
    scenario: str = "success"


@router.post("/v1/gateway/events")
async def gateway_webhook(request: Request, x_gw_timestamp: str = Header(...), x_gw_signature: str = Header(...),
                          db: Session = Depends(get_db)):
    """Where ABL's acquiring switch would deliver events in a pilot. Same verification as the simulator."""
    body = await request.body()
    try:
        r = ingest_gateway_event(db, body, x_gw_timestamp, x_gw_signature)
    except PaymentError as exc:
        code = 401 if exc.code in {"bad_signature", "stale_event"} else 409
        raise HTTPException(code, exc.code) from exc
    return {"status": r.status, "payment_status": r.payment.status}


@router.post("/sim/pay/{token}")
def sim_pay(token: str, body: SimPay, db: Session = Depends(get_db)):
    try:
        p = gateway_sim.pay(db, token, body.scenario)
    except PaymentError as exc:
        raise HTTPException(409, exc.code) from exc
    return {"status": p.status, "reference": p.reference}


@router.get("/sim/status/{token}")
def sim_status(token: str, db: Session = Depends(get_db)):
    p = db.scalar(select(PaymentRequest).where(PaymentRequest.pay_token == token))
    if p is None:
        raise HTTPException(404, "not found")
    return {"status": p.status}


@router.get("/pay/{token}", response_class=HTMLResponse)
def payer_page(token: str, db: Session = Depends(get_db)):
    p = db.scalar(select(PaymentRequest).where(PaymentRequest.pay_token == token))
    if p is None:
        raise HTTPException(404, "invalid payment link")
    m = db.get(Merchant, p.merchant_id)
    return HTMLResponse(_PAGE.format(
        merchant=html.escape(m.name), amount=f"{p.amount_minor // 100:,}", ref=html.escape(p.reference),
        token=html.escape(token), status=p.status))


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Demo payer | Allied Awaaz</title>
<style>
:root{{--bg:#f4f6f8;--card:#fff;--ink:#111;--muted:#667;--brand:#0a5c36;--warn:#b45309;--bad:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1418;--card:#182028;--ink:#eef;--muted:#99a}}}}
*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--ink)}}
.banner{{background:var(--warn);color:#fff;text-align:center;font-size:13px;padding:6px}}
.card{{max-width:420px;margin:24px auto;background:var(--card);border-radius:16px;padding:24px;box-shadow:0 4px 20px #0002}}
.muted{{color:var(--muted);font-size:14px}}.amt{{font-size:44px;font-weight:700;margin:8px 0}}
button{{width:100%;padding:16px;border:0;border-radius:12px;font-size:18px;font-weight:600;cursor:pointer}}
.pay{{background:var(--brand);color:#fff;margin-top:16px}}
details{{margin-top:20px}}.alt{{background:transparent;border:1px solid var(--muted);color:var(--ink);font-size:14px;padding:10px;margin-top:8px}}
#msg{{margin-top:18px;font-size:18px;font-weight:600;min-height:24px}}
</style></head><body>
<div class="banner">SIMULATED PAYER FOR DEMO ONLY. Not a bank app. No real money moves.</div>
<div class="card">
<div class="muted">Pay to</div><div style="font-size:22px;font-weight:600">{merchant}</div>
<div class="amt">PKR {amount}</div><div class="muted">Reference {ref}</div>
<button class="pay" onclick="pay('success')">PAY</button>
<details><summary class="muted">Demo scenarios</summary>
<button class="alt" onclick="pay('slow')">Payer bank slow (settles later)</button>
<button class="alt" onclick="pay('stuck')">Stuck pending at payer bank</button>
<button class="alt" onclick="pay('fail')">Payment fails</button>
</details>
<div id="msg"></div></div>
<script>
const token="{token}";const msg=document.getElementById('msg');
function show(s){{const t={{CREATED:'Waiting for payment',PENDING:'Processing at your bank...',SUCCEEDED:'Paid. Merchant has been notified by the bank.',FAILED:'Payment failed.',EXPIRED:'This QR has expired.'}};msg.textContent=t[s]||s;}}
show("{status}");
async function pay(scenario){{
  document.querySelectorAll('button').forEach(b=>b.disabled=true);
  try{{const r=await fetch('/sim/pay/'+token,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{scenario}})}});
  const j=await r.json();show(r.ok?j.status:(j.detail||'error'));poll();}}catch(e){{msg.textContent='Network error';}}
}}
async function poll(){{for(let i=0;i<60;i++){{await new Promise(r=>setTimeout(r,1500));
  try{{const j=await (await fetch('/sim/status/'+token)).json();show(j.status);if(['SUCCEEDED','FAILED','EXPIRED'].includes(j.status))return;}}catch(e){{}}}}}}
</script></body></html>"""
