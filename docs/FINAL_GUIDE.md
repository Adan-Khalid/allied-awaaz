# Allied Awaaz: Final Product Guide

Version 1.0 · 26 September 2026 · 5th Allied Bank Fintech Hackathon 2026 (with LUMS)
Theme: **Agentic AI for Banking** · Category: **Early Stage**

This is the single document to read. It covers what the product is, how to run and verify it,
how to demo it, how to bring up the hardware, and what remains manual.
Deep technical design lives in [ARCHITECTURE.md](ARCHITECTURE.md). Instructions for an automated
reviewer (Claude Code) live in [../CLAUDE.md](../CLAUDE.md).

---

## 1. The product in one page

**Problem.** Pakistan's QR problem has moved from registration to reliable, repeated use. At a busy
counter a silent or delayed confirmation forces the shopkeeper to choose between trusting a customer's
screenshot and holding up the sale. Soundboxes already exist in Pakistan (Easypaisa, Zindigi, Tapsys)
and AI soundboxes exist in India (Paytm, ToneTag). None of them resolves the disputed or silent payment,
and none gives the bank an agent that acts on merchant inactivity.

**Solution.** Two agents on one verified ledger.

| | Payment Exception Agent | Merchant Activation Agent |
|---|---|---|
| Where | Counter terminal (ESP32-S3) | Bank console (Next.js) |
| User | Shopkeeper | Relationship manager, supervisor |
| Does | Creates a transaction-specific QR by voice or keypad; announces payment in Urdu only after bank-side confirmation; answers "customer says he paid 1730, did it arrive?" with received, pending, failed or not received; raises a case with evidence | Scores every merchant from ledger signals; diagnoses dormancy, decline, offline terminal, dispute spikes, never activated; drafts the playbook intervention with evidence; waits for human approval |
| Human control | LLM-proposed amounts need a keypad confirmation | Nothing reaches a merchant without a named approval; WhatsApp needs a supervisor |

**Why it is agentic, not a chatbot.** Each run follows observe, understand, plan, act (allowlisted tools
only), verify (re-read state before claiming success), respond (fixed templates from verified numbers).
Every step is stored and shown in the console.

**What Allied Bank gets.** More active QR merchants, higher transaction frequency, fewer dormant accounts,
lower dispute friction, and an auditable record of every agent decision.

---

## 2. What is in the repository

```
backend/     FastAPI: payments, both agents, simulated gateway, console API       (50 tests)
console/     Next.js 15 bank console                                               (12 browser checks)
firmware/    ESP32-S3 terminal: display, QR, keypad, push-to-talk, speaker        (compiles; 5,187 host cases)
  data/clips/  130 placeholder Urdu clips (replace with a human voice before the demo)
tools/       virtual_terminal.py, gen_clips.py, gen_golden.py, provision_device.py
scripts/     verify.sh, e2e_live.py (16 checks), e2e_console.py, local_broker.sh
infra/       Mosquitto config and per-device ACLs
docs/        FINAL_GUIDE.md (this file), ARCHITECTURE.md
.github/     CI workflow running verify.sh --strict
```

---

## 3. Verification status

Verified in the build environment on 26 September 2026:

| Stage | Result | What it covers |
|-------|--------|----------------|
| backend-unit | PASS, 50/50 | Security, payments, both agents, parser, approvals (SQLite) |
| backend-postgres | PASS, 50/50 | Same suite on PostgreSQL 16 |
| firmware-core | PASS | C++ protocol core matches backend on 5,117 amounts and 70 signing cases |
| firmware-build | PASS | ESP32-S3 build, RAM 14.7%, flash 15.6%, no warnings in project code |
| console-build | PASS | TypeScript check and production build |
| live-e2e | PASS, 16/16 | Real broker, backend and virtual terminal: full demo, failures, attacks, presence |
| console-e2e | PASS, 12/12 | Real browser: login, triage, sweep, role gate, reasoning, disputes, audit, mobile |

Bugs found and fixed during verification: seed data violated foreign keys on Postgres; SQLite dev mode
shared one connection across requests; login lost input typed before hydration; the console signed users
out on network blips instead of only on 401; the console polled before sign-in; missing favicon.

**Reproduce:** `scripts/verify.sh --strict` (setup in CLAUDE.md section 2).

**Manual items that no automated test can prove** (section 11): firmware on physical hardware, recorded
Urdu voice, Urdu speech-to-text accuracy, current hackathon rules.

---

## 4. Run it

