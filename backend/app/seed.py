"""Deterministic demo data: Ahmed Pharmacy (the live-demo merchant) plus a synthetic
merchant base with realistic activity patterns for the activation console.

All data is synthetic. Names are fictional."""
from __future__ import annotations

import os
import random
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import Device, ExceptionCase, Merchant, PaymentRequest

DEMO_DEVICE_ID = "awz-demo-001"

TICKETS = {  # (min, max) rupees per category
    "pharmacy": (150, 4500), "kiryana": (80, 3000), "bakery": (120, 2500), "restaurant": (400, 6000),
    "barber": (300, 1500), "mobile_shop": (500, 15000), "garments": (800, 9000), "workshop": (500, 8000),
}

# (name, category, city, pattern, rm)
BASE = [
    ("Madina General Store", "kiryana", "Rawalpindi", "healthy", "Sana Qureshi"),
    ("Al-Rehman Bakers", "bakery", "Islamabad", "healthy", "Sana Qureshi"),
    ("Shaheen Mobile Zone", "mobile_shop", "Rawalpindi", "declining", "Sana Qureshi"),
    ("Karachi Biryani House", "restaurant", "Islamabad", "healthy", "Bilal Ahmed"),
    ("Fresh Cuts Salon", "barber", "Islamabad", "dormant", "Bilal Ahmed"),
    ("Noor Garments", "garments", "Rawalpindi", "healthy", "Bilal Ahmed"),
    ("City Care Pharmacy", "pharmacy", "Islamabad", "offline", "Sana Qureshi"),
    ("Bismillah Kiryana", "kiryana", "Rawalpindi", "exceptions", "Sana Qureshi"),
    ("Hamza Auto Workshop", "workshop", "Rawalpindi", "never", "Bilal Ahmed"),
    ("Chaudhry Sweets", "bakery", "Rawalpindi", "declining", "Bilal Ahmed"),
    ("Blue Area Cafe", "restaurant", "Islamabad", "healthy", "Sana Qureshi"),
    ("Life Line Medicos", "pharmacy", "Rawalpindi", "healthy", "Bilal Ahmed"),
    ("Tariq Cloth House", "garments", "Islamabad", "dormant", "Sana Qureshi"),
    ("Smart Phone Point", "mobile_shop", "Islamabad", "healthy", "Bilal Ahmed"),
    ("Pak Hotel & Tikka", "restaurant", "Rawalpindi", "declining", "Sana Qureshi"),
    ("Iqbal Super Mart", "kiryana", "Islamabad", "healthy", "Bilal Ahmed"),
    ("Royal Hair Studio", "barber", "Rawalpindi", "healthy", "Sana Qureshi"),
    ("Ittefaq Motors Service", "workshop", "Islamabad", "offline", "Bilal Ahmed"),
    ("Gulshan Bakery", "bakery", "Islamabad", "healthy", "Sana Qureshi"),
    ("New Friends Kiryana", "kiryana", "Rawalpindi", "never", "Bilal Ahmed"),
    ("Sehat Pharmacy", "pharmacy", "Islamabad", "declining", "Bilal Ahmed"),
    ("Faisal Fabrics", "garments", "Rawalpindi", "healthy", "Sana Qureshi"),
    ("Metro Mobiles", "mobile_shop", "Rawalpindi", "dormant", "Bilal Ahmed"),
    ("Desi Dhaba", "restaurant", "Islamabad", "healthy", "Sana Qureshi"),
]


