#!/usr/bin/env python3
"""Smoke test for the laptop terminal (tools/laptop_terminal).

Against a running backend and laptop terminal: create a QR through the terminal, pay it on the
simulated payer API, and require a verified "paid" event on the terminal's event stream with the
right amount and clips. Also checks that the device secret never reaches the browser side.

    AWAAZ_API=http://localhost:8000 AWAAZ_TERMINAL=http://127.0.0.1:8090 python scripts/smoke_laptop_terminal.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import httpx

API = os.getenv("AWAAZ_API", "http://localhost:8000")
TERM = os.getenv("AWAAZ_TERMINAL", "http://127.0.0.1:8090")
SECRET = os.getenv("AWAAZ_DEMO_DEVICE_SECRET", "dev-device-secret-001")


def main() -> int:
    events: list[dict] = []

    def listen() -> None:
        with httpx.stream("GET", TERM + "/api/events", timeout=None) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

    threading.Thread(target=listen, daemon=True).start()

    state = httpx.get(TERM + "/api/state", timeout=5).json()
    page = httpx.get(TERM + "/", timeout=5).text
    assert SECRET not in json.dumps(state) and SECRET not in page, "device secret exposed to the browser"
    assert state["bank"], f"terminal cannot reach the backend: {state}"

    r = httpx.post(TERM + "/api/payments", json={"amount_rupees": 1250}, timeout=15).json()
    action = r["action"]
    assert action["type"] == "show_qr" and action["amount_rupees"] == 1250, r
    assert r["qr_svg"].startswith("data:image/svg+xml"), "QR image missing"
    token = action["qr_payload"].rsplit("/", 1)[-1]

    paid = httpx.post(f"{API}/sim/pay/{token}", json={"scenario": "success"}, timeout=10).json()
    assert paid["status"] == "SUCCEEDED", paid

    deadline = time.time() + 15
    while time.time() < deadline:
        hit = [e for e in events if e.get("type") == "paid" and e.get("txn") == action["txn_id"]]
        if hit:
            e = hit[0]
            assert e["rupees"] == 1250, e
            assert e["clips"] == ["n_1", "hazaar", "n_2", "sau", "n_50", "rupay", "receive_ho_gaye"], e
            clip = httpx.get(TERM + "/clips/receive_ho_gaye.wav", timeout=5)
            assert clip.status_code == 200 and clip.content[:4] == b"RIFF", "clip not served"
            assert httpx.get(TERM + "/clips/..%2Fsecret.wav", timeout=5).status_code == 404
            print(f"laptop terminal OK: QR -> verified payment via {e['source']} -> announced PKR 1,250")
            return 0
        time.sleep(0.2)
    print(f"no verified paid event; events seen: {events}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
