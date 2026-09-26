# Allied Awaaz: System Architecture

Version 0.1, hackathon POC. Everything marked **SIMULATED** stands in for Allied Bank infrastructure
that a pilot would connect to. Nothing here claims to be the real Raast or ABL API.

## 1. What the system does

Two agents share one verified transaction ledger.

**Payment Exception Agent (merchant side, on the counter terminal).** Creates transaction-specific
QR requests by voice or keypad, announces payments only after bank-side confirmation, and resolves
the disputed or silent payment ("customer says 1730 bhej diye, aaye nahi") by investigating the
ledger and answering *received*, *pending at payer bank*, *failed* or *not received*, opening an ops
case with evidence when needed.

**Merchant Activation Agent (bank side, console).** Scores every merchant on deterministic health
signals, diagnoses the likely cause of dormancy or decline, drafts the playbook intervention with
evidence attached, and stops. A named staff member approves or rejects. Customer-facing messages
require a supervisor.

## 2. Component view

```
 Customer phone                                   ABL staff browser
 (payer page, SIMULATED)                          (Next.js console)
        |  HTTPS                                         |  HTTPS + staff token
        v                                                v
 +--------------------+   signed events   +-------------------------------------------+
 | Gateway simulator  | ----------------> |            Allied Awaaz backend           |
 | (SIMULATED ABL     |  (same verify     |  FastAPI                                  |
 |  acquiring switch) |   path as the     |  - payments: state machine, verification |
 +--------------------+   real webhook)   |  - agent: orchestrator + tool allowlist  |
                                          |  - health + interventions (activation)   |
       /v1/gateway/events  <------------  |  - audit log, agent run traces           |
       (pilot: ABL switch webhook)        +-------------------------------------------+
                                             |  PostgreSQL        |  MQTT publish (signed)
                                             v                    v
                                        [ledger, cases,     +-----------+   LWT presence
                                         runs, audit]       | Mosquitto | <-------------+
                                                            +-----------+               |
                                                                  | QoS 1               |
                                                                  v                     |
                                          +------------------------------------------+  |
                                          | ESP32-S3 terminal                        |--+
                                          | TFT + QR, keypad, PTT mic, I2S speaker   |
                                          | Signed HTTPS requests, verified MQTT     |
                                          +------------------------------------------+
```

Financial truth lives only in the backend database. The terminal is a secure presentation and
interaction endpoint. The LLM (optional) never sees balances and never produces a number the
merchant hears.

## 3. Key decisions

| # | Decision | Why | Trade-off accepted |
|---|----------|-----|--------------------|
| D1 | **MQTT** (Mosquitto) for backend-to-terminal push, not WebSocket | QoS 1 redelivery and persistent sessions survive flaky 4G/Wi-Fi behind NAT. The **Last Will** message gives device presence for free, and presence is a first-class input to the activation agent (DEVICE_OFFLINE). | One more service to run. Mitigated by a polling fallback over signed HTTPS. |
| D2 | **Explicit state machine** orchestrator, not a framework graph | Six fixed stages (observe, understand, plan, act, verify, respond) are easy to audit and test. No hidden loops, no model-chosen tool chains. | Less flexible for open-ended requests. That is the point for a banking terminal. |
| D3 | **Rules-first understanding**, closed-enum LLM fallback | Rules are instant, offline-capable and cannot hallucinate. The LLM is consulted only when rules return UNKNOWN, answers through a forced tool call with an enum schema, and any amount it proposes needs a keypad `#` confirmation. | Rule coverage must grow from real merchant recordings. |
| D4 | **Clip-concatenation speech**, no TTS in the loop | Every spoken number is rendered from a verified integer into pre-recorded clips (1..99 are irregular in Urdu, so each has a clip, plus sau/hazaar/lakh/crore and ~28 phrases, 130 total). Payment announcements are derived on the device from the signed amount, so even a compromised response channel cannot change what is spoken. Zero TTS latency, works offline. | New phrases need new clips. |
| D5 | **HMAC-SHA256** for device requests, gateway events and MQTT payloads | Fast on ESP32 (mbedTLS), simple to demo end to end. | Pilot moves the device key into a secure element (ATECC608 class) and the gateway to asymmetric signatures verified with ABL's public key. |
| D6 | **Transaction-specific requests**, not static QR | Exact amount, reference and expiry per sale. Enables precise matching for the exception agent. | Customer app must support dynamic Raast P2M QR, which the SBP standard provides. |
| D7 | PostgreSQL, SQLAlchemy, one service | Team size of three, 2 to 3 minute demo. One deployable is easier to secure and explain. | Split into payment, agent and console services only if a pilot demands it. |

