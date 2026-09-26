// Allied Awaaz terminal. The device is a secure presentation/interaction endpoint:
// it never decides that a payment succeeded. It announces only
//   (a) an HMAC-verified, fresh, sequence-checked MQTT message, or
//   (b) a status read over its own signed HTTPS request (polling fallback).
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Keypad.h>
#include <TFT_eSPI.h>  // colour constants
#include <vector>
#include "config.h"
#include "net.h"
#include "pins.h"
#include "speech.h"
#include "ui.h"

enum class St { IDLE, SHOW_QR, CONFIRM, MESSAGE };
static St state = St::IDLE;

static char KEYS[4][4] = {{'1', '2', '3', 'A'}, {'4', '5', '6', 'B'}, {'7', '8', '9', 'C'}, {'*', '0', '#', 'D'}};
static Keypad keypad(makeKeymap(KEYS), (byte*)KEYPAD_ROWS, (byte*)KEYPAD_COLS, 4, 4);

static String merchantName = "Allied Awaaz";
static String digits;
static String currentTxn, currentRef, pendingRunId;
static uint32_t currentAmount = 0, qrShownAt = 0, messageUntil = 0, lastPoll = 0, paymentTtlS = 300;
static std::vector<String> lastSpoken;
static String announced[8];
static uint8_t announcedIdx = 0;

static bool alreadyAnnounced(const String& txn) {
  for (auto& a : announced) if (a == txn) return true;
  return false;
}

static void speak(const std::vector<String>& clips) {
  lastSpoken = clips;
  playClips(clips);
}

static std::vector<String> clipsFrom(JsonVariantConst arr) {
  std::vector<String> v;
  for (JsonVariantConst c : arr.as<JsonArrayConst>()) v.push_back(c.as<String>());
  return v;
}

static void goIdle() {
  state = St::IDLE;
  digits = "";
  currentTxn = "";
  uiIdle(merchantName, mqttConnected());
  uiEntry(digits);
}

static void showMessage(const char* title, const String& body, uint16_t colour, uint32_t ms = 6000) {
  state = St::MESSAGE;
  messageUntil = millis() + ms;
  uiResult(title, body, colour);
}

static void announcePaid(const String& txn, uint32_t rupees) {
  if (alreadyAnnounced(txn)) return;
  announced[announcedIdx++ % 8] = txn;
  digitalWrite(PIN_LED, HIGH);
  uiPaid(rupees, txn == currentTxn ? currentRef : String(""));
  speak(paymentReceivedClips(rupees));
  digitalWrite(PIN_LED, LOW);
  state = St::MESSAGE;
  messageUntil = millis() + 5000;
}

// Single place that turns an agent response into screen + voice + next state.
static void handleAgent(JsonDocument& r) {
  JsonVariantConst action = r["action"];
  String type = action["type"] | "";
  std::vector<String> clips = clipsFrom(r["speech"]["clips"]);

  if (type == "show_qr") {
    currentTxn = action["txn_id"].as<String>();
    currentRef = action["reference"].as<String>();
    currentAmount = action["amount_rupees"] | 0;
    qrShownAt = millis();
    state = St::SHOW_QR;
    uiQr(currentAmount, action["qr_payload"].as<String>(), currentRef, paymentTtlS);
    speak(clips);
    return;
  }
  if (type == "confirm_amount") {
    pendingRunId = action["run_id"].as<String>();
    currentAmount = action["amount_rupees"] | 0;
    state = St::CONFIRM;
    uiConfirm(currentAmount);
    speak(clips);
    return;
  }
  String outcome = r["outcome"] | "";
  uint16_t colour = 0x02C6;
  if (outcome == "CLAIM_NOT_RECEIVED" || outcome == "CLAIM_FAILED") colour = TFT_RED;
  else if (outcome == "CLAIM_PENDING" || outcome.startsWith("CLARIFY")) colour = 0xFD20;
  else if (outcome == "CLAIM_RECEIVED") colour = 0x07E0;
  showMessage(outcome.startsWith("CLAIM") ? "Bank check" : "Allied Awaaz", r["display_text"].as<String>(), colour, 8000);
  speak(clips);
}

static void onVerifiedPayment(const PaymentStatusMsg& m) {
  if (m.status == "SUCCEEDED") announcePaid(m.txn, m.amountMinor / 100);
  else if (m.status == "PENDING" && m.txn == currentTxn && state == St::SHOW_QR) uiQrStatus("Customer ke bank mein process...");
  else if (m.status == "FAILED" && m.txn == currentTxn) {
    showMessage("Payment fail", "Customer dobara payment karein", TFT_RED);
    playClip("payment_fail_hui");
  }
}

