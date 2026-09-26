"""Runtime configuration. Every value comes from the environment so the same
image runs in dev, demo and a bank-hosted pilot without code changes."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in {"1", "true", "yes", "on"}


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env(
        "AWAAZ_DATABASE_URL", "postgresql+psycopg://awaaz:awaaz@localhost:5432/awaaz"))
    public_base_url: str = field(default_factory=lambda: _env("AWAAZ_PUBLIC_BASE_URL", "http://localhost:8000"))

    # Simulated gateway signing key. In production this is replaced by the acquiring
    # bank's event-signing key (asymmetric; the backend holds only the public key).
    gateway_signing_key: str = field(default_factory=lambda: _env(
        "AWAAZ_GATEWAY_SIGNING_KEY", "dev-gateway-key-change-me"))

    max_clock_skew_s: int = field(default_factory=lambda: int(_env("AWAAZ_MAX_SKEW_S", "300")))

    # Business limits enforced in tool schemas, never by the model.
    max_payment_rupees: int = field(default_factory=lambda: int(_env("AWAAZ_MAX_PAYMENT_RUPEES", "500000")))
    payment_ttl_s: int = field(default_factory=lambda: int(_env("AWAAZ_PAYMENT_TTL_S", "300")))
    claim_window_min: int = field(default_factory=lambda: int(_env("AWAAZ_CLAIM_WINDOW_MIN", "15")))
    device_rate_per_min: int = field(default_factory=lambda: int(_env("AWAAZ_DEVICE_RATE_PER_MIN", "30")))

    sim_slow_delay_s: float = field(default_factory=lambda: float(_env("AWAAZ_SIM_SLOW_DELAY_S", "20")))

    mqtt_enabled: bool = field(default_factory=lambda: _bool("AWAAZ_MQTT_ENABLED", True))
    mqtt_host: str = field(default_factory=lambda: _env("AWAAZ_MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(_env("AWAAZ_MQTT_PORT", "1883")))
    mqtt_username: str = field(default_factory=lambda: _env("AWAAZ_MQTT_USERNAME", "awaaz-backend"))
    mqtt_password: str = field(default_factory=lambda: _env("AWAAZ_MQTT_PASSWORD", ""))

    # Optional LLM fallback for intent understanding only. Never used for numbers or status.
    llm_enabled: bool = field(default_factory=lambda: _bool("AWAAZ_LLM_ENABLED", False))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: _env("AWAAZ_LLM_MODEL", "claude-haiku-4-5-20251001"))

    # Speech-to-text: "none" (text/keypad only) or "openai_compatible" (Whisper-style endpoint).
    stt_provider: str = field(default_factory=lambda: _env("AWAAZ_STT_PROVIDER", "none"))
    stt_base_url: str = field(default_factory=lambda: _env("AWAAZ_STT_BASE_URL", "https://api.openai.com/v1"))
    stt_api_key: str = field(default_factory=lambda: _env("AWAAZ_STT_API_KEY", ""))
    stt_model: str = field(default_factory=lambda: _env("AWAAZ_STT_MODEL", "whisper-1"))
    stt_language: str = field(default_factory=lambda: _env("AWAAZ_STT_LANGUAGE", "ur"))

    # Bank console staff tokens: "token:role:Display Name,token:role:Display Name"
    staff_tokens: str = field(default_factory=lambda: _env(
        "AWAAZ_STAFF_TOKENS", "dev-rm-token:rm:Sana (RM),dev-sup-token:supervisor:Imran (Supervisor)"))

    cors_origins: str = field(default_factory=lambda: _env("AWAAZ_CORS_ORIGINS", "http://localhost:3000"))

    seed_demo_data: bool = field(default_factory=lambda: _bool("AWAAZ_SEED_DEMO", True))


settings = Settings()