## 4. Data model (backend/app/models.py)

| Table | Purpose | Notable constraints |
|-------|---------|---------------------|
| merchants | Merchant registry, RM ownership | |
| devices | Terminal identity, HMAC secret, presence, MQTT sequence counter | secret never leaves the server except at provisioning |
| payment_requests | One row per dynamic QR | amount in paisa, unique pay_token, state machine below |
| payment_events | Every verified gateway event | **unique event_id** = idempotency and replay protection |
| used_nonces | Device request replay store | unique (principal, nonce), pruned after 2x skew |
| exception_cases | Opened by the exception agent | CLAIM_NOT_FOUND, PENDING_AT_PAYER, PAYMENT_FAILED; PENDING cases auto-resolve on final event |
| agent_runs | Explainability trace, every step with inputs and results | pending_action holds confirm-before-act proposals |
| interventions | Activation agent drafts | PENDING_APPROVAL, APPROVED, EXECUTED, REJECTED; decided_by recorded |
| audit_log | Append-only record of every state change and decision | actor is device, gateway, agent run or named staff |

### Payment state machine

```
CREATED --> PENDING --> SUCCEEDED
   |           |
   |           +------> FAILED
   +--> SUCCEEDED / FAILED (direct)
CREATED --(expiry)--> EXPIRED --(late settlement)--> SUCCEEDED (flagged late)
```
Any other transition is rejected with 409. PENDING never expires locally, because money may already
be in flight at the payer bank; only a final gateway event closes it.

## 5. Agent design

### Merchant agent stages (backend/app/agent/orchestrator.py)

| Stage | What happens | Guarantee |
|-------|--------------|-----------|
| Observe | Transcript or keypad hotkey plus authenticated device and merchant | Merchant identity comes from the signed request, never from speech |
| Understand | intents.py rules, then llm.py fallback if UNKNOWN | Closed enum. Outbound money, loans and instruction-like text are refused |
| Plan | Intent to tool sequence, or clarify, or confirm-first | Model-derived or low-confidence amounts are never executed directly |
| Act | tools.py allowlist, per-agent | merchant_id injected server-side; args type and range checked |
| Verify | Re-read state before claiming success | e.g. created request exists, is CREATED, amount matches exactly |
| Respond | Fixed Urdu templates rendered from verified integers | Display text and clip plan come from the same numbers |

### Tool allowlist

| Tool | Agent | Notes |
|------|-------|-------|
| create_payment_request(amount_rupees) | merchant | 1 to AWAAZ_MAX_PAYMENT_RUPEES |
| get_payment_status(txn_id) | merchant | own merchant only |
| get_last_payment() | merchant | SUCCEEDED only |
| get_today_summary() | merchant | since local midnight, PKT (UTC+5) |
| find_payments(amount_rupees, window_min) | merchant | window 1 to 120 min |
| open_exception_case(type, amount, payment_id, evidence) | merchant | three case types only |
| get_device_status() | merchant | |
| get_merchant_health(merchant_id) | activation | deterministic signals |
| draft_intervention(merchant_id, reason_code) | activation | creates PENDING_APPROVAL only; dedupes open drafts |

There is no tool that moves money, changes limits, approves credit or runs arbitrary queries.

### Exception agent decision logic

