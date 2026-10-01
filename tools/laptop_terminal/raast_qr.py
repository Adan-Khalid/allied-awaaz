"""Raast QR with a preset amount, built from the merchant's own bank-issued Raast QR.

Why start from the bank's QR: the official SBP Raast QR profile is not public, and a wrong
account template sends money to the wrong place or is rejected by banking apps. So the account
part (Merchant Account Information, EMVCo tags 26-51) is copied byte for byte from the QR that
the merchant's bank generated. This module only:
  * sets Point of Initiation to dynamic ("12"),
  * sets the transaction amount (tag 54),
  * recomputes the CRC (tag 63, CRC-16/CCITT-FALSE as EMVCo MPM requires).

Allied Awaaz cannot see payments made to these QRs (there is no bank notification), so the
terminal never announces them as received. The merchant checks their own bank app.
"""
from __future__ import annotations

import re

_TLV = re.compile(r"^(\d{2})(\d{2})")


class RaastQrError(ValueError):
    pass


def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def parse(payload: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(payload):
        m = _TLV.match(payload[i:])
        if not m:
            raise RaastQrError("not an EMVCo QR payload")
        tag, length = m.group(1), int(m.group(2))
        value = payload[i + 4:i + 4 + length]
        if len(value) != length:
            raise RaastQrError("truncated QR payload")
        out.append((tag, value))
        i += 4 + length
    return out


def build(fields: list[tuple[str, str]]) -> str:
    body = "".join(f"{t}{len(v):02d}{v}" for t, v in fields if t != "63")
    body += "6304"
    return body + crc16_ccitt(body)


def validate(payload: str) -> dict:
    """Checks a bank-issued payload and returns safe-to-display details (account masked)."""
    payload = payload.strip()
    fields = parse(payload)
    tags = dict(fields)
    if fields[0] != ("00", "01"):
        raise RaastQrError("missing EMVCo payload format indicator")
    if "63" not in tags or crc16_ccitt(payload[:-4]) != payload[-4:].upper():
        raise RaastQrError("checksum does not match; scan the QR again")
    if tags.get("58") != "PK":
        raise RaastQrError("not a Pakistani QR (country code is not PK)")
    if tags.get("53", "586") != "586":
        raise RaastQrError("currency is not PKR")
    accounts = [(t, v) for t, v in fields if "26" <= t <= "51"]
    raast = [(t, v) for t, v in accounts if "raast" in v.lower()]
    if not raast:
        raise RaastQrError("no Raast account in this QR; use the Raast QR from your bank app")
    sub = parse(raast[0][1])
    account = next((v for t, v in sub if t != "00"), "")
    return {"merchant": tags.get("59", ""), "city": tags.get("60", ""),
            "account_hint": ("•••• " + account[-4:]) if account else "",
            "has_amount": "54" in tags}


def with_amount(payload: str, rupees: int) -> str:
    """The bank's QR with Point of Initiation = dynamic and the amount set; CRC recomputed."""
    if not 1 <= rupees <= 9_999_999_999:
        raise RaastQrError("amount out of range")
    fields = [(t, v) for t, v in parse(payload.strip()) if t not in ("54", "63")]
    fields = [(t, "12") if t == "01" else (t, v) for t, v in fields]
    if not any(t == "01" for t, _ in fields):
        fields.insert(1, ("01", "12"))
    # EMVCo orders tags ascending; insert 54 after 53 (or before 58 when 53 is absent).
    idx = next((i for i, (t, _) in enumerate(fields) if t > "54"), len(fields))
    fields.insert(idx, ("54", str(rupees)))
    return build(fields)
