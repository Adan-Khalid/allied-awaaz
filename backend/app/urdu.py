"""Urdu number handling and deterministic speech rendering.

Design rule: the device speaks by concatenating pre-recorded clips (numbers 1..99,
multipliers, fixed phrases). Every spoken amount is rendered here from a verified
integer, so neither the LLM nor any TTS engine can alter a number the merchant hears.
The same clip IDs are used by the firmware (see firmware/src/speech.cpp).
"""
from __future__ import annotations

import re

# Urdu 1..99 are irregular, so each has its own clip.
_UNITS = [
    "", "aik", "do", "teen", "chaar", "paanch", "chhe", "saat", "aath", "nau", "das",
    "gyarah", "barah", "terah", "chaudah", "pandrah", "solah", "satrah", "atharah", "unees", "bees",
    "ikkees", "baaees", "teyees", "chaubees", "pachchees", "chhabbees", "sattaees", "athaees", "untees", "tees",
    "ikattees", "battees", "taintees", "chauntees", "paintees", "chhattees", "saintees", "artees", "untaalees", "chaalees",
    "iktaalees", "bayaalees", "taintaalees", "chawaalees", "paintaalees", "chhiyaalees", "saintaalees", "artaalees", "unchaas", "pachaas",
    "ikyaawan", "baawan", "tirpan", "chauwan", "pachpan", "chhappan", "sattawan", "athaawan", "unsath", "saath",
    "iksath", "baasath", "tirsath", "chaunsath", "painsath", "chhiyaasath", "sarsath", "arsath", "unhattar", "sattar",
    "ikhattar", "bahattar", "tihattar", "chauhattar", "pachhattar", "chhihattar", "sathattar", "athhattar", "unaasi", "assi",
    "ikyaasi", "bayaasi", "tiraasi", "chauraasi", "pachaasi", "chhiyaasi", "sattaasi", "athaasi", "navaasi", "nabbe",
    "ikyaanave", "baanave", "tiraanave", "chauraanave", "pachaanave", "chhiyaanave", "sattaanave", "athaanave", "ninyaanave",
]
assert len(_UNITS) == 100

_MULTIPLIERS = [(10_000_000, "crore"), (100_000, "lakh"), (1_000, "hazaar"), (100, "sau")]

# Fixed phrase clips. Text is what the clip says; the firmware ships one WAV per key.
PHRASES: dict[str, str] = {
    "rupay": "rupay",
    "receive_ho_gaye": "receive ho gaye",
    "aakhri_payment": "aakhri payment",
    "thi": "thi",
    "aaj": "aaj",
    "payments_mein": "payments mein",
    "receive_hue": "receive hue",
    "aaj_koi_payment_nahi": "aaj abhi tak koi payment receive nahi hui",
    "koi_payment_nahi_hui": "abhi tak koi payment receive nahi hui",
    "ka_qr_tayyar_hai": "ka QR tayyar hai",
    "ki_payment": "ki payment",
    "minute_pehle_receive_ho_chuki": "minute pehle receive ho chuki hai",
    "abhi_pending_hai": "abhi pending hai, customer ke bank se confirm nahi hui.",
    "maal_abhi_na_dein": "maal abhi na dein.",
    "pichle": "pichle",
    "minute_mein": "minute mein",
    "ki_koi_payment_nahi_aayi": "ki koi payment nahi aayi.",
    "abhi_abhi_receive_ho_chuki": "abhi abhi receive ho chuki hai",
    "case_darj": "case darj kar diya gaya hai",
    "payment_fail_hui": "payment fail ho gayi thi, customer dobara payment karein",
    "raqam_samajh_nahi": "raqam samajh nahi aayi, dobara bataein ya keypad se likhein",
    "confirm_karein": "sahi hai to hash dabayein",
    "sirf_payment_madad": "maaf kijiye, main sirf payment aur hisaab mein madad kar sakta hoon",
    "device_online": "device online hai aur bank se connected hai",
    "payment_expire": "payment ka waqt khatam ho gaya",
    "help": "raqam bolein QR ke liye, ya poochein aaj kitni payment aayi",
    "zero": "sifar",
}


def number_clips(n: int) -> list[str]:
    """Integer rupees -> clip IDs, e.g. 1250 -> ['n_12', 'sau', 'n_50']."""
    if n < 0:
        raise ValueError("negative")
    if n == 0:
        return ["zero"]
    clips: list[str] = []
    for value, word in _MULTIPLIERS:
        q, n = divmod(n, value)
        if q:
            if value == 10_000_000 and q >= 100:
                clips += number_clips(q)
            else:
                clips.append(f"n_{q}")
            clips.append(word)
    if n:
        clips.append(f"n_{n}")
    return clips


