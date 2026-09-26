#include "ui.h"
#include <TFT_eSPI.h>
#include <qrcode.h>

static TFT_eSPI tft;
static const uint16_t BRAND = 0x02C6;   // ABL-like deep green (RGB565)
static const uint16_t OK_GREEN = 0x07E0;
static const uint16_t WARN = 0xFD20;

static void header(const char* text, uint16_t bg = BRAND) {
  tft.fillRect(0, 0, tft.width(), 34, bg);
  tft.setTextColor(TFT_WHITE, bg);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(text, tft.width() / 2, 17, 4);
}

static String pkr(uint32_t v) {
  String s = String(v), out;
  int n = s.length();
  for (int i = 0; i < n; i++) { out += s[i]; if ((n - i - 1) % 3 == 0 && i != n - 1) out += ','; }
  return "PKR " + out;
}

static void wrapped(const String& text, int y, int font = 2) {
  tft.setTextDatum(TC_DATUM);
  String line, word;
  int maxW = tft.width() - 16;
  for (size_t i = 0; i <= text.length(); i++) {
    char c = i < text.length() ? text[i] : ' ';
    if (c == ' ') {
      String trial = line.length() ? line + " " + word : word;
      if (tft.textWidth(trial, font) > maxW && line.length()) { tft.drawString(line, tft.width() / 2, y, font); y += 18; line = word; }
      else line = trial;
      word = "";
    } else word += c;
  }
  if (line.length()) tft.drawString(line, tft.width() / 2, y, font);
}

void uiBegin() {
  tft.init();
  tft.setRotation(0);  // portrait 240x320
  tft.fillScreen(TFT_WHITE);
}

void uiIdle(const String& merchant, bool online) {
  tft.fillScreen(TFT_WHITE);
  header("Allied Awaaz");
  tft.setTextColor(TFT_BLACK, TFT_WHITE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(merchant, tft.width() / 2, 70, 4);
  tft.drawString("Raqam likhein ya bolein", tft.width() / 2, 130, 2);
  tft.drawString("# = QR    A = Aaj    B = Aakhri", tft.width() / 2, 160, 2);
  tft.drawString("C = Payment aayi?    D = Dobara", tft.width() / 2, 180, 2);
  tft.fillCircle(tft.width() - 14, 300, 6, online ? OK_GREEN : TFT_RED);
  tft.setTextDatum(MR_DATUM);
  tft.drawString(online ? "Bank connected" : "Offline", tft.width() - 26, 300, 2);
}

void uiEntry(const String& digits) {
  tft.fillRect(0, 200, tft.width(), 80, TFT_WHITE);
  tft.setTextColor(BRAND, TFT_WHITE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(digits.length() ? pkr(digits.toInt()) : String("PKR 0"), tft.width() / 2, 240, 4);
}

void uiQr(uint32_t rupees, const String& payload, const String& reference, uint32_t secondsLeft) {
  tft.fillScreen(TFT_WHITE);
  header(pkr(rupees).c_str());
  QRCode qr;
  static uint8_t* qrbuf = nullptr;
  if (!qrbuf) qrbuf = (uint8_t*)malloc(qrcode_getBufferSize(10));
  qrcode_initText(&qr, qrbuf, 10, ECC_LOW, payload.c_str());  // v10-L holds up to 271 bytes (EMVCo-size payloads)
  int scale = min(tft.width() - 12, 230) / qr.size;
  int size = qr.size * scale, x0 = (tft.width() - size) / 2, y0 = 42;
  tft.fillRect(x0 - 6, y0 - 6, size + 12, size + 12, TFT_WHITE);
  for (uint8_t y = 0; y < qr.size; y++)
    for (uint8_t x = 0; x < qr.size; x++)
      if (qrcode_getModule(&qr, x, y)) tft.fillRect(x0 + x * scale, y0 + y * scale, scale, scale, TFT_BLACK);
  tft.setTextColor(TFT_DARKGREY, TFT_WHITE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("Ref " + reference, tft.width() / 2, y0 + size + 14, 2);
  uiQrStatus("Customer scan karein");
  (void)secondsLeft;
}

void uiQrStatus(const char* status) {
  tft.fillRect(0, 294, tft.width(), 26, BRAND);
  tft.setTextColor(TFT_WHITE, BRAND);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(status, tft.width() / 2, 307, 2);
}

void uiPaid(uint32_t rupees, const String& reference) {
  tft.fillScreen(OK_GREEN);
  tft.setTextColor(TFT_WHITE, OK_GREEN);
  tft.setTextDatum(MC_DATUM);
  tft.fillCircle(tft.width() / 2, 80, 40, TFT_WHITE);
  tft.drawWideLine(tft.width() / 2 - 20, 80, tft.width() / 2 - 5, 97, 7, OK_GREEN, TFT_WHITE);
  tft.drawWideLine(tft.width() / 2 - 5, 97, tft.width() / 2 + 22, 62, 7, OK_GREEN, TFT_WHITE);
  tft.drawString("PAYMENT RECEIVED", tft.width() / 2, 150, 4);
  tft.drawString(pkr(rupees), tft.width() / 2, 195, 4);
  tft.drawString("Bank verified  " + reference, tft.width() / 2, 240, 2);
}

void uiResult(const char* title, const String& body, uint16_t colour) {
  tft.fillScreen(TFT_WHITE);
  header(title, colour);
  tft.setTextColor(TFT_BLACK, TFT_WHITE);
  wrapped(body, 60, 4);
}

void uiListening() {
  tft.fillScreen(TFT_WHITE);
  header("Sun raha hoon...", WARN);
  tft.fillCircle(tft.width() / 2, 170, 45, WARN);
  tft.setTextColor(TFT_BLACK, TFT_WHITE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("Button chhor dein jab bol lein", tft.width() / 2, 250, 2);
}

void uiThinking() { uiQrStatus("Bank se check ho raha hai..."); }

void uiConfirm(uint32_t rupees) {
  tft.fillScreen(TFT_WHITE);
  header("Confirm karein", WARN);
  tft.setTextColor(TFT_BLACK, TFT_WHITE);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(pkr(rupees), tft.width() / 2, 130, 4);
  tft.drawString("# = Haan    * = Nahi", tft.width() / 2, 200, 4);
}
