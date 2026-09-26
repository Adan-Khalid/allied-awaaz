# Allied Awaaz

[![verify](https://github.com/Adan-Khalid/allied-awaaz/actions/workflows/verify.yml/badge.svg)](https://github.com/Adan-Khalid/allied-awaaz/actions/workflows/verify.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Next.js](https://img.shields.io/badge/console-Next.js-black)
![ESP32-S3](https://img.shields.io/badge/firmware-ESP32--S3-red)

Agentic, voice-first merchant banking terminal for the 5th Allied Bank Fintech Hackathon 2026
(theme: Agentic AI for Banking, Early Stage).

> **Proof of concept.** The payment gateway is **simulated**. This is not a Raast or Allied Bank
> integration, and it is not production banking software.

* **Payment Exception Agent** on the counter: voice or keypad QR requests, bank-verified Urdu
  announcements, and instant resolution of "customer says he paid" disputes.
* **Merchant Activation Agent** in the bank: deterministic health signals, drafted interventions,
  human approval on every action.

**Start with [docs/FINAL_GUIDE.md](docs/FINAL_GUIDE.md).** Architecture, security model and decisions:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Instructions for Claude Code: [CLAUDE.md](CLAUDE.md).

Verify everything with one command: `scripts/verify.sh --strict`.

## Repository

```
backend/    FastAPI service: payments, agents, simulator, console API, 50 tests
console/    Next.js bank console: merchants, approvals, disputes, agent reasoning, audit
firmware/   ESP32-S3 terminal (PlatformIO, Arduino core)
infra/      Mosquitto config and ACLs
tools/      virtual terminal, clip library builder, golden-file generator, device provisioning
scripts/    verify.sh (one-command acceptance), live and browser end-to-end tests, local broker
docs/       FINAL_GUIDE.md (start here), ARCHITECTURE.md
```

## Run the backend

```bash
cp .env.example .env                      # set AWAAZ_PUBLIC_BASE_URL to your laptop's LAN IP
# create broker passwords, see infra/mosquitto/README.md
docker compose up --build
```
Backend on :8000, console on :3000 (sign in with `dev-rm-token` or `dev-sup-token`).
Seeds Ahmed Pharmacy (device `awz-demo-001`) plus 24 synthetic merchants with healthy, declining,
dormant, offline, exception-spike and never-activated patterns.

Without Docker, for quick iteration:
```bash
cd backend && pip install -r requirements.txt
AWAAZ_DATABASE_URL=sqlite:///./awaaz.db AWAAZ_MQTT_ENABLED=false uvicorn app.main:app --reload
```

Console without Docker: see [console/README.md](console/README.md).

Tests:
```bash
cd backend && python -m pytest -q
```

## Drive it without hardware

```python
# backend/scripts: signed request helper (same scheme as the firmware)
import json, time, secrets, httpx
from app.security import sign_device_request
def call(method, path, body):
    raw = json.dumps(body).encode(); ts = str(int(time.time())); n = secrets.token_hex(8)
    h = {"X-Device-Id": "awz-demo-001", "X-Timestamp": ts, "X-Nonce": n, "Content-Type": "application/json",
         "X-Signature": sign_device_request("dev-device-secret-001", method, path, ts, n, raw)}
    return httpx.request(method, "http://localhost:8000" + path, content=raw, headers=h).json()

call("POST", "/v1/device/query", {"text": "1250 ka payment"})            # -> QR_READY + payer link
call("POST", "/v1/device/query", {"text": "customer keh raha hai 1730 bhej diye"})  # -> not received, case opened
call("POST", "/v1/device/query", {"intent": "TODAY_SUMMARY"})
```
Open the `qr_payload` link on a phone to reach the simulated payer page.

## Hardware (prototype)

| Part | Notes |
|------|-------|
| ESP32-S3-DevKitC-1 N16R8 | 16 MB flash for the clip library, 8 MB PSRAM for audio capture |
| 2.8" ILI9341 SPI TFT, 240x320 | pins in `platformio.ini` |
| INMP441 I2S MEMS microphone | pins in `include/pins.h` |
| MAX98357A I2S amplifier + 3 W 4 ohm speaker | |
| 4x4 membrane keypad | digits, `#` QR/confirm, `*` back, A today, B last, C claim check, D repeat |
| Push-to-talk | DevKit BOOT button (GPIO0) |
| USB-C 5 V supply | battery optional for the demo |

Flash:
```bash
cd firmware
cp include/config.h.example include/config.h     # Wi-Fi, backend IP, device secret
python ../tools/gen_clips.py --import-dir ../recordings   # placeholders already ship in data/clips
pio run -t uploadfs && pio run -t upload && pio device monitor
```
The firmware compiles cleanly for ESP32-S3 (RAM 14.7%, flash 15.6%). It has not yet run on physical hardware; follow the bring-up checklist in docs/FINAL_GUIDE.md.

## Live demo runbook (about 3 minutes)

| Step | Action | Expected |
|------|--------|----------|
| 1 | Merchant: "1250 ka payment" (or type 1250 #) | Terminal shows PKR 1,250 QR, says "... ka QR tayyar hai" |
| 2 | Judge scans, taps **PAY** on the payer page | Terminal: PAYMENT RECEIVED, "aik hazaar do sau pachaas rupay receive ho gaye" |
| 3 | New QR for 1730; judge does **not** pay, shows a screenshot instead. Merchant: "customer keh raha hai 1730 bhej diye" | "koi payment nahi aayi. maal abhi na dein. case darj" |
| 4 | New QR for 2500, judge picks **Stuck pending at payer bank**. Merchant asks again | "abhi pending hai ... maal abhi na dein"; case opens |
| 5 | "Aaj kitni payment aayi?" | "aaj 14 payments mein ... rupay receive hue" |
| 6 | Console: run activation sweep, open a DECLINING merchant, approve WhatsApp as supervisor | Draft shows evidence; RM token gets 403, supervisor approves; audit shows who and when |

Rehearse on a closed Wi-Fi hotspot. Keep keypad entry ready as the fallback for every voice step.

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first; security
reports go through [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
