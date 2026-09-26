#!/usr/bin/env bash
# Allied Awaaz: one-command verification.
#
#   scripts/verify.sh            run everything available, SKIP what the machine cannot run
#   scripts/verify.sh --strict   any SKIP counts as a failure (use this for final acceptance)
#
# Stages
#   backend-unit       pytest on in-memory SQLite (50 tests)
#   backend-postgres   same suite on Postgres        (needs AWAAZ_TEST_DATABASE_URL)
#   firmware-core      C++ protocol core vs backend golden files (needs g++)
#   firmware-build     PlatformIO build for ESP32-S3 (needs pio)
#   console-build      npm ci, typecheck, production build (needs node 20+)
#   live-e2e           backend + Mosquitto + virtual terminal, 16 checks (needs mosquitto)
#   console-e2e        real browser against the console, 12 checks (needs python playwright + chromium)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STRICT=0; [[ "${1:-}" == "--strict" ]] && STRICT=1
WORK="$(mktemp -d)"
PY="${PYTHON:-python3}"
# Pick free ports so a developer's running stack never collides with verification.
free_port() { "$PY" -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'; }
API_PORT="${AWAAZ_VERIFY_API_PORT:-$(free_port)}"
UI_PORT="${AWAAZ_VERIFY_UI_PORT:-$(free_port)}"
MQ_PORT="${AWAAZ_VERIFY_MQTT_PORT:-$(free_port)}"
BPW="verify-backend-$RANDOM"; DPW="verify-device-$RANDOM"
declare -a NAMES STATUS NOTES
PIDS=()

cleanup() { for p in "${PIDS[@]:-}"; do [[ -n "$p" ]] && kill "$p" 2>/dev/null; done; wait 2>/dev/null; if [[ -n "${VERIFY_KEEP:-}" ]]; then echo "logs kept in $WORK"; else rm -rf "$WORK"; fi; }
trap cleanup EXIT

record() { NAMES+=("$1"); STATUS+=("$2"); NOTES+=("${3:-}"); printf '%-18s %s %s\n' "$1" "$2" "${3:-}"; }
have() { command -v "$1" >/dev/null 2>&1; }
wait_http() { for _ in $(seq 1 "${2:-60}"); do curl -fs -o /dev/null "$1" && return 0; sleep 1; done; return 1; }

start_backend() {  # $1 = db url, $2 = mqtt enabled (true/false)
  (cd "$ROOT/backend" && \
    AWAAZ_DATABASE_URL="$1" AWAAZ_MQTT_ENABLED="$2" AWAAZ_MQTT_HOST=127.0.0.1 AWAAZ_MQTT_PORT="$MQ_PORT" \
    AWAAZ_MQTT_PASSWORD="$BPW" AWAAZ_SIM_SLOW_DELAY_S=3 AWAAZ_PUBLIC_BASE_URL="http://localhost:$API_PORT" \
    AWAAZ_CORS_ORIGINS="http://localhost:$UI_PORT" \
    exec "$PY" -m uvicorn app.main:app --port "$API_PORT" >"$WORK/backend.log" 2>&1) &
  BACKEND_PID=$!; PIDS+=("$BACKEND_PID")
  wait_http "http://localhost:$API_PORT/healthz" 90
}
stop_backend() { kill "$BACKEND_PID" 2>/dev/null; wait "$BACKEND_PID" 2>/dev/null; }

echo "== Allied Awaaz verification ($(date -u +%FT%TZ)) =="

# ------------------------------------------------------------------ backend
if (cd "$ROOT/backend" && env -u AWAAZ_TEST_DATABASE_URL "$PY" -m pytest -q >"$WORK/unit.log" 2>&1); then
  record backend-unit PASS "$(tail -1 "$WORK/unit.log")"
else
  record backend-unit FAIL "see output below"; tail -30 "$WORK/unit.log"
fi

if [[ -n "${AWAAZ_TEST_DATABASE_URL:-}" ]]; then
  if (cd "$ROOT/backend" && "$PY" -m pytest -q >"$WORK/pg.log" 2>&1); then
    record backend-postgres PASS "$(tail -1 "$WORK/pg.log")"
  else
    record backend-postgres FAIL; tail -30 "$WORK/pg.log"
  fi
else
  record backend-postgres SKIP "set AWAAZ_TEST_DATABASE_URL=postgresql+psycopg://user:pw@host/db"
fi

# ------------------------------------------------------------------ firmware
if have g++; then
  if g++ -std=c++17 -Wall -Wextra -Werror -I"$ROOT/firmware/lib/awaaz_core" "$ROOT/firmware/test/native/test_core.cpp" \
       -o "$WORK/core_test" && "$WORK/core_test" "$ROOT/firmware/test/golden" >"$WORK/core.log" 2>&1; then
    record firmware-core PASS "$(cat "$WORK/core.log")"
  else
    record firmware-core FAIL; cat "$WORK/core.log" 2>/dev/null
  fi
else
  record firmware-core SKIP "install g++"
fi

if have pio; then
  created=0
  [[ -f "$ROOT/firmware/include/config.h" ]] || { cp "$ROOT/firmware/include/config.h.example" "$ROOT/firmware/include/config.h"; created=1; }
  if (cd "$ROOT/firmware" && pio run >"$WORK/pio.log" 2>&1); then
    record firmware-build PASS "$(grep -E '^(RAM|Flash):' "$WORK/pio.log" | tr -s ' ' | paste -sd ';' -)"
  else
    record firmware-build FAIL; tail -40 "$WORK/pio.log"
  fi
  [[ $created == 1 ]] && rm -f "$ROOT/firmware/include/config.h"
else
  record firmware-build SKIP "pip install platformio"
fi

# ------------------------------------------------------------------ console build
CONSOLE_OK=0
if have npm; then
  if (cd "$ROOT/console" && { [[ -d node_modules ]] || npm ci --no-audit --no-fund; } >"$WORK/npm.log" 2>&1 \
      && npm run -s typecheck >>"$WORK/npm.log" 2>&1 \
      && NEXT_PUBLIC_API_BASE="http://localhost:$API_PORT" NEXT_TELEMETRY_DISABLED=1 npm run -s build >>"$WORK/npm.log" 2>&1); then
    record console-build PASS "typecheck + production build"; CONSOLE_OK=1
  else
    record console-build FAIL; tail -40 "$WORK/npm.log"
  fi
else
  record console-build SKIP "install Node.js 20+"
fi

# ------------------------------------------------------------------ live end-to-end
if [[ -n "${VERIFY_ONLY_UI:-}" ]]; then record live-e2e SKIP "VERIFY_ONLY_UI set"; elif have mosquitto && have mosquitto_passwd; then
  "$ROOT/scripts/local_broker.sh" "$WORK/mq" "$MQ_PORT" "$BPW" "$DPW" >"$WORK/mq.log" 2>&1 &
  PIDS+=($!); sleep 1
  if start_backend "sqlite:///$WORK/live.db" true; then
    if AWAAZ_API="http://localhost:$API_PORT" AWAAZ_MQTT_HOST=127.0.0.1 AWAAZ_MQTT_PORT="$MQ_PORT" \
       AWAAZ_DEVICE_MQTT_PASSWORD="$DPW" AWAAZ_BACKEND_MQTT_PASSWORD="$BPW" \
       "$PY" "$ROOT/scripts/e2e_live.py" >"$WORK/live.log" 2>&1; then
      record live-e2e PASS "$(tail -1 "$WORK/live.log")"
    else
      record live-e2e FAIL; cat "$WORK/live.log"; tail -20 "$WORK/backend.log"
    fi
  else
    record live-e2e FAIL "backend did not start"; tail -30 "$WORK/backend.log"
  fi
  stop_backend
else
  record live-e2e SKIP "install mosquitto (apt install mosquitto / brew install mosquitto)"
fi

# ------------------------------------------------------------------ console end-to-end
if [[ $CONSOLE_OK == 1 ]] && "$PY" -c "import playwright" 2>/dev/null; then
  if start_backend "sqlite:///$WORK/console.db" false; then
    (cd "$ROOT/console" && NEXT_TELEMETRY_DISABLED=1 exec npx next start -p "$UI_PORT" >"$WORK/next.log" 2>&1) &
    PIDS+=($!)
    if wait_http "http://localhost:$UI_PORT/login" 60 && \
       AWAAZ_CONSOLE="http://localhost:$UI_PORT" AWAAZ_API="http://localhost:$API_PORT" \
       "$PY" "$ROOT/scripts/e2e_console.py" >"$WORK/ui.log" 2>&1; then
      record console-e2e PASS "$(tail -1 "$WORK/ui.log")"
    else
      record console-e2e FAIL; cat "$WORK/ui.log"
    fi
  else
    record console-e2e FAIL "backend did not start"
  fi
  stop_backend
else
  record console-e2e SKIP "needs console-build PASS and: pip install playwright && playwright install chromium"
fi

# ------------------------------------------------------------------ summary
echo; echo "== Summary =="
fail=0; skip=0
for i in "${!NAMES[@]}"; do
  printf '  %-18s %s\n' "${NAMES[$i]}" "${STATUS[$i]}"
  [[ "${STATUS[$i]}" == FAIL ]] && fail=1
  [[ "${STATUS[$i]}" == SKIP ]] && skip=1
done
if [[ $fail == 1 ]]; then echo "RESULT: FAIL"; exit 1; fi
if [[ $skip == 1 && $STRICT == 1 ]]; then echo "RESULT: FAIL (strict mode: stages were skipped)"; exit 1; fi
[[ $skip == 1 ]] && echo "RESULT: PASS with skipped stages (run with --strict for full acceptance)" || echo "RESULT: PASS (all stages)"
exit 0
