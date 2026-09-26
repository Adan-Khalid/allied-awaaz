#include "crypto.h"
#include <mbedtls/md.h>
#include <esp_random.h>

static String toHex(const uint8_t* d, size_t n) {
  static const char* hx = "0123456789abcdef";
  String s;
  s.reserve(n * 2);
  for (size_t i = 0; i < n; i++) { s += hx[d[i] >> 4]; s += hx[d[i] & 0xF]; }
  return s;
}

String sha256Hex(const uint8_t* data, size_t len) {
  uint8_t out[32];
  mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), data, len, out);
  return toHex(out, 32);
}

String hmacSha256Hex(const char* key, const String& msg) {
  uint8_t out[32];
  mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
                  (const uint8_t*)key, strlen(key),
                  (const uint8_t*)msg.c_str(), msg.length(), out);
  return toHex(out, 32);
}

bool constantTimeEquals(const String& a, const String& b) {
  if (a.length() != b.length()) return false;
  uint8_t diff = 0;
  for (size_t i = 0; i < a.length(); i++) diff |= a[i] ^ b[i];
  return diff == 0;
}

String randomHex(size_t bytes) {
  uint8_t buf[32];
  bytes = min(bytes, sizeof(buf));
  esp_fill_random(buf, bytes);
  return toHex(buf, bytes);
}
