#pragma once
#include <Arduino.h>

String sha256Hex(const uint8_t* data, size_t len);
String hmacSha256Hex(const char* key, const String& msg);
bool constantTimeEquals(const String& a, const String& b);
String randomHex(size_t bytes);
