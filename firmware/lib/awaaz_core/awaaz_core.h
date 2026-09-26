#pragma once
// Portable, Arduino-free protocol logic shared by the firmware and the host test.
// Any change here must keep backend/app/urdu.py and backend/app/security.py in sync;
// firmware/test/native/test_core.cpp checks both against golden files from the backend.
#include <cstdint>
#include <string>
#include <vector>

namespace awaaz {

inline std::vector<std::string> numberClips(uint32_t n) {
  std::vector<std::string> c;
  if (n == 0) { c.push_back("zero"); return c; }
  struct M { uint32_t v; const char* w; };
  static const M mults[] = {{10000000u, "crore"}, {100000u, "lakh"}, {1000u, "hazaar"}, {100u, "sau"}};
  for (const auto& m : mults) {
    uint32_t q = n / m.v;
    n %= m.v;
    if (q) {
      if (m.v == 10000000u && q >= 100) {
        auto inner = numberClips(q);
        c.insert(c.end(), inner.begin(), inner.end());
      } else {
        c.push_back("n_" + std::to_string(q));
      }
      c.push_back(m.w);
    }
  }
  if (n) c.push_back("n_" + std::to_string(n));
  return c;
}

inline std::vector<std::string> paymentReceivedClips(uint32_t rupees) {
  auto c = numberClips(rupees);
  c.push_back("rupay");
  c.push_back("receive_ho_gaye");
  return c;
}

// Must equal backend security.mqtt_canonical().
inline std::string mqttCanonical(int v, const std::string& type, uint64_t seq, int64_t ts, const std::string& txn,
                                 uint32_t amountMinor, const std::string& status) {
  return std::to_string(v) + "|" + type + "|" + std::to_string(seq) + "|" + std::to_string(ts) + "|" + txn + "|" +
         std::to_string(amountMinor) + "|" + status;
}

// Must equal backend security.device_canonical() given the body's SHA-256 hex.
inline std::string requestCanonical(const std::string& method, const std::string& path, const std::string& ts,
                                    const std::string& nonce, const std::string& bodySha256Hex) {
  return method + "\n" + path + "\n" + ts + "\n" + nonce + "\n" + bodySha256Hex;
}

// Accept a message only if it is fresh and strictly newer than the last one seen.
inline bool acceptSequence(uint64_t seq, uint64_t lastSeq, int64_t ts, int64_t now, int64_t maxSkew) {
  int64_t d = now - ts;
  if (d < 0) d = -d;
  return d <= maxSkew && seq > lastSeq;
}

}  // namespace awaaz
