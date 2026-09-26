#!/usr/bin/env python3
"""Build the terminal's voice clip library (firmware/data/clips/<id>.wav).

    python tools/gen_clips.py --list > clips.csv      # recording sheet for a human voice (recommended)
    python tools/gen_clips.py --import-dir recordings # convert human recordings named <id>.wav/.m4a/.mp3
    python tools/gen_clips.py --tts                   # synthetic fallback via OpenAI-compatible TTS
    python tools/gen_clips.py --espeak                # offline robotic placeholders for hardware bring-up only

A single consistent human Urdu voice sounds far better than current synthetic Urdu and
is what the demo should ship. All output is normalised to 16 kHz, mono, 16-bit PCM WAV
with leading/trailing silence trimmed, which the firmware plays back-to-back.
Requires ffmpeg on PATH for --import-dir and --tts.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("AWAAZ_DATABASE_URL", "sqlite://")
from app.urdu import all_clip_ids, clip_text  # noqa: E402

OUT = ROOT / "firmware" / "data" / "clips"
FFMPEG_NORMALISE = ["-ac", "1", "-ar", "16000", "-sample_fmt", "s16",
                    "-af", "silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=1:stop_threshold=-45dB,"
                           "loudnorm=I=-16:TP=-1.5"]


def normalise(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), *FFMPEG_NORMALISE, str(dst)], check=True)


def cmd_list() -> None:
    w = csv.writer(sys.stdout)
    w.writerow(["clip_id", "say_this"])
    for cid in all_clip_ids():
        w.writerow([cid, clip_text(cid)])


def cmd_import(folder: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = []
    for cid in all_clip_ids():
        src = next((p for p in folder.glob(f"{cid}.*")), None)
        if src is None:
            missing.append(cid)
            continue
        normalise(src, OUT / f"{cid}.wav")
    print(f"imported {len(all_clip_ids()) - len(missing)} clips")
    if missing:
        print("MISSING:", " ".join(missing))
        sys.exit(1)


def cmd_tts() -> None:
    import httpx
    base = os.getenv("AWAAZ_TTS_BASE_URL", "https://api.openai.com/v1")
    key = os.environ["AWAAZ_TTS_API_KEY"]
    model, voice = os.getenv("AWAAZ_TTS_MODEL", "gpt-4o-mini-tts"), os.getenv("AWAAZ_TTS_VOICE", "alloy")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp.mp3"
    for cid in all_clip_ids():
        r = httpx.post(f"{base}/audio/speech", headers={"Authorization": f"Bearer {key}"}, timeout=30,
                       json={"model": model, "voice": voice, "input": clip_text(cid),
                             "instructions": "Speak in natural Pakistani Urdu, clear and friendly, like a shop assistant."})
        r.raise_for_status()
        tmp.write_bytes(r.content)
        normalise(tmp, OUT / f"{cid}.wav")
        print("ok", cid)
    tmp.unlink(missing_ok=True)


def cmd_espeak() -> None:
    """Placeholder clips so the playback path can be tested before real recordings exist."""
    voice = os.getenv("AWAAZ_ESPEAK_VOICE", "hi")
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp.wav"
    for cid in all_clip_ids():
        subprocess.run(["espeak-ng", "-v", voice, "-s", "150", "-w", str(tmp), clip_text(cid)], check=True)
        normalise(tmp, OUT / f"{cid}.wav")
    tmp.unlink(missing_ok=True)
    total = sum(p.stat().st_size for p in OUT.glob("*.wav"))
    print(f"wrote {len(all_clip_ids())} placeholder clips, {total / 1e6:.2f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--import-dir", type=Path)
    g.add_argument("--tts", action="store_true")
    g.add_argument("--espeak", action="store_true")
    a = ap.parse_args()
    if a.list:
        cmd_list()
    elif a.import_dir:
        cmd_import(a.import_dir)
    elif a.espeak:
        cmd_espeak()
    else:
        cmd_tts()
