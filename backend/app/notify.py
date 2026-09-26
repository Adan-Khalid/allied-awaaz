"""Backend -> terminal push over MQTT.

Why MQTT over WebSocket: devices sit behind NAT on flaky 4G/Wi-Fi. MQTT gives QoS 1
redelivery, persistent sessions and a Last Will message. The LWT is used as the
device-presence signal, which directly feeds the Merchant Activation Agent
(DEVICE_OFFLINE reason code) with no extra heartbeat protocol.

Topics
  awaaz/v1/dev/{device_id}/evt      backend -> device   (QoS 1, signed payload)
  awaaz/v1/dev/{device_id}/status   device  -> broker   (retained "online", LWT "offline")
Broker ACLs restrict each device to its own two topics.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Protocol

from .config import settings
from .db import SessionLocal, utcnow
from .models import Device, PaymentRequest
from .security import hmac_hex, mqtt_canonical

log = logging.getLogger(__name__)
TOPIC_EVT = "awaaz/v1/dev/{}/evt"
TOPIC_STATUS = "awaaz/v1/dev/+/status"


def build_payment_message(device: Device, payment: PaymentRequest) -> dict:
    """Increments the device sequence number; caller commits the session."""
    device.mqtt_seq = (device.mqtt_seq or 0) + 1
    ts = int(time.time())
    msg = {
        "v": 1,
        "type": "payment.status",
        "seq": device.mqtt_seq,
        "ts": ts,
        "txn": payment.id,
        "amount_minor": payment.amount_minor,
        "status": payment.status,
    }
    msg["sig"] = hmac_hex(device.secret, mqtt_canonical(1, msg["type"], msg["seq"], ts, payment.id,
                                                        payment.amount_minor, payment.status))
    return msg


class Notifier(Protocol):
    def publish(self, device_id: str, message: dict) -> None: ...


class MemoryNotifier:
    """Used in tests and when MQTT is disabled; the device falls back to polling."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    def publish(self, device_id: str, message: dict) -> None:
        self.sent.append((device_id, message))


class MqttNotifier:
    def __init__(self) -> None:
        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="awaaz-backend", clean_session=False)
        if settings.mqtt_password:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(1, 30)
        self._client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=30)
        self._client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("mqtt connected: %s", reason_code)
        client.subscribe(TOPIC_STATUS, qos=1)

    def _on_message(self, client, userdata, msg):
        try:
            device_id = msg.topic.split("/")[3]
            state = msg.payload.decode().strip().lower()
        except Exception:
            return
        threading.Thread(target=_record_presence, args=(device_id, state == "online"), daemon=True).start()

    def publish(self, device_id: str, message: dict) -> None:
        self._client.publish(TOPIC_EVT.format(device_id), json.dumps(message, separators=(",", ":")), qos=1)


def _record_presence(device_id: str, online: bool) -> None:
    with SessionLocal() as db:
        device = db.get(Device, device_id)
        if device is None:
            return
        device.online = online
        device.last_seen_at = utcnow()
        db.commit()


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = MqttNotifier() if settings.mqtt_enabled else MemoryNotifier()
    return _notifier


def set_notifier(n: Notifier) -> None:
    global _notifier
    _notifier = n
