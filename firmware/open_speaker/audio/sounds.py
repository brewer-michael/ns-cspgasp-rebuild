"""Short feedback sounds, synthesized so the project ships no binary audio files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .pcm import read_wav, to_int16, to_int16_mono

RATE = 22050


@dataclass(frozen=True)
class Sound:
    pcm: bytes
    rate: int = RATE

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (2 * self.rate)


def _tone(freq: float, seconds: float, level: float = 0.5, attack: float = 0.008) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    wave = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
    envelope = np.minimum(1.0, t / attack) * np.minimum(1.0, (seconds - t) / 0.04)
    return level * wave / 1.25 * np.clip(envelope, 0.0, 1.0)


def _gap(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE))


def _render(*parts: np.ndarray) -> Sound:
    signal = np.concatenate(parts)
    return Sound((np.clip(signal, -1, 1) * 32767).astype("<i2").tobytes())


def _builtin(name: str) -> Sound:
    if name == "wake":  # rising two-note chime
        return _render(_tone(784, 0.07), _tone(1175, 0.11))
    if name == "done":  # falling acknowledgement
        return _render(_tone(1175, 0.06, 0.4), _tone(880, 0.09, 0.4))
    if name == "error":  # low double buzz
        return _render(_tone(330, 0.12, 0.5), _gap(0.05), _tone(262, 0.18, 0.5))
    if name == "volume":  # short tick for volume changes
        return _render(_tone(1318, 0.045, 0.35, attack=0.003))
    if name == "timer":  # three bright beeps, repeated while ringing
        beeps = [part for _ in range(3) for part in (_tone(1568, 0.12, 0.6), _gap(0.1))]
        return _render(*beeps, _gap(0.5))
    if name == "alarm":  # classic alarm-clock pattern, repeated while ringing
        beeps = [part for _ in range(4) for part in (_tone(1000, 0.09, 0.7), _gap(0.06))]
        return _render(*beeps, _gap(0.6))
    raise KeyError(name)


BUILTIN_SOUNDS = ("wake", "done", "error", "volume", "timer", "alarm")


def load_sound(spec: str | None) -> Sound | None:
    """Resolve a sounds-config value: ``builtin:<name>``, a WAV path, or None."""
    if not spec:
        return None
    if spec.startswith("builtin:"):
        return _builtin(spec.removeprefix("builtin:"))
    pcm, rate, width, channels = read_wav(Path(spec).expanduser().read_bytes())
    pcm = to_int16_mono(to_int16(pcm, width), channels, "mix")
    return Sound(pcm, rate)
