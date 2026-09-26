"""Deterministic intent understanding (primary path).

Rules run first because they are fast, auditable and never hallucinate. The LLM
fallback (llm.py) is only consulted when rules return UNKNOWN, and even then it
can only choose from this closed enum."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from ..urdu import normalise, parse_amount


class Intent(str, Enum):
    CREATE_PAYMENT = "CREATE_PAYMENT"
    CHECK_CLAIM = "CHECK_CLAIM"          # "customer says he paid 1730, did it arrive?"
    LAST_PAYMENT = "LAST_PAYMENT"
    TODAY_SUMMARY = "TODAY_SUMMARY"
    DEVICE_STATUS = "DEVICE_STATUS"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


@dataclass
class Understanding:
    intent: Intent
    amount: int | None = None
    confidence: float = 0.0
    source: str = "rules"
    notes: list[str] = field(default_factory=list)


def _has(t: str, patterns: list[str]) -> bool:
    return any(re.search(p, t) for p in patterns)


# Money-out or credit requests are out of scope for the terminal agent by design.
_OUTBOUND = [r"transfer\s*karo", r"bhejo", r"bhej\s*do", r"withdraw", r"nikalo", r"nikaal", r"\bloan\b",
             r"qarz", r"refund\s*karo", r"ignore", r"instruction", r"mark\s.*paid", r"system\s*prompt"]
_CLAIM = [
    r"keh\s*raha", r"kehta", r"keh\s*rahi", r"bol\s*raha", r"bhej\s*(di|diye|diya|dia|de)", r"bheji", r"bheja",
    r"(aay[ei]|aaya|aa[iy]i|aaye)\s*nahi", r"nahi\s*(aay[ei]|aaya|aai|aaye|aya)", r"screenshot", r"transfer\s*kar",
    r"send\s*kar", r"paid", r"\b(aaye|aayi|aaya|aai|aa\s*gaye|aa\s*gayi|mil\s*gaye|mile)\s*\?", r"check\s*kar", r"confirm\s*kar", r"(aa|aay)\s*(gay[ei]|gaya|gai)\s*\?", r"mil[ea]?\s*\?",
    r"کہہ\s*رہا", r"بھیج", r"نہیں\s*آئ",
]
_LAST = [r"\blast\b", r"aakhri", r"akhri", r"pichl[ie]\s*payment", r"آخری"]
_SUMMARY = [r"\baaj\b", r"hisaab", r"hisab", r"\btotal\b", r"kitn[ia]\s*(payment|paise|paisa|receive|sale)",
            r"\bsales?\b", r"آج", r"حساب"]
_DEVICE = [r"device", r"internet", r"connect", r"online", r"signal"]
_HELP = [r"\bhelp\b", r"madad", r"kya\s*kar\s*sakt"]
_CREATE = [r"\bqr\b", r"payment\s*bana", r"\bbana\b", r"banao", r"ka\s*payment", r"ki\s*payment", r"charge", r"le\s*lo"]
# Strip "15 minute pehle" style time phrases so they are not read as the amount.
_TIME_PHRASE = re.compile(r"\b\d+\s*(minute|min|mint|second|sec|ghant[ae])\w*\b")


def understand(text: str) -> Understanding:
    t = normalise(text).strip()
    if not t:
        return Understanding(Intent.UNKNOWN, notes=["empty input"])
    amount, conf = parse_amount(_TIME_PHRASE.sub(" ", t))

    if _has(t, _OUTBOUND):
        return Understanding(Intent.UNKNOWN, amount, 0.0, notes=["outbound or out-of-scope request refused"])

    if _has(t, _CLAIM) and not _has(t, [r"\bqr\b", r"bana"]):
        return Understanding(Intent.CHECK_CLAIM, amount, conf if amount else 0.5,
                             notes=[] if amount else ["claim without amount"])
    if amount is None and _has(t, _LAST):
        return Understanding(Intent.LAST_PAYMENT, confidence=0.9)
    if amount is None and _has(t, _SUMMARY):
        return Understanding(Intent.TODAY_SUMMARY, confidence=0.9)
    if amount is not None and (_has(t, _CREATE) or len(t.split()) <= 4):
        return Understanding(Intent.CREATE_PAYMENT, amount, conf)
    if _has(t, _DEVICE):
        return Understanding(Intent.DEVICE_STATUS, confidence=0.85)
    if _has(t, _HELP):
        return Understanding(Intent.HELP, confidence=0.85)
    if _has(t, _CREATE):
        return Understanding(Intent.CREATE_PAYMENT, None, 0.4, notes=["create without clear amount"])
    return Understanding(Intent.UNKNOWN, amount, 0.0)
