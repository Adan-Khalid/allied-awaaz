#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>
#include <functional>

struct PaymentStatusMsg {
  String txn;
  uint32_t amountMinor;
  String status;  // PENDING | SUCCEEDED | FAILED
};

void netBegin(std::function<void(const PaymentStatusMsg&)> onVerifiedPayment);
void netLoop();
bool mqttConnected();
bool timeSynced();

// Signed HTTP to the backend. Returns HTTP status (negative on transport error); fills `out`.
int apiJson(const char* method, const String& path, const String& body, JsonDocument& out);
int apiBinary(const String& path, const uint8_t* data, size_t len, const char* contentType, JsonDocument& out);