### Docker (demo laptop)
```bash
cp .env.example .env            # set AWAAZ_PUBLIC_BASE_URL to the laptop's LAN IP; change every secret
docker run --rm -v "$PWD/infra/mosquitto:/m" eclipse-mosquitto:2 sh -c \
  "mosquitto_passwd -b -c /m/passwd awaaz-backend '<AWAAZ_MQTT_PASSWORD>' && \
   mosquitto_passwd -b /m/passwd awz-demo-001 '<device mqtt password>'"
docker compose up --build
```
Backend on http://localhost:8000, console on http://localhost:3000. Sign in with the tokens in
`AWAAZ_STAFF_TOKENS`. The database seeds Ahmed Pharmacy (terminal `awz-demo-001`) and 24 synthetic
merchants with healthy, declining, dormant, offline, dispute-spike and never-activated patterns.

### Local development
```bash
cd backend && pip install -r requirements.txt
AWAAZ_DATABASE_URL=sqlite:///./awaaz.db AWAAZ_MQTT_ENABLED=false uvicorn app.main:app --reload
cd console && npm install && npm run dev
python tools/virtual_terminal.py --interactive        # software terminal, no hardware needed
```

### Configuration reference (backend)

| Variable | Default | Purpose |
|----------|---------|---------|
| AWAAZ_DATABASE_URL | postgresql+psycopg://awaaz:awaaz@localhost:5432/awaaz | Database |
| AWAAZ_PUBLIC_BASE_URL | http://localhost:8000 | Base of QR payer links; must be reachable by the payer phone |
| AWAAZ_GATEWAY_SIGNING_KEY | dev key | Simulated gateway event signing |
| AWAAZ_DEMO_DEVICE_SECRET | dev-device-secret-001 | HMAC secret of `awz-demo-001`; must match firmware `DEVICE_SECRET` |
| AWAAZ_MQTT_ENABLED / HOST / PORT / USERNAME / PASSWORD | true, localhost, 1883, awaaz-backend, empty | Broker |
| AWAAZ_MAX_PAYMENT_RUPEES | 500000 | Hard limit per request, enforced in tool schemas |
| AWAAZ_PAYMENT_TTL_S | 300 | QR expiry |
| AWAAZ_CLAIM_WINDOW_MIN | 15 | Exception agent search window |
| AWAAZ_SIM_SLOW_DELAY_S | 20 | Delay for the "payer bank slow" demo scenario |
| AWAAZ_STAFF_TOKENS | dev tokens | `token:role:Name,...`, roles `rm` and `supervisor` |
| AWAAZ_CORS_ORIGINS | http://localhost:3000 | Console origin |
| AWAAZ_STT_PROVIDER / BASE_URL / API_KEY / MODEL / LANGUAGE | none | Speech-to-text; `none` means keypad and text only |
| AWAAZ_LLM_ENABLED / ANTHROPIC_API_KEY / AWAAZ_LLM_MODEL | false | Optional intent fallback |

Console: `NEXT_PUBLIC_API_BASE` (backend URL, baked in at build time).

---

## 5. Live demo runbook (about 3 minutes)

Setup: laptop running the stack on a private hotspot; terminal on the same network; judge's phone on the
hotspot; console open in two browser windows (RM and supervisor).

