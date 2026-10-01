#!/usr/bin/env python3
"""Laptop terminal: the Allied Awaaz counter device, running on a laptop.

The laptop stands in for the ESP32-S3 hardware:
  laptop screen    -> 240x320 TFT display
  keyboard / mouse -> 4x4 keypad (digits, # * A B C D)
  laptop mic       -> INMP441 push-to-talk microphone
  laptop speakers  -> MAX98357A amplifier playing the same WAV clip library

This process *is* the device. It holds the device secret and does all protocol work
through tools/virtual_terminal.py (the byte-for-byte twin of the firmware):
  * every backend call is an HMAC-signed request
  * a payment is announced only from an HMAC-verified, fresh, in-sequence MQTT message,
    or from the device's own signed HTTPS status read (polling fallback)
  * the spoken amount is derived locally from the verified integer
The browser page is only screen, keys, mic and speaker. It never sees the device secret
and cannot mark anything as paid. The server listens on 127.0.0.1 only.

    python tools/laptop_terminal/server.py            # then open http://127.0.0.1:8090
    AWAAZ_API=http://localhost:8000 AWAAZ_MQTT_HOST=127.0.0.1 AWAAZ_DEVICE_MQTT_PASSWORD=... \\
        python tools/laptop_terminal/server.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import segno
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CLIPS = ROOT / "firmware" / "data" / "clips"
sys.path.insert(0, str(ROOT / "tools"))
from virtual_terminal import VirtualTerminal, from_env, payment_received_clips  # noqa: E402

POLL_S = 3.0          # same cadence as the firmware's polling fallback
_CLIP_NAME = re.compile(r"^[a-z0-9_]{1,48}$")


class Device:
    """Terminal state that the firmware keeps in main.cpp (current txn, announced ring buffer)."""

    def __init__(self, vt: VirtualTerminal):
        self.vt = vt
        self.merchant = "Allied Awaaz"
        self.payment_ttl_s = 300
        self.mqtt_mode = False
        self.bank_ok = False
        self.current_txn = ""
        self.current_ref = ""
        self.announced: list[str] = []
        self.lock = threading.Lock()
        self.subscribers: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ events to the screen
    def emit(self, event: dict) -> None:
        if not self.loop:
            return
        for q in list(self.subscribers):
            self.loop.call_soon_threadsafe(q.put_nowait, event)

    def announce_paid(self, txn: str, amount_minor: int, source: str) -> None:
        with self.lock:
            if txn in self.announced:
                return
            self.announced = (self.announced + [txn])[-8:]
            ref = self.current_ref if txn == self.current_txn else ""
            if txn == self.current_txn:
                self.current_txn = ""
        rupees = amount_minor // 100
        self.emit({"type": "paid", "txn": txn, "rupees": rupees, "reference": ref,
                   "clips": payment_received_clips(rupees), "source": source})

    def on_status(self, txn: str, status: str, amount_minor: int, source: str) -> None:
        if status == "SUCCEEDED":
            self.announce_paid(txn, amount_minor, source)
        elif status == "PENDING" and txn == self.current_txn:
            self.emit({"type": "pending", "txn": txn})
        elif status == "FAILED" and txn == self.current_txn:
            with self.lock:
                self.current_txn = ""
            self.emit({"type": "failed", "txn": txn, "clips": ["payment_fail_hui"]})

    # ------------------------------------------------------------ background workers
    def mqtt_worker(self) -> None:
        """Drains announcements that virtual_terminal already verified (HMAC, freshness, sequence)."""
        while True:
            a = self.vt.announcements.get()
            self.on_status(a.txn, a.status, a.amount_minor, "mqtt")

    def poll_worker(self) -> None:
        """The device's own signed status read for the QR on screen.

        The firmware polls only while MQTT is down. A laptop sleeps and changes Wi-Fi far more
        often, so here the signed read also runs while a QR is showing, as a backup to MQTT.
        It is an authenticated HTTPS response (invariant 2), and announce_paid() de-duplicates."""
        import httpx

        while True:
            time.sleep(POLL_S)
            try:
                self.bank_ok = httpx.get(self.vt.api_base + "/healthz", timeout=3).status_code == 200
            except httpx.HTTPError:
                self.bank_ok = False
            txn = self.current_txn
            if not txn:
                continue
            try:
                r = self.vt.poll_status(txn)
            except Exception:  # noqa: BLE001  network blip; try again next tick
                continue
            self.on_status(txn, r.get("status", ""), int(r.get("amount_minor") or 0), "https")

    def mqtt_connected(self) -> bool:
        c = self.vt._mqtt  # noqa: SLF001
        return bool(c and c.is_connected())

    # ------------------------------------------------------------ backend calls
    def call(self, fn, *args) -> dict:
        try:
            r = fn(*args)
        except RuntimeError as exc:  # non-200 from the backend
            raise HTTPException(502, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001  unreachable backend
            raise HTTPException(503, f"bank unreachable: {exc}") from exc
        return self.decorate(r)

    def decorate(self, r: dict) -> dict:
        action = r.get("action") or {}
        if action.get("type") == "show_qr":
            with self.lock:
                self.current_txn = action.get("txn_id", "")
                self.current_ref = action.get("reference", "")
            qr = segno.make(action.get("qr_payload", ""), error="l")
            r["qr_svg"] = qr.svg_data_uri(scale=6, border=2, dark="#000", light="#fff")
        return r


dev = Device(from_env())


class Query(BaseModel):
    text: str | None = Field(default=None, max_length=500)
    intent: str | None = Field(default=None, max_length=32)
    amount_rupees: int | None = Field(default=None, ge=1)


class Amount(BaseModel):
    amount_rupees: int = Field(ge=1)


class Confirm(BaseModel):
    run_id: str = Field(max_length=32)


def _resubscribe_on_reconnect(vt: VirtualTerminal) -> None:
    """paho reconnects by itself after sleep or a Wi-Fi change, but with clean_session the broker
    forgets the subscription. Subscribe again and re-announce presence on every reconnect."""
    client = vt._mqtt  # noqa: SLF001

    def on_connect(c, userdata, flags, reason_code, properties=None):
        if not reason_code.is_failure:
            c.subscribe(f"awaaz/v1/dev/{vt.device_id}/evt", qos=1)
            c.publish(f"awaaz/v1/dev/{vt.device_id}/status", "online", qos=1, retain=True)
            print("[terminal] MQTT (re)connected; subscribed to payment events")

    client.on_connect = on_connect


async def _startup() -> None:
    dev.loop = asyncio.get_running_loop()
    try:
        import httpx
        dev.bank_ok = httpx.get(dev.vt.api_base + "/healthz", timeout=3).status_code == 200
    except Exception:  # noqa: BLE001
        pass
    try:
        cfg = dev.vt._ok(dev.vt.request("GET", "/v1/device/config"))  # noqa: SLF001
        dev.merchant = cfg.get("merchant_name", dev.merchant)
        dev.payment_ttl_s = int(cfg.get("payment_ttl_s", 300))
    except Exception as exc:  # noqa: BLE001
        print(f"[terminal] warning: could not read device config: {exc}")
    if dev.vt.mqtt_host:
        try:
            dev.vt.connect_mqtt()
            dev.mqtt_mode = True
            _resubscribe_on_reconnect(dev.vt)
            print(f"[terminal] MQTT connected to {dev.vt.mqtt_host}:{dev.vt.mqtt_port}")
        except Exception as exc:  # noqa: BLE001
            print(f"[terminal] MQTT unavailable ({exc}); using signed HTTPS polling")
    threading.Thread(target=dev.mqtt_worker, daemon=True).start()
    threading.Thread(target=dev.poll_worker, daemon=True).start()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _startup()
    yield


app = FastAPI(title="Allied Awaaz laptop terminal", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/clips/{name}.wav")
def clip(name: str):
    path = CLIPS / f"{name}.wav"
    if not _CLIP_NAME.match(name) or not path.is_file():
        raise HTTPException(404, "no such clip")
    return FileResponse(path, media_type="audio/wav")


@app.get("/api/state")
def state():
    return {"merchant": dev.merchant, "device_id": dev.vt.device_id, "payment_ttl_s": dev.payment_ttl_s,
            "mqtt": dev.mqtt_connected(), "bank": dev.bank_ok, "api": dev.vt.api_base}


@app.post("/api/query")
def query(body: Query):
    payload = body.model_dump(exclude_none=True)
    if not payload.get("text") and not payload.get("intent"):
        raise HTTPException(422, "text or intent required")
    return dev.call(lambda: dev.vt._ok(dev.vt.request("POST", "/v1/device/query", payload)))  # noqa: SLF001


@app.post("/api/payments")
def payments(body: Amount):
    return dev.call(dev.vt.keypad_amount, body.amount_rupees)


@app.post("/api/confirm")
def confirm(body: Confirm):
    return dev.call(dev.vt.confirm, body.run_id)


@app.post("/api/voice")
async def voice(request: Request):
    wav = await request.body()
    if len(wav) > 2_000_000:
        raise HTTPException(413, "recording too long")

    def send() -> dict:
        return dev.vt._ok(dev.vt.request("POST", "/v1/device/voice", raw=wav, content_type="audio/wav"))  # noqa: SLF001

    return await asyncio.to_thread(dev.call, send)


@app.post("/api/cancel")
def cancel():
    with dev.lock:
        dev.current_txn = ""
    return {"ok": True}


@app.get("/api/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    dev.subscribers.add(q)

    async def stream():
        try:
            yield f"data: {json.dumps({'type': 'hello', 'mqtt': dev.mqtt_connected(), 'bank': dev.bank_ok})}\n\n"
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=10)
                except asyncio.TimeoutError:
                    ev = {"type": "presence", "mqtt": dev.mqtt_connected(), "bank": dev.bank_ok}
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            dev.subscribers.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    port = int(os.getenv("AWAAZ_TERMINAL_PORT", "8090"))
    print(f"[terminal] device {dev.vt.device_id} -> {dev.vt.api_base}; open http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
