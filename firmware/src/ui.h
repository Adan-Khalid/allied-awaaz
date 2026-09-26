#pragma once
#include <Arduino.h>

void uiBegin();
void uiIdle(const String& merchant, bool online);
void uiEntry(const String& digits);
void uiQr(uint32_t rupees, const String& payload, const String& reference, uint32_t secondsLeft);
void uiQrStatus(const char* status);  // small status strip under the QR ("Processing...")
void uiPaid(uint32_t rupees, const String& reference);
void uiResult(const char* title, const String& body, uint16_t colour);
void uiListening();
void uiThinking();
void uiConfirm(uint32_t rupees);
