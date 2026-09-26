// Host-side test: proves the firmware protocol core matches the backend reference.
// Build and run:  g++ -std=c++17 -Ilib/awaaz_core test/native/test_core.cpp -o /tmp/awaaz_core_test && /tmp/awaaz_core_test test/golden
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include "awaaz_core.h"

static int failures = 0;
static void check(bool ok, const std::string& what) {
  if (!ok) { if (++failures <= 10) std::cerr << "FAIL: " << what << "\n"; }
}

static std::string join(const std::vector<std::string>& v) {
  std::string s;
  for (size_t i = 0; i < v.size(); i++) s += (i ? " " : "") + v[i];
  return s;
}

static std::vector<std::string> split(const std::string& s, char d) {
  std::vector<std::string> out;
  std::stringstream ss(s);
  std::string x;
  while (std::getline(ss, x, d)) out.push_back(x);
  return out;
}

static std::string unescape(const std::string& s) {
  std::string o;
  for (size_t i = 0; i < s.size(); i++) {
    if (s[i] == '\\' && i + 1 < s.size() && s[i + 1] == 'n') { o += '\n'; i++; } else o += s[i];
  }
  return o;
}

int main(int argc, char** argv) {
  std::string dir = argc > 1 ? argv[1] : "test/golden";
  size_t clipCases = 0, canonCases = 0;

  std::ifstream clips(dir + "/clips.txt");
  if (!clips) { std::cerr << "missing " << dir << "/clips.txt\n"; return 2; }
  for (std::string line; std::getline(clips, line);) {
    auto bar = line.find('|');
    uint32_t n = (uint32_t)std::stoul(line.substr(0, bar));
    check(join(awaaz::numberClips(n)) == line.substr(bar + 1), "numberClips(" + std::to_string(n) + ")");
    clipCases++;
  }

  std::ifstream canon(dir + "/canonical.txt");
  if (!canon) { std::cerr << "missing canonical.txt\n"; return 2; }
  for (std::string line; std::getline(canon, line);) {
    auto f = split(line, '\t');
    if (f[0] == "M") {
      auto got = awaaz::mqttCanonical(std::stoi(f[1]), f[2], std::stoull(f[3]), std::stoll(f[4]), f[5],
                                      (uint32_t)std::stoul(f[6]), f[7]);
      check(got == unescape(f[8]), "mqttCanonical line " + std::to_string(canonCases));
    } else {
      check(awaaz::requestCanonical(f[1], f[2], f[3], f[4], f[5]) == unescape(f[6]), "requestCanonical");
    }
    canonCases++;
  }

  auto pay = awaaz::paymentReceivedClips(1250);
  check(join(pay) == "n_1 hazaar n_2 sau n_50 rupay receive_ho_gaye", "paymentReceivedClips(1250)");
  check(awaaz::acceptSequence(5, 4, 1000, 1100, 300), "fresh newer accepted");
  check(!awaaz::acceptSequence(4, 4, 1000, 1100, 300), "equal seq rejected");
  check(!awaaz::acceptSequence(3, 4, 1000, 1100, 300), "older seq rejected");
  check(!awaaz::acceptSequence(9, 4, 1000, 1400, 300), "stale rejected");
  check(!awaaz::acceptSequence(9, 4, 1400, 1000, 300), "future-dated rejected");

  if (failures) { std::cerr << failures << " failures\n"; return 1; }
  std::cout << "firmware core OK: " << clipCases << " amount cases, " << canonCases << " canonical cases, 6 unit checks\n";
  return 0;
}
