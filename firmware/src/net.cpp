#include "net.h"
#include <HTTPClient.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include "config.h"
#include "crypto.h"
#include <awaaz_core.h>

static WiFiClient mqttNet;
static PubSubClient mqtt(mqttNet);
static Preferences prefs;
static uint64_t lastSeq = 0;
static std::function<void(const PaymentStatusMsg&)> paymentCb;
static String topicEvt, topicStatus;

bool timeSynced() { return time(nullptr) > 1700000000; }
bool mqttConnected() { return mqtt.connected(); }

// Verifies HMAC, freshness and strictly increasing sequence before anything is announced.
static void onMqtt(char* topic, byte* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  uint64_t seq = doc["seq"] | 0ULL;
  int64_t ts = doc["ts"] | 0LL;
  String type = doc["type"] | "", txn = doc["txn"] | "", status = doc["status"] | "", sig = doc["sig"] | "";
  uint32_t amount = doc["amount_minor"] | 0UL;
  int v = doc["v"] | 0;

  String canonical = awaaz::mqttCanonical(v, type.c_str(), seq, ts, txn.c_str(), amount, status.c_str()).c_str();
  if (!constantTimeEquals(hmacSha256Hex(DEVICE_SECRET, canonical), sig)) { Serial.println("mqtt: bad sig"); return; }
  if (!timeSynced() || !awaaz::acceptSequence(seq, lastSeq, ts, (int64_t)time(nullptr), MAX_CLOCK_SKEW_S)) {
    Serial.println("mqtt: stale or replayed");
    return;
  }
  lastSeq = seq;
  prefs.putULong64("seq", lastSeq);
  if (type == "payment.status" && paymentCb) paymentCb({txn, amount, status});
}

static void mqttReconnect() {
  static uint32_t lastTry = 0;
  if (mqtt.connected() || millis() - lastTry < 3000) return;
  lastTry = millis();
  // Last Will: broker publishes "offline" if we vanish. This feeds the bank's DEVICE_OFFLINE signal.
  if (mqtt.connect(DEVICE_ID, DEVICE_ID, MQTT_PASSWORD, topicStatus.c_str(), 1, true, "offline", false)) {
    mqtt.publish(topicStatus.c_str(), "online", true);
    mqtt.subscribe(topicEvt.c_str(), 1);
  }
}

void netBegin(std::function<void(const PaymentStatusMsg&)> cb) {
  paymentCb = cb;
  prefs.begin("awaaz", false);
  lastSeq = prefs.getULong64("seq", 0);
  topicEvt = String("awaaz/v1/dev/") + DEVICE_ID + "/evt";
  topicStatus = String("awaaz/v1/dev/") + DEVICE_ID + "/status";
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  configTime(5 * 3600, 0, "pool.ntp.org", "time.google.com");  // PKT, but signing uses epoch seconds
  for (int i = 0; i < 40 && !timeSynced(); i++) delay(250);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqtt);
  mqtt.setKeepAlive(30);
  mqttReconnect();
}

void netLoop() {
  if (WiFi.status() != WL_CONNECTED) { WiFi.reconnect(); return; }
  mqttReconnect();
  mqtt.loop();
}

static int send(const char* method, const String& path, const uint8_t* body, size_t len, const char* ctype,
                JsonDocument& out, uint32_t timeoutMs) {
  String ts = String((long long)time(nullptr));
  String nonce = randomHex(12);
  String canonical = awaaz::requestCanonical(method, path.c_str(), ts.c_str(), nonce.c_str(),
                                             sha256Hex(body, len).c_str()).c_str();
  HTTPClient http;
  WiFiClientSecure tls;
  String url = String(API_BASE) + path;
  if (url.startsWith("https")) {
    if (strlen(ROOT_CA)) tls.setCACert(ROOT_CA);
    http.begin(tls, url);
  } else {
    http.begin(url);
  }
  http.setTimeout(timeoutMs);
  http.addHeader("X-Device-Id", DEVICE_ID);
  http.addHeader("X-Timestamp", ts);
  http.addHeader("X-Nonce", nonce);
  http.addHeader("X-Signature", hmacSha256Hex(DEVICE_SECRET, canonical));
  if (ctype) http.addHeader("Content-Type", ctype);
  int code = http.sendRequest(method, (uint8_t*)body, len);
  if (code > 0) deserializeJson(out, http.getString());
  http.end();
  return code;
}

int apiJson(const char* method, const String& path, const String& body, JsonDocument& out) {
  return send(method, path, (const uint8_t*)body.c_str(), body.length(), body.length() ? "application/json" : nullptr,
              out, 8000);
}

int apiBinary(const String& path, const uint8_t* data, size_t len, const char* ctype, JsonDocument& out) {
  return send("POST", path, data, len, ctype, out, 15000);
}