| # | Say or do | Terminal shows and says | Console |
|---|-----------|-------------------------|---------|
| 1 | "1250 ka payment" (or type 1250 #) | PKR 1,250 QR; "... ka QR tayyar hai" | |
| 2 | Judge scans, taps **PAY** | PAYMENT RECEIVED; "aik hazaar do sau pachaas rupay receive ho gaye" | |
| 3 | New QR for 1730. Judge does not pay and shows a screenshot. "Customer keh raha hai 1730 bhej diye" | "pichle 15 minute mein 1,730 rupay ki koi payment nahi aayi. maal abhi na dein. case darj kar diya gaya hai" | Dispute appears within 5 s |
| 4 | New QR for 2500; judge picks **Stuck pending at payer bank**; ask again | "abhi pending hai ... maal abhi na dein" | Case shows pending |
| 5 | "Aaj kitni payment aayi?" | "aaj 14 payments mein ... rupay receive hue" | |
| 6 | Console: Find merchants who need attention; open a WhatsApp draft; RM cannot approve, supervisor approves | | Evidence, agent reasoning, audit entry |

Closing line: *One terminal, more active merchants, more digital payments, a deeper Allied relationship.*

**Fallbacks.** Keypad for every voice step. If the device fails, run `python tools/virtual_terminal.py
--interactive` on the laptop; it speaks the same protocol. If the network fails, the terminal polls over
signed HTTPS when MQTT drops.

**Rehearsal check:** run `scripts/verify.sh` the morning of the demo.

---

## 6. Security model (summary)

The chain for "payment received": gateway event signed and fresh, unique event id, amount must match,
legal transition; backend publishes an HMAC-signed message with a per-device sequence number; the terminal
verifies signature, freshness and sequence, then derives the spoken amount itself from the signed integer.
Screenshots, the payer page and the customer's phone can never mark a payment as paid.

Device requests carry an HMAC over method, path, timestamp, nonce and body hash, with a nonce replay store
and rate limit. Agent tools are allowlisted per agent, scoped to the authenticated merchant and range
checked. No tool moves money. Every decision is audit-logged. Full threat table: ARCHITECTURE.md section 6.

---

## 7. Hardware

### Prototype bill of materials (indicative Pakistan retail, verify locally)

| Part | Qty | Approx. PKR |
|------|-----|-------------|
| ESP32-S3-DevKitC-1 N16R8 | 1 | 3,500 to 5,000 |
| 2.8" ILI9341 SPI TFT 240x320 | 1 | 2,000 to 3,000 |
| INMP441 I2S microphone | 1 | 600 to 1,000 |
| MAX98357A I2S amplifier | 1 | 700 to 1,200 |
| 3 W 4 ohm speaker | 1 | 300 to 600 |
| 4x4 membrane keypad | 1 | 250 to 500 |
| Wires, breadboard or perfboard, USB-C cable, enclosure | 1 set | 1,000 to 2,500 |
| **Prototype total** | | **about 8,500 to 14,000** |

Production estimates are not claimed until component quotes and the 4G vs Wi-Fi decision are made.

### Wiring

| Signal | ESP32-S3 GPIO |
|--------|---------------|
| TFT MOSI / SCLK / CS / DC / RST / BL | 11 / 12 / 10 / 9 / 14 / 21 |
| Amplifier BCLK / LRC / DIN | 4 / 5 / 6 |
| Microphone SCK / WS / SD (L/R to GND) | 15 / 16 / 17 |
| Push-to-talk | 0 (DevKit BOOT button) |
| Status LED | 2 |
| Keypad rows | 38, 39, 40, 41 |
| Keypad columns | 42, 18, 8, 7 |

Power the amplifier from 5 V, everything else from 3.3 V; common ground.

### Keypad map
Digits enter an amount · `#` create QR or confirm · `*` back or cancel · `A` today's total ·
`B` last payment · `C` "payment aayi?" for the typed amount · `D` repeat last announcement.

---

## 8. Hardware bring-up checklist

1. `cp firmware/include/config.h.example firmware/include/config.h`; set Wi-Fi, backend IP, MQTT host,
   `DEVICE_SECRET` (must equal `AWAAZ_DEMO_DEVICE_SECRET`) and the device MQTT password.
2. `cd firmware && pio run -t uploadfs` (clips), then `pio run -t upload && pio device monitor`.
3. Display: boot screen, then Ahmed Pharmacy idle screen with "Bank connected".
4. Audio: press `D` after any reply; placeholder clips should play clearly with no clicks between words.
5. Keypad: type 1250 `#`; QR appears; scan with a phone on the same network; payer page opens.
6. MQTT: tap PAY; announcement within 1 s. Serial must show no "bad sig" or "stale" lines.
7. Clock: if announcements are rejected as stale, check NTP reachability (the device needs internet time).
8. Presence: unplug the device; within about 45 s the console shows the terminal offline.
9. Microphone: set `AWAAZ_STT_PROVIDER`; hold BOOT, say "1250 ka payment", release. If the transcript is
   empty, check mic wiring and the `>> 14` gain shift in `speech.cpp`.
10. Polling fallback: stop the broker, create and pay a QR; the terminal still announces within about 3 s.

---

## 9. Voice and speech

**Clips.** `tools/gen_clips.py --list` produces the 130-line recording sheet (numbers 1 to 99 are
irregular in Urdu, so each has its own clip). Record one consistent human voice, name files `<clip_id>.wav`,
then `python tools/gen_clips.py --import-dir recordings` and `pio run -t uploadfs`. Placeholders from
espeak-ng ship so bring-up can start immediately; they are not demo quality.

**Speech-to-text.** The adapter accepts any OpenAI-compatible transcription endpoint
(`AWAAZ_STT_PROVIDER=openai_compatible`). Before choosing, record 50 or more real counter utterances with
background noise, amounts and Urdu-English mixing, and compare at least two providers on exact amount
accuracy. Amount parsing already handles digits, Urdu-script digits, Roman Urdu number words and
multipliers, and asks again when the amount is ambiguous.

---

## 10. Registration form (final text)

**Solution Brief (184/200 words)**

Allied Awaaz is an agentic merchant-banking system built on a voice-first counter terminal and a bank-side
operations console.

Pakistan's QR challenge has shifted from registration to reliable, repeated use. At a busy counter, a
silent or delayed confirmation leaves the merchant choosing between trusting a customer's screenshot and
holding up the sale.

At the counter, the merchant speaks or types an amount; the terminal generates a transaction-specific QR
and announces receipt only after bank-side confirmation. When a customer claims to have paid but nothing
was announced, the merchant simply asks. The Payment Exception Agent searches verified transactions by
amount and time, checks status, and answers in Urdu: received, pending at payer bank, or not received.
Unresolved cases are raised to ABL operations with evidence attached.

In the bank, the Merchant Activation Agent monitors QR merchants, detects dormancy or declining usage,
diagnoses likely causes such as offline devices or repeated disputes, and drafts interventions for
relationship managers, who approve every action.

The LLM only calls allowlisted tools; all amounts and statuses come from deterministic backend services,
with signed events, device authentication and full audit logs.

**Innovation / Uniqueness (95/100 words)**

Existing Pakistani soundboxes announce completed payments; AI soundboxes abroad answer collection queries.
Allied Awaaz focuses on what they leave unresolved: the disputed or silent payment at the counter. Its agent
investigates, verifies against bank records and escalates with evidence, turning a trust failure into a
clear answer or an open case. The same transaction signals power a second agent that helps ABL staff
reactivate dormant merchants, with human approval on every action. Safety is architectural: allowlisted
tools, deterministic financial truth, signed confirmations. The result is one agentic loop linking merchant
trust to measurable acquiring volume.

**Go-to-Market & Scaling (81/100 words)**

Phase 1: 90-day pilot with 50 to 100 existing ABL Raast QR merchants in one city, measuring transaction
frequency, monthly volume, dormancy rate and disputes resolved versus a matched control group. Phase 2:
bundle the terminal and agent with ABL business accounts through branches and relationship managers,
offered free or subsidised and offset by current-account balances and retention. Phase 3: scale across
ABL's merchant base, add Punjabi, Pashto and Sindhi, and, with consent, feed verified transaction history
into bank-controlled working-capital prequalification.

Note: one sentence in the Solution Brief says the LLM "only calls allowlisted tools". In the build, the
LLM is an optional intent fallback and the orchestrator calls the tools; if you want exact wording, use
"The agent only calls allowlisted tools".

---

## 11. Definition of done

**Automated (must all pass):** `scripts/verify.sh --strict` shows seven PASS stages; the Docker path
serves the backend and console.

**Manual (owner: team):**

| Item | How to accept |
|------|---------------|
| Firmware on hardware | Section 8 steps 1 to 10 all pass |
| Human voice clips | 130 clips imported; a listener understands every amount in the demo script |
| Urdu STT choice | Benchmark sheet shows the chosen provider's exact-amount accuracy on 50+ real clips |
| Hackathon rules | Deadline, format and demo limits re-checked on Allied Bank's official page |
| Secrets | Every value in `.env` and `config.h` changed from defaults before any shared demo |

---

## 12. Likely judge questions

**Isn't this a Paytm or Easypaisa soundbox?** Those announce completed payments. Ours creates the request,
resolves disputed payments against the ledger, and gives the bank an activation agent with human approval.

**Why is it agentic?** Six explicit stages with allowlisted tools and a verify step before every claim;
the full trace is visible for each decision.

**Can the AI move money or invent numbers?** No tool moves money. Numbers come only from ledger queries and
are spoken through fixed templates. Model-proposed amounts need a keypad confirmation.

**What if someone forges a confirmation?** Events are signed, fresh, idempotent and sequence-checked; the
terminal derives the spoken amount from the signed integer. Our live test injects a forged message and the
terminal rejects it.

**Is the Raast integration real?** No. The gateway is simulated and labelled as such. Production connects
to ABL's acquiring switch through the same verified webhook; the terminal treats the QR payload as opaque,
so the real EMVCo string needs no firmware change.

**What does the bank measure in a pilot?** Transaction frequency, monthly volume, dormancy rate, disputes
resolved, and intervention outcomes against a matched control group.

**Privacy?** The model sees only the utterance; audio is not stored; payer identity is masked.

**Cost?** Prototype about PKR 8,500 to 14,000 in parts; production pricing after component quotes and the
connectivity decision.

---

## 13. Known limitations and pilot path

Simulated gateway and WhatsApp/CRM dispatch; HMAC keys rather than a secure element and asymmetric gateway
signatures; `create_all` instead of migrations; staff tokens instead of bank SSO; espeak placeholder voice;
STT provider not yet chosen. The pilot path for each is in ARCHITECTURE.md sections 6 and 9.