def _payments(db: Session, rng: random.Random, m: Merchant, device_id: str | None, days: int,
              per_day: tuple[int, int], category: str, stop_days_ago: int = 0,
              decline_last_week: bool = False, today_count: int | None = None) -> None:
    now = utcnow()
    from .payments import pkt_day_start_utc
    minutes_today = int((now - pkt_day_start_utc(now)).total_seconds() // 60)
    lo, hi = TICKETS[category]
    for day in range(days, stop_days_ago - 1, -1):
        n = rng.randint(*per_day)
        if decline_last_week and day < 7:
            n = max(0, n // 4)
        if day == 0 and today_count is not None:
            n = today_count
        for _ in range(n):
            if day == 0:
                # today: inside the elapsed part of the Pakistan-time day, never in the future
                if minutes_today < 3:
                    continue
                t = now - timedelta(minutes=rng.randint(1, min(300, minutes_today - 1)))
            else:
                t = now - timedelta(days=day, hours=rng.randint(0, 10), minutes=rng.randint(0, 59))
            amount = rng.randint(lo, hi)
            amount -= amount % 10
            db.add(PaymentRequest(merchant_id=m.id, device_id=device_id, amount_minor=amount * 100,
                                  reference=f"AWZ{secrets.token_hex(4).upper()}", status="SUCCEEDED",
                                  created_at=t, settled_at=t, expires_at=t + timedelta(minutes=5),
                                  payer_bank=rng.choice(["HBL", "Meezan Bank", "UBL", "easypaisa", "JazzCash"]),
                                  announced=True))


def seed(db: Session) -> bool:
    if db.scalar(select(func.count()).select_from(Merchant)):
        return False
    rng = random.Random(42)
    now = utcnow()

    demo = Merchant(name="Ahmed Pharmacy", category="pharmacy", city="Islamabad", phone_masked="0300-xxx-4417",
                    rm_name="Sana Qureshi", onboarded_at=now - timedelta(days=60))
    db.add(demo)
    db.flush()
    db.add(Device(id=DEMO_DEVICE_ID, merchant_id=demo.id,
                  secret=os.getenv("AWAAZ_DEMO_DEVICE_SECRET", "dev-device-secret-001"),
                  online=False, last_seen_at=now))
    db.flush()  # devices must exist before payments reference them (FK enforced on Postgres)
    _payments(db, rng, demo, DEMO_DEVICE_ID, 45, (9, 16), "pharmacy", today_count=13)

    for idx, (name, cat, city, pattern, rm) in enumerate(BASE, start=1):
        onboarded = now - timedelta(days=30 if pattern == "never" else rng.randint(50, 120))
        m = Merchant(name=name, category=cat, city=city, phone_masked=f"03{rng.randint(0, 4)}x-xxx-{rng.randint(1000, 9999)}",
                     rm_name=rm, onboarded_at=onboarded)
        db.add(m)
        db.flush()
        dev_id = f"awz-{idx:04d}"
        online, last_seen = True, now - timedelta(minutes=rng.randint(1, 30))
        if pattern == "offline":
            online, last_seen = False, now - timedelta(hours=rng.randint(40, 80))
        if pattern == "never":
            online, last_seen = False, None
        db.add(Device(id=dev_id, merchant_id=m.id, secret=secrets.token_hex(32), online=online, last_seen_at=last_seen))
        db.flush()

        if pattern == "healthy":
            _payments(db, rng, m, dev_id, 40, (6, 18), cat)
        elif pattern == "declining":
            _payments(db, rng, m, dev_id, 40, (8, 16), cat, decline_last_week=True)
        elif pattern == "dormant":
            _payments(db, rng, m, dev_id, 40, (4, 10), cat, stop_days_ago=rng.randint(9, 20))
        elif pattern == "offline":
            _payments(db, rng, m, dev_id, 40, (6, 14), cat, stop_days_ago=3)
        elif pattern == "exceptions":
            _payments(db, rng, m, dev_id, 40, (5, 12), cat)
            for k in range(4):
                db.add(ExceptionCase(merchant_id=m.id, type="CLAIM_NOT_FOUND", claimed_amount_minor=rng.randint(5, 30) * 10000,
                                     evidence={"matches": [], "window_min": 15, "seeded": True},
                                     opened_at=now - timedelta(days=rng.randint(1, 12))))
    db.commit()
    return True
