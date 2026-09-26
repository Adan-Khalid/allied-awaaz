#pragma once
// ESP32-S3-DevKitC-1 wiring. Display pins are in platformio.ini (TFT_eSPI build flags).

// MAX98357A I2S amplifier (speaker out)
#define PIN_AMP_BCLK   4
#define PIN_AMP_LRC    5
#define PIN_AMP_DIN    6
// INMP441 I2S MEMS microphone (L/R pin to GND = left channel)
#define PIN_MIC_SCK    15
#define PIN_MIC_WS     16
#define PIN_MIC_SD     17
// Push-to-talk: the DevKit BOOT button (GPIO0) works out of the box; hold after boot, never during reset
#define PIN_PTT        0
// Status LED (single-colour; the onboard RGB on GPIO48 also works with neopixelWrite)
#define PIN_LED        2
// 4x4 membrane keypad
static const uint8_t KEYPAD_ROWS[4] = {38, 39, 40, 41};
static const uint8_t KEYPAD_COLS[4] = {42, 18, 8, 7};   // avoids strapping pins 3 and 46