static void sendQuery(const String& body) {
  uiThinking();
  JsonDocument r;
  int code = apiJson("POST", "/v1/device/query", body, r);
  if (code == 200) handleAgent(r);
  else showMessage("Connection", "Bank se rabta nahi ho saka. Dobara koshish karein.", TFT_RED);
}

static void submitAmount() {
  if (!digits.length()) return;
  uiThinking();
  JsonDocument r;
  int code = apiJson("POST", "/v1/device/payments", "{\"amount_rupees\":" + String(digits.toInt()) + "}", r);
  digits = "";
  if (code == 200) handleAgent(r);
  else showMessage("Connection", "QR nahi ban saka. Internet check karein.", TFT_RED);
}

static void pushToTalk() {
  uiListening();
  size_t len = 0;
  uint8_t* wav = recordWhileHeld(PIN_PTT, MAX_RECORD_S, &len);
  if (!wav || len < 44 + 16000) {  // under 0.5 s: treat as accidental press
    free(wav);
    goIdle();
    return;
  }
  uiThinking();
  JsonDocument r;
  int code = apiBinary("/v1/device/voice", wav, len, "audio/wav", r);
  free(wav);
  if (code == 200) handleAgent(r);
  else showMessage("Connection", "Awaaz bank tak nahi pohanchi. Keypad istemal karein.", TFT_RED);
}

static void onKey(char k) {
  if (state == St::CONFIRM) {
    if (k == '#') {
      JsonDocument r;
      if (apiJson("POST", "/v1/device/confirm", "{\"run_id\":\"" + pendingRunId + "\"}", r) == 200 && (r["ok"] | false))
        handleAgent(r);
      else goIdle();
    } else if (k == '*') goIdle();
    return;
  }
  if (state == St::SHOW_QR && k == '*') { goIdle(); return; }
  if (state == St::MESSAGE) goIdle();

  if (k >= '0' && k <= '9' && digits.length() < 7) { digits += k; uiEntry(digits); }
  else if (k == '*') { digits = digits.substring(0, digits.length() ? digits.length() - 1 : 0); uiEntry(digits); }
  else if (k == '#') submitAmount();
  else if (k == 'A') sendQuery("{\"intent\":\"TODAY_SUMMARY\"}");
  else if (k == 'B') sendQuery("{\"intent\":\"LAST_PAYMENT\"}");
  else if (k == 'C' && digits.length()) {  // "customer says he paid <typed amount>"
    String body = "{\"intent\":\"CHECK_CLAIM\",\"amount_rupees\":" + String(digits.toInt()) + "}";
    digits = "";
    sendQuery(body);
  } else if (k == 'D' && !lastSpoken.empty()) playClips(lastSpoken);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_PTT, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  uiBegin();
  uiResult("Allied Awaaz", "Bank se connect ho raha hai...", 0x02C6);
  audioBegin();
  netBegin(onVerifiedPayment);
  JsonDocument cfg;
  if (apiJson("GET", "/v1/device/config", "", cfg) == 200) {
    merchantName = cfg["merchant_name"].as<String>();
    paymentTtlS = cfg["payment_ttl_s"] | 300;
  }
  goIdle();
}

void loop() {
  netLoop();
  char k = keypad.getKey();
  if (k) onKey(k);
  if (digitalRead(PIN_PTT) == LOW && state != St::CONFIRM) { delay(30); if (digitalRead(PIN_PTT) == LOW) pushToTalk(); }

  if (state == St::SHOW_QR) {
    if (millis() - qrShownAt > paymentTtlS * 1000UL) {
      showMessage("QR expire", "Payment ka waqt khatam. Nayi raqam likhein.", 0xFD20);
      playClip("payment_expire");
    } else if (!mqttConnected() && millis() - lastPoll > 3000) {  // polling fallback, still authenticated
      lastPoll = millis();
      JsonDocument r;
      if (apiJson("GET", "/v1/device/payments/" + currentTxn, "", r) == 200) {
        String st = r["status"] | "";
        if (st == "SUCCEEDED") announcePaid(currentTxn, (r["amount_minor"] | 0UL) / 100);
        else if (st == "FAILED") onVerifiedPayment({currentTxn, 0, "FAILED"});
      }
    }
  }
  if (state == St::MESSAGE && millis() > messageUntil) goIdle();
}
