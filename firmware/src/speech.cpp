#include "speech.h"
#include <LittleFS.h>
#include <driver/i2s.h>
#include "pins.h"
#include <awaaz_core.h>

#define AMP_PORT I2S_NUM_0
#define MIC_PORT I2S_NUM_1
static const uint32_t SAMPLE_RATE = 16000;

static std::vector<String> toArduino(const std::vector<std::string>& v) {
  std::vector<String> out;
  out.reserve(v.size());
  for (auto& x : v) out.push_back(String(x.c_str()));
  return out;
}

std::vector<String> numberClips(uint32_t n) { return toArduino(awaaz::numberClips(n)); }
std::vector<String> paymentReceivedClips(uint32_t rupees) { return toArduino(awaaz::paymentReceivedClips(rupees)); }

void audioBegin() {
  LittleFS.begin(true);
  i2s_config_t amp = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = 0, .dma_buf_count = 8, .dma_buf_len = 256,
    .use_apll = false, .tx_desc_auto_clear = true, .fixed_mclk = 0};
  i2s_pin_config_t ampPins = {.mck_io_num = I2S_PIN_NO_CHANGE, .bck_io_num = PIN_AMP_BCLK,
                              .ws_io_num = PIN_AMP_LRC, .data_out_num = PIN_AMP_DIN, .data_in_num = I2S_PIN_NO_CHANGE};
  i2s_driver_install(AMP_PORT, &amp, 0, nullptr);
  i2s_set_pin(AMP_PORT, &ampPins);

  i2s_config_t mic = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = 0, .dma_buf_count = 8, .dma_buf_len = 256,
    .use_apll = false, .tx_desc_auto_clear = false, .fixed_mclk = 0};
  i2s_pin_config_t micPins = {.mck_io_num = I2S_PIN_NO_CHANGE, .bck_io_num = PIN_MIC_SCK,
                              .ws_io_num = PIN_MIC_WS, .data_out_num = I2S_PIN_NO_CHANGE, .data_in_num = PIN_MIC_SD};
  i2s_driver_install(MIC_PORT, &mic, 0, nullptr);
  i2s_set_pin(MIC_PORT, &micPins);
}

// Walks RIFF chunks to the "data" chunk (ffmpeg may insert LIST chunks before it).
static bool seekToData(File& f, uint32_t* dataLen) {
  char id[4];
  uint32_t sz;
  f.seek(12);
  while (f.available() >= 8) {
    f.read((uint8_t*)id, 4);
    f.read((uint8_t*)&sz, 4);
    if (memcmp(id, "data", 4) == 0) { *dataLen = sz; return true; }
    f.seek(f.position() + sz + (sz & 1));
  }
  return false;
}

bool playClip(const String& id) {
  File f = LittleFS.open("/clips/" + id + ".wav", "r");
  if (!f) { Serial.printf("missing clip %s\n", id.c_str()); return false; }
  uint32_t remaining = 0;
  if (!seekToData(f, &remaining)) { f.close(); return false; }
  static uint8_t buf[1024];
  while (remaining > 0) {
    size_t n = f.read(buf, min<uint32_t>(sizeof(buf), remaining));
    if (n == 0) break;
    size_t written;
    i2s_write(AMP_PORT, buf, n, &written, portMAX_DELAY);
    remaining -= n;
  }
  f.close();
  return true;
}

void playClips(const std::vector<String>& clips) {
  for (auto& c : clips) playClip(c);
  static const uint8_t silence[640] = {0};  // 20 ms tail so the last word is not clipped
  size_t w;
  i2s_write(AMP_PORT, silence, sizeof(silence), &w, portMAX_DELAY);
  i2s_zero_dma_buffer(AMP_PORT);
}

static void writeWavHeader(uint8_t* h, uint32_t dataLen) {
  auto u32 = [&](int o, uint32_t v) { memcpy(h + o, &v, 4); };
  auto u16 = [&](int o, uint16_t v) { memcpy(h + o, &v, 2); };
  memcpy(h, "RIFF", 4); u32(4, 36 + dataLen); memcpy(h + 8, "WAVEfmt ", 8);
  u32(16, 16); u16(20, 1); u16(22, 1); u32(24, SAMPLE_RATE); u32(28, SAMPLE_RATE * 2); u16(32, 2); u16(34, 16);
  memcpy(h + 36, "data", 4); u32(40, dataLen);
}

uint8_t* recordWhileHeld(int holdPin, uint32_t maxSeconds, size_t* outLen) {
  const size_t maxSamples = SAMPLE_RATE * maxSeconds;
  uint8_t* wav = (uint8_t*)ps_malloc(44 + maxSamples * 2);
  if (!wav) return nullptr;
  int16_t* pcm = (int16_t*)(wav + 44);
  size_t count = 0;
  int32_t raw[256];
  i2s_zero_dma_buffer(MIC_PORT);
  while (digitalRead(holdPin) == LOW && count < maxSamples) {
    size_t got = 0;
    i2s_read(MIC_PORT, raw, sizeof(raw), &got, pdMS_TO_TICKS(50));
    for (size_t i = 0; i < got / 4 && count < maxSamples; i++) {
      int32_t s = raw[i] >> 14;                  // INMP441: 24-bit left-justified in 32; gain via shift
      pcm[count++] = (int16_t)constrain(s, -32768, 32767);
    }
  }
  writeWavHeader(wav, count * 2);
  *outLen = 44 + count * 2;
  return wav;
}