```
find_payments(amount, last 15 min)
  SUCCEEDED match -> verify -> "1,730 rupay ki payment abhi abhi receive ho chuki hai"
  PENDING match   -> verify -> open/reuse PENDING_AT_PAYER case -> "abhi pending hai ... maal abhi na dein"
                               (case auto-resolves and terminal announces when gateway settles)
  FAILED match    -> open PAYMENT_FAILED case -> "payment fail ho gayi thi, customer dobara payment karein"
  nothing paid    -> open CLAIM_NOT_FOUND case -> "pichle 15 minute mein 1,730 rupay ki koi payment nahi aayi.
                                                  maal abhi na dein. case darj kar diya gaya hai"
```
A QR that was shown but never paid counts as *not received*: that is exactly the fake-screenshot case.

### Activation agent signals (backend/app/health.py)

| Code | Rule | Weight | Playbook channel | Approver |
|------|------|--------|------------------|----------|
| NEVER_ACTIVATED | no payment, onboarded 14+ days | 50 | field_visit | RM or supervisor |
| DORMANT | no payment for 7+ days | 45 | rm_call | RM or supervisor |
| DECLINING | usual 5+/week and last 7 days under 50% of it | 30 | whatsapp | **supervisor** |
| DEVICE_OFFLINE | terminal offline 24h+ (from MQTT LWT) | 25 | field_visit | RM or supervisor |
| EXCEPTION_SPIKE | 3+ exception cases in 14 days | 20 | ops_review | RM or supervisor |

Score = 100 minus weights. HEALTHY 80+, WATCH 50 to 79, AT_RISK under 50. Every flag stores the exact
numbers that triggered it, and those numbers travel with the draft to the approver.

## 6. Security model

### Integrity chain for "payment received"

1. Gateway event signed: `HMAC(gateway_key, ts + "." + body)`, freshness 300 s, unique event_id,
   amount must equal the request amount, transition must be legal.
2. Backend publishes to the terminal: `HMAC(device_secret, "v|type|seq|ts|txn|amount_minor|status")`
   with a per-device monotonic sequence number.
3. Terminal verifies signature, freshness (NTP-synced clock) and `seq > last_seq` (persisted in NVS)
   before announcing, then renders the amount into clips itself.

The customer's phone, screenshot or payer page can never mark anything paid.

### Threats and controls

| Threat | Control |
|--------|---------|
| Fake payment screenshot | Terminal announces only bank-confirmed events; exception agent answers "not received" and logs a case |
| Forged or replayed gateway event | Signature, freshness window, unique event_id, amount match, state machine |
| Spoofed MQTT message (broker or network compromise) | Per-device HMAC plus sequence plus freshness on the terminal; broker ACLs restrict topics per device |
| Stolen or cloned device request | Per-request HMAC over method, path, timestamp, nonce and body hash; nonce replay store; rate limit |
| Body tampering in transit | Body hash inside the signature (tested) |
| Prompt injection via speech | Transcript is data; rules refuse instruction-like input; LLM output limited to enum; tools cannot move money |
| Hallucinated totals or balances | Numbers only from deterministic queries; templates, not generated text |
| Cross-merchant data access | merchant_id injected from the authenticated device, never from input (tested) |
| Unauthorised outreach to merchants | Drafts only; named approval; role gate for customer-facing messages; full audit |
| Voice replay or impersonation near the counter | Voice can only create requests and read own summaries. Nothing voice-initiated moves money. Pilot: sensitive future actions require keypad PIN |
| Privacy | LLM sees only the utterance. Audio is not stored. Payer identity stored masked |

### Pilot hardening (not in POC)

TLS 1.2+ everywhere with certificate pinning on the terminal; device keys in a secure element;
MQTT over 8883 with per-device client certificates; gateway events signed with ABL's asymmetric key;
KMS-encrypted secrets at rest; secure boot and flash encryption on ESP32-S3; signed OTA; API gateway
rate limiting; SIEM export of the audit log.

## 7. API contracts

