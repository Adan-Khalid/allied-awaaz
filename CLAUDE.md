# CLAUDE.md: instructions for Claude Code

You are receiving **Allied Awaaz**, a hackathon product for the 5th Allied Bank Fintech Hackathon 2026
(theme: Agentic AI for Banking). Your job is to **set up the environment, run the full verification,
and report whether the product meets its acceptance criteria.** Read `docs/FINAL_GUIDE.md` for the
product itself; this file tells you how to verify it.

## 1. Rules

1. **Never edit tests, golden files or acceptance scripts to make them pass.** If a check fails, fix the
   product code, or report the failure. Files you must not weaken:
   `backend/tests/**`, `firmware/test/**`, `scripts/e2e_live.py`, `scripts/e2e_console.py`, `scripts/verify.sh`.
2. **Do not break the security invariants** in section 5. A change that passes tests but violates one is a failure.
3. The payment gateway is **SIMULATED** by design. Do not describe it as Raast or ABL integration.
4. Do not commit secrets. `.env`, `firmware/include/config.h` and `infra/mosquitto/passwd` are git-ignored.
5. If a stage cannot run because a tool is missing, install the tool (section 2). Do not accept SKIP.

## 2. Environment setup

Required: Python 3.11+, Node.js 20+, g++, Mosquitto, PlatformIO, Chromium for Playwright, PostgreSQL 16.

Ubuntu / Debian:
```bash
sudo apt-get update && sudo apt-get install -y python3-pip g++ mosquitto mosquitto-clients
sudo systemctl stop mosquitto 2>/dev/null || true          # verify.sh starts its own broker on a free port
pip install -r backend/requirements.txt -r scripts/requirements.txt
python -m playwright install --with-deps chromium
docker run -d --name awaaz-pg -p 5432:5432 -e POSTGRES_USER=awaaz -e POSTGRES_PASSWORD=awaaz \
  -e POSTGRES_DB=awaaz_test postgres:16-alpine
export AWAAZ_TEST_DATABASE_URL=postgresql+psycopg://awaaz:awaaz@localhost:5432/awaaz_test
```

macOS: `brew install mosquitto node python`, then the same `pip`, `playwright` and `docker` lines.

Windows: use WSL2 (Ubuntu) and follow the Ubuntu steps.

On pip "externally managed environment" errors, use a virtualenv (`python3 -m venv .venv && . .venv/bin/activate`).

## 3. Run the verification

```bash
scripts/verify.sh --strict
```

It picks free ports, starts its own broker, backend and console, and cleans up afterwards.
Set `VERIFY_KEEP=1` to keep logs for debugging. Expected output:

```
backend-unit       PASS 50 passed
backend-postgres   PASS 50 passed
firmware-core      PASS firmware core OK: 5117 amount cases, 70 canonical cases, 6 unit checks
firmware-build     PASS RAM ... Flash ...
console-build      PASS typecheck + production build
live-e2e           PASS 16/16 live acceptance checks passed
console-e2e        PASS 12/12 console acceptance checks passed
RESULT: PASS (all stages)
```

The first `firmware-build` run downloads the ESP32 toolchain (about 500 MB, several minutes).

Also confirm the Docker path works:
```bash
cp .env.example .env
docker run --rm -v "$PWD/infra/mosquitto:/m" eclipse-mosquitto:2 sh -c \
  "mosquitto_passwd -b -c /m/passwd awaaz-backend change-me-mqtt-backend && mosquitto_passwd -b /m/passwd awz-demo-001 device-mqtt-password"
docker compose up --build -d
curl -fs http://localhost:8000/healthz && curl -fs -o /dev/null http://localhost:3000/login && echo STACK_OK
docker compose down
```

## 4. Acceptance criteria

**Automated (all must PASS in strict mode):** the seven stages above.

**What the automated stages prove:**

| Requirement | Proven by |
|-------------|-----------|
| Dynamic QR by voice or keypad, verified before display | live-e2e demo 1, keypad check; backend test_agent |
| Terminal announces only bank-signed, fresh, in-sequence events | live-e2e demo 2, forged-message check; firmware-core |
| Spoken amount derived from the signed integer, identical on firmware and backend | firmware-core golden files |
| Exception agent answers received / pending / failed / not received and raises cases | live-e2e demos 3 and 4, failed-payment check |
| Pending cases auto-resolve on settlement | live-e2e demo 4 |
| Totals come from the ledger, never from a model | live-e2e demo 5 (exact arithmetic) |
| Money-out, loans and prompt injection refused with no state change | live-e2e security check; backend tests |
| Replay, body tampering, stale timestamps, unknown devices rejected | backend test_security; live-e2e replay check |
| Activation agent drafts evidence-backed interventions; humans approve; role gate | live-e2e demo 6 and gate; console-e2e |
| Every decision traceable (agent steps, audit log) | console-e2e reasoning, disputes, audit checks |
| Device presence from MQTT Last Will | live-e2e power-loss check |
| Console works on desktop and mobile with no browser errors | console-e2e |
| Firmware builds for ESP32-S3 | firmware-build |

**Manual (report as NOT VERIFIABLE BY CLAUDE CODE; do not mark passed):**
1. Firmware running on physical hardware (bring-up checklist, FINAL_GUIDE section 8).
2. Human-recorded Urdu voice clips replacing the espeak placeholders.
3. Urdu speech-to-text accuracy on real shop recordings.
4. Current hackathon dates and rules on Allied Bank's official page.

## 5. Security invariants (must hold after any change)

1. Only `payments.ingest_gateway_event` changes payment state, and only after signature, freshness,
   event-id idempotency, amount match and a legal state transition.
2. The terminal announces a payment only from an HMAC-verified MQTT message with a fresh timestamp and a
   sequence number greater than the last one seen, or from its own signed HTTPS status read.
3. Agent tools receive `merchant_id` and device from the authenticated context, never from user or model input.
4. No agent tool moves money, changes limits, approves credit or runs arbitrary queries.
5. Spoken and displayed numbers are rendered from verified integers through templates (`urdu.render`).
6. An LLM-proposed amount is never executed without the merchant's keypad confirmation.
7. Interventions reach merchants only after a named staff approval; WhatsApp needs the supervisor role.
8. Every state change and decision writes an audit log entry.

## 6. Report format

When done, report:
1. The verify summary table and the RESULT line.
2. The Docker path result (STACK_OK or the error).
3. Any product code you changed and why (tests must be untouched).
4. The four manual items, listed as not verifiable by you.
5. Verdict: **APPROVED** only if all seven stages pass in strict mode, the Docker path works and no
   security invariant is violated. Otherwise **NOT APPROVED**, with the failing items.
