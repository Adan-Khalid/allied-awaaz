#!/usr/bin/env python3
"""Regenerate firmware/test/golden/* from the backend's reference implementation.
The firmware host test (firmware/test/native/test_core.cpp) must pass against these files."""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("AWAAZ_DATABASE_URL", "sqlite://")
from app.security import device_canonical, mqtt_canonical, sha256_hex  # noqa: E402
from app.urdu import number_clips  # noqa: E402

out = ROOT / "firmware" / "test" / "golden"
out.mkdir(parents=True, exist_ok=True)
rng = random.Random(7)
nums = sorted(set(list(range(0, 2101)) + [9999, 10000, 99999, 100000, 100001, 150000, 250000, 999999, 1000000,
                                            9999999, 10000000, 12345678, 99999999, 100000000, 999999999, 4294967295]
                  + [rng.randint(0, 50_000_000) for _ in range(3000)]))
with open(out / "clips.txt", "w") as f:
    for n in nums:
        f.write(f"{n}|{' '.join(number_clips(n))}\n")

with open(out / "canonical.txt", "w") as f:
    for i in range(50):
        v, t, seq, ts = 1, "payment.status", rng.randint(1, 2**40), 1_790_000_000 + rng.randint(0, 10**6)
        txn, amt = f"txn_{rng.getrandbits(64):016x}", rng.randint(100, 50_000_000)
        st = rng.choice(["PENDING", "SUCCEEDED", "FAILED"])
        f.write("M\t" + "\t".join(map(str, [v, t, seq, ts, txn, amt, st])) + "\t" + mqtt_canonical(v, t, seq, ts, txn, amt, st).replace("\n", "\\n") + "\n")
    for i in range(20):
        body = os.urandom(rng.randint(0, 64))
        path = rng.choice(["/v1/device/query", "/v1/device/payments", "/v1/device/config"])
        method, ts, nonce = rng.choice(["GET", "POST"]), str(1_790_000_000 + i), f"{rng.getrandbits(96):024x}"
        f.write("R\t" + "\t".join([method, path, ts, nonce, sha256_hex(body)]) + "\t"
                + device_canonical(method, path, ts, nonce, body).replace("\n", "\\n") + "\n")
print(f"wrote {len(nums)} clip cases and 70 canonical cases to {out}")
