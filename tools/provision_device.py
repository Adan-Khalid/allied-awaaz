#!/usr/bin/env python3
"""Register a terminal for a merchant and print the values to flash into firmware/include/config.h.

    AWAAZ_DATABASE_URL=postgresql+psycopg://awaaz:awaaz@localhost:5432/awaaz \
      python tools/provision_device.py --merchant "Ahmed Pharmacy" --device awz-0100
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Device, Merchant, audit  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--merchant", required=True)
ap.add_argument("--device", required=True)
a = ap.parse_args()

with SessionLocal() as db:
    m = db.scalar(select(Merchant).where(Merchant.name == a.merchant))
    if m is None:
        sys.exit(f"merchant not found: {a.merchant}")
    if db.get(Device, a.device):
        sys.exit(f"device exists: {a.device}")
    secret = secrets.token_hex(32)
    mqtt_pw = secrets.token_urlsafe(18)
    db.add(Device(id=a.device, merchant_id=m.id, secret=secret))
    audit(db, "provisioning", "device.provisioned", a.device, merchant_id=m.id)
    db.commit()

print(f'#define DEVICE_ID       "{a.device}"')
print(f'#define DEVICE_SECRET   "{secret}"')
print(f'#define MQTT_PASSWORD   "{mqtt_pw}"')
print(f"\nAdd to broker: mosquitto_passwd -b infra/mosquitto/passwd {a.device} '{mqtt_pw}'")
