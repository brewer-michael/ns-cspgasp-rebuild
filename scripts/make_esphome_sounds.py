#!/usr/bin/env python3
"""Write the speaker's built-in sounds to esphome/sounds/ as WAV files.

The Linux firmware synthesizes its sounds when it starts
(firmware/open_speaker/audio/sounds.py). ESPHome builds them into the firmware from
files, so this renders the same sounds for the ESP32-S3 build. Run it again after
changing a sound; --check only reports whether the files are up to date.
"""

import argparse
import io
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "firmware"))

from open_speaker.audio.sounds import BUILTIN_SOUNDS, load_sound  # noqa: E402

OUT = ROOT / "esphome" / "sounds"


def render(name: str) -> bytes:
    sound = load_sound(f"builtin:{name}")
    assert sound is not None
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sound.rate)
        wav.writeframes(sound.pcm)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check the files")
    args = parser.parse_args()
    stale = []
    OUT.mkdir(parents=True, exist_ok=True)
    for name in BUILTIN_SOUNDS:
        path = OUT / f"{name}.wav"
        data = render(name)
        if path.exists() and path.read_bytes() == data:
            continue
        stale.append(path.relative_to(ROOT))
        if not args.check:
            path.write_bytes(data)
    if args.check and stale:
        print("Out of date, run scripts/make_esphome_sounds.py:", *stale, sep="\n  ")
        return 1
    for path in stale:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