### Device (all HMAC-signed)

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | /v1/device/config | | merchant name, limits |
| POST | /v1/device/payments | `{"amount_rupees":1250}` | agent response with `action.type = show_qr` |
| GET | /v1/device/payments/{txn} | | status (polling fallback) |
| POST | /v1/device/query | `{"text":"..."}` or `{"intent":"TODAY_SUMMARY"}` or `{"intent":"CHECK_CLAIM","amount_rupees":1730}` | agent response |
| POST | /v1/device/voice | raw WAV, 16 kHz mono | agent response plus transcript |
| POST | /v1/device/confirm | `{"run_id":"run_..."}` | executes a pending agent proposal |

Agent response:
```json
{"run_id":"run_ab12","intent":"CHECK_CLAIM","understood_by":"rules","outcome":"CLAIM_NOT_RECEIVED",
 "display_text":"pichle 15 minute mein 1,730 rupay ki koi payment nahi aayi. maal abhi na dein. case darj kar diya gaya hai",
 "speech":{"clips":["pichle","n_15","minute_mein","n_1","hazaar","n_7","sau","n_30","rupay", "..."],"spoken_text":"..."},
 "action":{"type":"claim_result","result":"NOT_RECEIVED","case_id":"case_9f"},"requires_confirmation":false}
```

### Console (Bearer staff token)

`GET /v1/console/merchants`, `GET /v1/console/merchants/{id}`, `GET /v1/console/exceptions`,
`POST /v1/console/activation/sweep`, `GET /v1/console/interventions`,
`POST /v1/console/interventions/{id}/approve|reject`, `GET /v1/console/agent-runs`, `GET /v1/console/audit`.

### Gateway

`POST /v1/gateway/events` with `X-Gw-Timestamp`, `X-Gw-Signature`. The simulator uses the same code path.

## 8. Failure modes

| Failure | Behaviour |
|---------|-----------|
| MQTT down | Terminal polls payment status every 3 s over signed HTTPS; LWT marks it offline for the bank |
| Speech unavailable or misheard | Keypad always works; ambiguous amounts ask again; STT outage returns a keypad prompt |
| Payer bank slow | PENDING shown on terminal; claim check says pending and opens a case; auto-resolves on settlement |
| QR expires unpaid | Terminal shows expiry; late settlement is still accepted and flagged |
| Duplicate gateway delivery | Idempotent on event_id; no double announcement (terminal also dedupes txn ids) |
| Clock drift on device | NTP at boot; stale messages rejected rather than trusted |

## 9. What is simulated vs real

| Real in the POC | Simulated |
|-----------------|-----------|
| Signed device protocol, replay protection, rate limiting | ABL acquiring switch and Raast settlement |
| Payment state machine and idempotent event ingestion | Raast P2M QR payload (demo uses a payer-page URL; terminal treats payload as opaque) |
| Both agents, tool allowlist, traces, approvals, audit | Merchant base and history (synthetic, seeded) |
| MQTT push with LWT presence | WhatsApp, CRM and ops dispatch (recorded, not sent) |
| ESP32-S3 terminal firmware | |

## 10. Open decisions

1. **Urdu STT provider.** Benchmark at least two options on 50+ real counter recordings (noise, code-switching,
   amounts) before the demo. Adapter is provider-agnostic (`AWAAZ_STT_PROVIDER`).
2. **ABL Developer Portal access.** If sandbox APIs are granted, replace the simulator behind `/v1/gateway/events`.
3. **Voice for clips.** Record one consistent human voice (`tools/gen_clips.py --list` gives the 130-line sheet).
4. **BOM and connectivity.** Price 4G Cat-1 vs Wi-Fi-only production variants before quoting unit cost.
5. **Pilot metrics.** Confirm with ABL which of activation, frequency, volume, dormancy and dispute rate they track today.

## 11. Verification

`scripts/verify.sh --strict` runs seven stages: backend unit tests (SQLite and Postgres), the firmware
protocol core against golden files generated from the backend (`tools/gen_golden.py`), the ESP32-S3 build,
the console build, a live end-to-end run with a real broker and `tools/virtual_terminal.py` (a software twin
of the firmware protocol), and a browser run against the console. See docs/FINAL_GUIDE.md section 3.
