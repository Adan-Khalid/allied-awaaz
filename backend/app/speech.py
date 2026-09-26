"""Speech-to-text adapter.

The terminal records push-to-talk audio (16 kHz, 16-bit mono WAV) and uploads it.
Only the transcript moves forward; audio is not stored.

Provider is pluggable because Urdu STT quality must be benchmarked on real shop
recordings before a final choice (see docs/ARCHITECTURE.md, open decisions).
Text-to-speech is not needed: every reply is a clip plan (see urdu.py)."""
from __future__ import annotations

import httpx

from .config import settings


class SttUnavailable(Exception):
    pass


def transcribe(wav: bytes) -> str:
    if settings.stt_provider == "none":
        raise SttUnavailable("speech disabled; use keypad or /query")
    if settings.stt_provider != "openai_compatible":
        raise SttUnavailable(f"unknown provider {settings.stt_provider}")
    if len(wav) > 2_000_000:  # ~60 s at 16 kHz mono; push-to-talk clips are a few seconds
        raise SttUnavailable("audio too long")
    try:
        r = httpx.post(
            f"{settings.stt_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.stt_api_key}"},
            files={"file": ("utterance.wav", wav, "audio/wav")},
            data={"model": settings.stt_model, "language": settings.stt_language,
                  # Biases the decoder toward shop vocabulary and digits for amounts.
                  "prompt": "Dukaan, payment, QR, rupay, 1250, hazaar, sau, aaj ka hisaab, aakhri payment."},
            timeout=8.0,
        )
        r.raise_for_status()
        return (r.json().get("text") or "").strip()
    except httpx.HTTPError as exc:
        raise SttUnavailable(str(exc)) from exc
