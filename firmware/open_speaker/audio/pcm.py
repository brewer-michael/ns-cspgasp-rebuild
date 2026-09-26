"""Small PCM helpers built on numpy (signed little-endian samples)."""

from __future__ import annotations

import io
import math
import wave

import numpy as np

_INT16_MAX = 32767


def to_int16_mono(data: bytes, channels: int, channel: int | str = "mix") -> bytes:
    """Reduce interleaved 16-bit audio to one channel.

    ``channel`` is an index (0 = left) or ``"mix"`` to average all channels.
    """
    if channels == 1:
        return data
    samples = np.frombuffer(data, dtype="<i2")
    frames = samples[: len(samples) - len(samples) % channels].reshape(-1, channels)
    if channel == "mix":
        mono = frames.astype(np.int32).mean(axis=1)
        return np.round(mono).astype("<i2").tobytes()
    return np.ascontiguousarray(frames[:, int(channel)]).tobytes()


def apply_gain(data: bytes, gain: float) -> bytes:
    """Multiply 16-bit samples by ``gain``, clipping to the valid range."""
    if gain == 1.0 or not data:
        return data
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) * gain
    return np.clip(samples, -32768, _INT16_MAX).astype("<i2").tobytes()


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20))


def rms_dbfs(data: bytes) -> float:
    """Signal level in dBFS (0 = full-scale square wave, -inf = digital silence)."""
    if len(data) < 2:
        return -math.inf
    samples = np.frombuffer(data[: len(data) - len(data) % 2], dtype="<i2").astype(np.float64)
    rms = math.sqrt(float(np.mean(samples * samples)))
    return 20 * math.log10(rms / 32768) if rms > 0 else -math.inf


def to_int16(data: bytes, width: int) -> bytes:
    """Convert 8/24/32-bit PCM to 16-bit."""
    if width == 2:
        return data
    if width == 1:  # unsigned 8-bit
        samples = (np.frombuffer(data, dtype=np.uint8).astype(np.int16) - 128) << 8
        return samples.astype("<i2").tobytes()
    if width == 3:
        raw = np.frombuffer(data[: len(data) - len(data) % 3], dtype=np.uint8).reshape(-1, 3)
        # Keep the two most significant bytes of each little-endian 24-bit sample.
        return np.ascontiguousarray(raw[:, 1:]).tobytes()
    if width == 4:
        samples = np.frombuffer(data[: len(data) - len(data) % 4], dtype="<i4") >> 16
        return samples.astype("<i2").tobytes()
    raise ValueError(f"unsupported sample width: {width}")


def wav_bytes(pcm: bytes, rate: int, width: int = 2, channels: int = 1) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(width)
            wav.setframerate(rate)
            wav.writeframes(pcm)
        return buffer.getvalue()


def is_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def read_wav(data: bytes) -> tuple[bytes, int, int, int]:
    """Return ``(pcm, rate, width, channels)`` for a WAV file's bytes."""
    with io.BytesIO(data) as buffer, wave.open(buffer, "rb") as wav:
        return (
            wav.readframes(wav.getnframes()),
            wav.getframerate(),
            wav.getsampwidth(),
            wav.getnchannels(),
        )


def silence(seconds: float, rate: int, channels: int = 1) -> bytes:
    return bytes(int(seconds * rate) * 2 * channels)


def duration(pcm: bytes, rate: int, width: int = 2, channels: int = 1) -> float:
    return len(pcm) / (rate * width * channels)
