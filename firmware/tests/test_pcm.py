"""PCM helpers: channels, sample widths, gain, levels and WAV files."""

from __future__ import annotations

import math
import struct

import pytest
from conftest import RATE, tone

from open_speaker.audio import pcm


def int16(*values: int) -> bytes:
    return struct.pack(f"<{len(values)}h", *values)


def values(data: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(data) // 2}h", data))


def interleave(*channels: bytes) -> bytes:
    columns = [values(channel) for channel in channels]
    return int16(*(sample for frame in zip(*columns, strict=True) for sample in frame))


# ---------------------------------------------------------------------------
# Channels and sample widths


def test_mono_passes_through() -> None:
    data = int16(1, -2, 3)
    assert pcm.to_int16_mono(data, channels=1) == data


def test_pick_one_channel_of_stereo() -> None:
    stereo = int16(100, -100, 2000, 4000, -32768, 0, 32767, 5)
    assert values(pcm.to_int16_mono(stereo, 2, channel=0)) == [100, 2000, -32768, 32767]
    assert values(pcm.to_int16_mono(stereo, 2, channel=1)) == [-100, 4000, 0, 5]


def test_mix_stereo_without_overflow() -> None:
    stereo = int16(100, -100, 2000, 4000, 32767, 32767, -32768, -32768, 32767, -32767)
    assert values(pcm.to_int16_mono(stereo, 2, "mix")) == [0, 3000, 32767, -32768, 0]


def test_mix_real_audio() -> None:
    left = tone(0.1, amplitude=0.5)
    right = pcm.silence(0.1, RATE)
    mixed = values(pcm.to_int16_mono(interleave(left, right), 2))
    assert all(abs(m - s / 2) <= 0.5 for m, s in zip(mixed, values(left), strict=True))
    assert pcm.to_int16_mono(interleave(left, right), 2, channel=0) == left


def test_pick_a_channel_of_four() -> None:
    data = int16(1, 2, 3, 4, 5, 6, 7, 8)
    assert values(pcm.to_int16_mono(data, 4, channel=3)) == [4, 8]


def test_a_partial_frame_is_dropped() -> None:
    assert values(pcm.to_int16_mono(int16(1, 2, 3, 4, 5), 2, channel=0)) == [1, 3]


def test_16_bit_passes_through() -> None:
    data = int16(1, -2, 3)
    assert pcm.to_int16(data, 2) == data


def test_8_bit_unsigned() -> None:
    assert values(pcm.to_int16(bytes([0, 64, 128, 255]), 1)) == [-32768, -16384, 0, 32512]


def test_24_bit() -> None:
    samples = [0x123456, -1, 0x7FFFFF, -0x800000, 0]
    data = b"".join(s.to_bytes(3, "little", signed=True) for s in samples)
    assert values(pcm.to_int16(data + b"\x01\x02", 3)) == [0x1234, -1, 32767, -32768, 0]


def test_32_bit() -> None:
    data = struct.pack("<5i", 0x12345678, -65536, 2**31 - 1, -(2**31), 0xFFFF)
    assert values(pcm.to_int16(data + b"\x01", 4)) == [0x1234, -1, 32767, -32768, 0]


def test_stereo_32_bit_to_mono_16_bit() -> None:
    frames = [(1000 << 16, 3000 << 16), (-(2000 << 16), -(4000 << 16)), (-(2**31), 2**31 - 1)]
    data = struct.pack("<6i", *(sample for frame in frames for sample in frame))
    assert values(pcm.to_int16_mono(pcm.to_int16(data, 4), 2)) == [2000, -3000, 0]


def test_unsupported_sample_width() -> None:
    with pytest.raises(ValueError, match="unsupported sample width: 5"):
        pcm.to_int16(bytes(10), 5)


# ---------------------------------------------------------------------------
# Gain and level


@pytest.mark.parametrize(
    ("gain", "expected"),
    [
        (1.0, [100, -200, 20000, -20000]),
        (2.0, [200, -400, 32767, -32768]),  # clipped, not wrapped around
        (0.5, [50, -100, 10000, -10000]),
        (0.0, [0, 0, 0, 0]),
    ],
)
def test_apply_gain(gain: float, expected: list[int]) -> None:
    assert values(pcm.apply_gain(int16(100, -200, 20000, -20000), gain)) == expected


def test_apply_gain_to_nothing() -> None:
    assert pcm.apply_gain(b"", 2.0) == b""


@pytest.mark.parametrize(
    ("db", "gain"),
    [(0, 1.0), (20, 10.0), (-20, 0.1), (-40, 0.01), (6.0206, 2.0)],
)
def test_db_to_gain(db: float, gain: float) -> None:
    assert pcm.db_to_gain(db) == pytest.approx(gain, rel=1e-4)


@pytest.mark.parametrize("data", [b"", b"\x01", bytes(3200)])
def test_silence_has_no_level(data: bytes) -> None:
    assert pcm.rms_dbfs(data) == -math.inf


def test_a_full_scale_square_wave_is_0_dbfs() -> None:
    assert pcm.rms_dbfs(int16(32767, -32768) * 800) == pytest.approx(0.0, abs=0.001)


@pytest.mark.parametrize("amplitude", [1.0, 0.5, 0.1, 0.01])
def test_a_sine_wave_is_3_db_below_its_peak(amplitude: float) -> None:
    expected = 20 * math.log10(amplitude / math.sqrt(2))
    assert pcm.rms_dbfs(tone(0.5, amplitude=amplitude)) == pytest.approx(expected, abs=0.05)


def test_a_trailing_odd_byte_is_ignored() -> None:
    data = tone(0.1)
    assert pcm.rms_dbfs(data + b"\x7f") == pcm.rms_dbfs(data)


def test_gain_changes_the_level_by_as_many_db() -> None:
    data = tone(0.5, amplitude=0.5)
    quieter = pcm.apply_gain(data, pcm.db_to_gain(-12))
    assert pcm.rms_dbfs(quieter) - pcm.rms_dbfs(data) == pytest.approx(-12, abs=0.05)


# ---------------------------------------------------------------------------
# WAV files, silence and duration


@pytest.mark.parametrize(
    ("rate", "width", "channels"),
    [(16000, 2, 1), (22050, 2, 2), (48000, 4, 2), (8000, 1, 1)],
)
def test_wav_round_trip(rate: int, width: int, channels: int) -> None:
    audio = bytes(range(256)) * (width * channels)
    wav = pcm.wav_bytes(audio, rate, width, channels)
    assert pcm.is_wav(wav)
    assert len(wav) == 44 + len(audio)
    assert pcm.read_wav(wav) == (audio, rate, width, channels)


def test_wav_defaults_to_16_bit_mono() -> None:
    audio = tone(0.25)
    assert pcm.read_wav(pcm.wav_bytes(audio, RATE)) == (audio, RATE, 2, 1)


@pytest.mark.parametrize(
    "data",
    [b"", b"RIFF", b"RIFF\x00\x00\x00\x00WAV", b"RIFF\x24\x00\x00\x00AVI LIST", tone(0.01)],
)
def test_is_wav_rejects_other_data(data: bytes) -> None:
    assert not pcm.is_wav(data)


def test_is_wav_only_needs_the_header() -> None:
    assert pcm.is_wav(b"RIFF\x00\x00\x00\x00WAVE")


@pytest.mark.parametrize(
    ("seconds", "rate", "channels", "size"),
    [(0.5, 16000, 1, 16000), (1.0, 48000, 2, 192000), (0.0, 16000, 1, 0), (0.01, 22050, 1, 440)],
)
def test_silence(seconds: float, rate: int, channels: int, size: int) -> None:
    data = pcm.silence(seconds, rate, channels)
    assert data == bytes(size)


@pytest.mark.parametrize(
    ("data", "rate", "width", "channels", "seconds"),
    [
        (pcm.silence(1.5, 16000), 16000, 2, 1, 1.5),
        (tone(0.25), RATE, 2, 1, 0.25),
        (bytes(48000 * 4 * 2), 48000, 4, 2, 1.0),
        (b"", 16000, 2, 1, 0.0),
    ],
)
def test_duration(data: bytes, rate: int, width: int, channels: int, seconds: float) -> None:
    assert pcm.duration(data, rate, width, channels) == pytest.approx(seconds)
