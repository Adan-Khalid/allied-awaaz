#pragma once
#include <Arduino.h>
#include <vector>

// Clip-concatenation voice. Mirrors backend/app/urdu.py number_clips() exactly, so a
// payment amount received in a signed MQTT message is spoken from the verified integer
// without trusting any server-supplied text.
std::vector<String> numberClips(uint32_t rupees);
std::vector<String> paymentReceivedClips(uint32_t rupees);

void audioBegin();
void playClips(const std::vector<String>& clips);
bool playClip(const String& id);

// Push-to-talk capture: returns a PSRAM buffer holding a complete 16 kHz mono 16-bit WAV.
// Caller frees with free(). Records while holdPin stays LOW, up to maxSeconds.
uint8_t* recordWhileHeld(int holdPin, uint32_t maxSeconds, size_t* outLen);
