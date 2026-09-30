# Contributing to Allied Awaaz

Thanks for your interest. Issues and pull requests are welcome.

## Getting started

1. Fork the repo and create a branch from `main`.
2. Set up the tools listed in [docs/VERIFICATION.md](docs/VERIFICATION.md#2-environment-setup) (Python 3.11+, Node.js 20+,
   g++, Mosquitto, PlatformIO, Playwright Chromium, PostgreSQL 16).
3. Run the full acceptance suite before opening a pull request:

   ```bash
   scripts/verify.sh --strict
   ```

   CI runs the same script plus a Docker Compose smoke test on every push and pull request.

## Ground rules

* **Do not weaken tests to make them pass.** `backend/tests/**`, `firmware/test/**`,
  `scripts/e2e_live.py`, `scripts/e2e_console.py` and `scripts/verify.sh` are the acceptance
  contract. Fix the product code instead.
* **Keep the security invariants.** They are listed in [docs/VERIFICATION.md](docs/VERIFICATION.md#5-security-invariants-must-hold-after-any-change)
  and explained in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). A change that passes tests but breaks
  one will not be merged.
* **Never commit secrets.** `.env`, `firmware/include/config.h` and `infra/mosquitto/passwd` are
  git-ignored for a reason.
* The payment gateway is **simulated**. Do not describe it as a real Raast or Allied Bank integration.

## Pull requests

* One focused change per pull request, with a short description of what and why.
* Add or update tests for behaviour changes.
* Make sure `scripts/verify.sh --strict` prints `RESULT: PASS (all stages)`.