def clip_text(clip: str) -> str:
    if clip.startswith("n_"):
        return _UNITS[int(clip[2:])]
    if clip in {"crore", "lakh", "hazaar", "sau"}:
        return clip
    return PHRASES[clip]


def all_clip_ids() -> list[str]:
    return [f"n_{i}" for i in range(1, 100)] + ["sau", "hazaar", "lakh", "crore"] + list(PHRASES)


def fmt_pkr(rupees: int) -> str:
    return f"{rupees:,}"


def render(parts: list[str | int]) -> dict:
    """parts: phrase keys or integers. Returns display text and clip plan."""
    clips: list[str] = []
    words: list[str] = []
    display: list[str] = []
    for p in parts:
        if isinstance(p, int):
            nc = number_clips(p)
            clips += nc
            words += [clip_text(c) for c in nc]
            display.append(fmt_pkr(p))
        else:
            clips.append(p)
            words.append(PHRASES[p])
            display.append(PHRASES[p])
    return {"clips": clips, "spoken_text": " ".join(words), "display_text": " ".join(display)}


# ---------------------------------------------------------------- parsing

_WORD_VALUES: dict[str, int] = {w: i for i, w in enumerate(_UNITS) if w}
_VARIANTS = {
    "ek": 1, "ik": 1, "aek": 1, "teen": 3, "char": 4, "panch": 5, "chay": 6, "che": 6, "chhay": 6,
    "sat": 7, "ath": 8, "barah": 12, "bara": 12, "baara": 12, "gyara": 11, "gyaara": 11,
    "tera": 13, "chauda": 14, "pandra": 15, "sola": 16, "satra": 17, "athara": 18, "athaara": 18,
    "pachees": 25, "pachis": 25, "tis": 30, "chalis": 40, "pachas": 50, "saath": 60,
    "satar": 70, "assi": 80, "nabe": 90, "nabbay": 90,
    # Urdu script: 1-10 and round numbers most likely in prices.
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7, "آٹھ": 8, "نو": 9, "دس": 10,
    "بارہ": 12, "پندرہ": 15, "بیس": 20, "پچیس": 25, "تیس": 30, "چالیس": 40, "پچاس": 50,
    "ساٹھ": 60, "ستر": 70, "اسی": 80, "نوے": 90,
}
_WORD_VALUES.update(_VARIANTS)
_MULT_WORDS = {
    "sau": 100, "so": 100, "saw": 100, "sao": 100, "سو": 100,
    "hazaar": 1000, "hazar": 1000, "hajar": 1000, "hazzar": 1000, "ہزار": 1000, "thousand": 1000,
    "lakh": 100_000, "lac": 100_000, "لاکھ": 100_000,
    "crore": 10_000_000, "karor": 10_000_000, "کروڑ": 10_000_000,
    "hundred": 100,
}
_ENGLISH = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# Words that are numbers only when they follow a number ("barah so" = 1200, but "so" alone is English).
_AMBIGUOUS_MULT = {"so", "saw", "sao"}
# "bana do", "kar do": the imperative "do" is not the number 2.
_IMPERATIVE_DO = re.compile(r"\b(bana|banao|kar|karo|de|dikha|bata|bhej|laga|generate|nikal)\s+do\b")

_URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TOKEN = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?|[^\s0-9.,?!]+")


def normalise(text: str) -> str:
    return text.translate(_URDU_DIGITS).lower().replace("rs.", " ").replace("pkr", " ")


def parse_amount(text: str) -> tuple[int | None, float]:
    """Extract a rupee amount. Returns (amount, confidence).

    Digit amounts are high confidence. Word amounts are medium. Multiple distinct
    candidate amounts return None so the agent asks instead of guessing."""
    t = _IMPERATIVE_DO.sub(r"\1", normalise(text))
    digit_hits = [m.group() for m in _TOKEN.finditer(t) if m.group()[0].isdigit()]
    if digit_hits:
        values = {int(float(h.replace(",", ""))) for h in digit_hits}
        # "5000 ka QR" -> one value. "1730 ... 15 minute" handled by the caller stripping time phrases.
        if len(values) == 1:
            return values.pop(), 0.95
        return None, 0.0

    total, current, seen = 0, 0, False
    for m in _TOKEN.finditer(t):
        w = m.group()
        if w in _WORD_VALUES or w in _ENGLISH:
            current += _WORD_VALUES.get(w, _ENGLISH.get(w, 0))
            seen = True
        elif w in _MULT_WORDS:
            if w in _AMBIGUOUS_MULT and current == 0:
                continue
            mult = _MULT_WORDS[w]
            if mult == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * mult
                current = 0
            seen = True
    if not seen:
        return None, 0.0
    value = total + current
    return (value, 0.8) if value > 0 else (None, 0.0)
