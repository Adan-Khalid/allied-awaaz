#!/usr/bin/env python3
"""Virtual Allied Awaaz terminal.

A byte-for-byte software twin of the ESP32 firmware protocol:
  * HMAC-signed HTTP requests (same canonical string as firmware/src/net.cpp)
  * MQTT session with Last Will "offline" and retained "online" presence
  * inbound payment messages verified exactly like the firmware: HMAC, freshness,
    strictly increasing sequence, and the spoken amount derived locally from the
    signed integer (same clip rules as firmware/src/speech.cpp)

Uses: acceptance tests without hardware (scripts/e2e_live.py), and a backup demo
terminal on a laptop if the physical device fails on stage.

    python tools/virtual_terminal.py --say "1250 ka payment"
    python tools/virtual_terminal.py --interactive
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import queue
import secrets
import sys
import time
from dataclasses import dataclass, field

import httpx

MULTS = [(10_000_000, "crore"), (100_000, "lakh"), (1_000, "hazaar"), (100, "sau")]


def number_clips(n: int) -> list[str]:
    """Independent re-implementation of the firmware rule (not imported from the backend on purpose)."""
    if n == 0:
        return ["zero"]
    out: list[str] = []
    for value, word in MULTS:
        q, n = divmod(n, value)
        if q:
            out += number_clips(q) if (value == 10_000_000 and q >= 100) else [f"n_{q}"]
            out.append(word)
    if n:
        out.append(f"n_{n}")
    return out


def payment_received_clips(rupees: int) -> list[str]:
    return number_clips(rupees) + ["rupay", "receive_ho_gaye"]


def _hmac(key: str, msg: str) -> str:
    return hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


@dataclass
class Announcement:
    txn: str
    status: str
    amount_minor: int
    clips: list[str]
    seq: int


@dataclass
class VirtualTerminal:
    api_base: str
    device_id: str
    secret: str
    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_password: str = ""
    max_skew_s: int = 300
    last_seq: int = 0
    announcements: "queue.Queue[Announcement]" = field(default_factory=queue.Queue)
    rejected: list[str] = field(default_factory=list)
    _mqtt: object = None

    # ---------------------------------------------------------------- HTTP
    def request(self, method: str, path: str, body: dict | None = None, raw: bytes | None = None,
                content_type: str = "application/json") -> httpx.Response:
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        ts, nonce = str(int(time.time())), secrets.token_hex(12)
        canonical = f"{method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(data).hexdigest()}"
        headers = {"X-Device-Id": self.device_id, "X-Timestamp": ts, "X-Nonce": nonce,
                   "X-Signature": _hmac(self.secret, canonical)}
        if data:
            headers["Content-Type"] = content_type
        return httpx.request(method, self.api_base + path, content=data, headers=headers, timeout=15)

    def say(self, text: str) -> dict:
        return self._ok(self.request("POST", "/v1/device/query", {"text": text}))

    def key(self, intent: str, amount: int | None = None) -> dict:
        body: dict = {"intent": intent}
        if amount is not None:
            body["amount_rupees"] = amount
        return self._ok(self.request("POST", "/v1/device/query", body))

    def keypad_amount(self, rupees: int) -> dict:
        return self._ok(self.request("POST", "/v1/device/payments", {"amount_rupees": rupees}))

    def confirm(self, run_id: str) -> dict:
        return self._ok(self.request("POST", "/v1/device/confirm", {"run_id": run_id}))

    def poll_status(self, txn: str) -> dict:
        return self._ok(self.request("GET", f"/v1/device/payments/{txn}"))

    @staticmethod
    def _ok(r: httpx.Response) -> dict:
        if r.status_code != 200:
            raise RuntimeError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text}")
        return r.json()

    # ---------------------------------------------------------------- MQTT
    def connect_mqtt(self) -> None:
        import paho.mqtt.client as mqtt

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.device_id, clean_session=True)
        c.username_pw_set(self.device_id, self.mqtt_password)
        status_topic = f"awaaz/v1/dev/{self.device_id}/status"
        c.will_set(status_topic, "offline", qos=1, retain=True)
        c.on_message = self._on_message
        c.connect(self.mqtt_host, self.mqtt_port, keepalive=10)
        c.loop_start()
        deadline = time.time() + 5
        while not c.is_connected() and time.time() < deadline:
            time.sleep(0.05)
        if not c.is_connected():
            raise RuntimeError("MQTT connect failed (check broker credentials/ACL)")
        c.subscribe(f"awaaz/v1/dev/{self.device_id}/evt", qos=1)
        c.publish(status_topic, "online", qos=1, retain=True)
        self._mqtt = c

    def drop_mqtt_ungracefully(self) -> None:
        """Simulates power loss: the broker must publish the Last Will."""
        c = self._mqtt
        c.loop_stop()
        c._sock.close()  # noqa: SLF001  no DISCONNECT packet, so the LWT fires
        self._mqtt = None

    def _on_message(self, client, userdata, msg) -> None:
        try:
            m = json.loads(msg.payload)
            canonical = f"{m['v']}|{m['type']}|{m['seq']}|{m['ts']}|{m['txn']}|{m['amount_minor']}|{m['status']}"
        except (ValueError, KeyError):
            self.rejected.append("malformed")
            return
        if not hmac.compare_digest(_hmac(self.secret, canonical), str(m.get("sig", ""))):
            self.rejected.append("bad_signature")
            return
        if abs(time.time() - int(m["ts"])) > self.max_skew_s:
            self.rejected.append("stale")
            return
        if int(m["seq"]) <= self.last_seq:
            self.rejected.append("replay")
            return
        self.last_seq = int(m["seq"])
        clips = payment_received_clips(int(m["amount_minor"]) // 100) if m["status"] == "SUCCEEDED" else []
        self.announcements.put(Announcement(m["txn"], m["status"], int(m["amount_minor"]), clips, self.last_seq))

    def wait_for(self, txn: str, status: str, timeout: float = 10) -> Announcement:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                a = self.announcements.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if a.txn == txn and a.status == status:
                return a
        raise TimeoutError(f"no verified {status} message for {txn}")


def from_env() -> VirtualTerminal:
    return VirtualTerminal(
        api_base=os.getenv("AWAAZ_API", "http://localhost:8000"),
        device_id=os.getenv("AWAAZ_DEVICE_ID", "awz-demo-001"),
        secret=os.getenv("AWAAZ_DEMO_DEVICE_SECRET", "dev-device-secret-001"),
        mqtt_host=os.getenv("AWAAZ_MQTT_HOST"),
        mqtt_port=int(os.getenv("AWAAZ_MQTT_PORT", "1883")),
        mqtt_password=os.getenv("AWAAZ_DEVICE_MQTT_PASSWORD", ""),
    )


def _print(r: dict) -> None:
    print(f"[{r.get('outcome')}] {r.get('display_text')}")
    if r.get("action", {}) and r["action"].get("qr_payload"):
        print(f"  QR: {r['action']['qr_payload']}")
    print(f"  speaks: {' '.join(r.get('speech', {}).get('clips', []))}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--say")
    ap.add_argument("--interactive", action="store_true")
    a = ap.parse_args()
    t = from_env()
    if t.mqtt_host:
        t.connect_mqtt()
    if a.say:
        _print(t.say(a.say))
    if a.interactive:
        print("Type what the merchant says. Blank line to quit.")
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                break
            if not line:
                break
            _print(t.say(line))
            while not t.announcements.empty():
                ann = t.announcements.get()
                print(f"  ** verified {ann.status} {ann.amount_minor // 100}: {' '.join(ann.clips)}")
    sys.exit(0)
