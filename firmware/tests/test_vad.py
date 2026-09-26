"""End-of-speech detection: speech detectors and the voice command segmenter."""

from __future__ import annotations

import math
import struct
from typing import Any

import pytest
from conftest import chunked, silence, tone

from open_speaker.config import VadConfig
from open_speaker.vad import (
    EnergySpeechDetector,
    MicroVadSpeechDetector,
    Segment,
    SpeechDetector,
    VoiceCommandSegmenter,
    create_speech_detector,
)


def level(dbfs: float) -> float:
    """The amplitude of a sine wave at ``dbfs``."""
    return 10 ** (dbfs / 20) * math.sqrt(2)


def classify(detector: SpeechDetector, audio: bytes) -> list[bool]:
    size = detector.frame_bytes
    return [detector.is_speech(audio[i : i + size]) for i in range(0, len(audio) - size + 1, size)]


class Loud(SpeechDetector):
    """Speech is any frame with a sample above 1000. Frames of 1/32 s keep times exact."""

    frame_seconds = 1 / 32  # 500 samples

    def __init__(self) -> None:
        self.frames = 0
        self.resets = 0

    def is_speech(self, frame: bytes) -> bool:
        self.frames += 1
        return max(abs(s) for s in struct.unpack(f"<{len(frame) // 2}h", frame)) > 1000

    def reset(self) -> None:
        self.resets += 1


def speech(frames: int) -> bytes:
    return tone(frames / 32)


def quiet(frames: int) -> bytes:
    return silence(frames / 32)


def segmenter(**options: Any) -> VoiceCommandSegmenter:
    """Timeout after 32 frames, speech after 8, end after 16 quiet, at most 96 frames."""
    settings = {
        "speech_start_timeout": 1.0,
        "min_speech_seconds": 0.25,
        "silence_seconds": 0.5,
        "max_seconds": 3.0,
        **options,
    }
    return VoiceCommandSegmenter(Loud(), **settings)


# ---------------------------------------------------------------------------
# Voice command segmenter


def test_waiting_for_speech() -> None:
    seg = segmenter()
    assert seg.state is Segment.WAITING
    assert seg.process(quiet(31)) is Segment.WAITING
    assert not seg.speech_started
    assert seg.elapsed == 31 / 32


def test_timeout_when_nobody_speaks() -> None:
    seg = segmenter()
    assert seg.process(quiet(31)) is Segment.WAITING
    assert seg.process(quiet(1)) is Segment.TIMEOUT
    assert seg.state.finished
    assert not seg.speech_started
    assert seg.elapsed == 1.0


def test_speech_starts_after_min_speech_seconds() -> None:
    seg = segmenter()
    assert seg.process(quiet(4) + speech(7)) is Segment.WAITING
    assert seg.process(speech(1)) is Segment.SPEAKING
    assert seg.speech_started
    assert not seg.state.finished


def test_short_sounds_are_not_speech() -> None:
    seg = segmenter()
    blip = speech(7) + quiet(1)
    assert seg.process(blip * 3) is Segment.WAITING
    assert seg.process(blip) is Segment.TIMEOUT


def test_speech_must_be_under_way_before_the_timeout() -> None:
    assert segmenter().process(quiet(25) + speech(7)) is Segment.TIMEOUT
    assert segmenter().process(quiet(24) + speech(8)) is Segment.SPEAKING


def test_the_command_ends_after_enough_silence() -> None:
    seg = segmenter()
    assert seg.process(quiet(2) + speech(10) + quiet(15)) is Segment.SPEAKING
    assert seg.process(quiet(1)) is Segment.ENDED
    assert seg.state.finished
    assert seg.speech_started
    assert seg.elapsed == 28 / 32


def test_a_short_pause_does_not_end_the_command() -> None:
    seg = segmenter()
    assert seg.process(speech(10) + quiet(15) + speech(1) + quiet(15)) is Segment.SPEAKING
    assert seg.process(quiet(1)) is Segment.ENDED


def test_a_command_that_goes_on_too_long() -> None:
    seg = segmenter()
    assert seg.process(speech(95)) is Segment.SPEAKING
    assert seg.process(speech(1)) is Segment.MAX_LENGTH
    assert seg.speech_started
    assert seg.elapsed == 3.0


def test_max_seconds_without_speech_is_a_timeout() -> None:
    seg = segmenter(speech_start_timeout=10.0)
    assert seg.process(quiet(95)) is Segment.WAITING
    assert seg.process(quiet(1)) is Segment.TIMEOUT
    assert not seg.speech_started


def test_a_finished_command_ignores_more_audio() -> None:
    seg = segmenter()
    assert seg.process(speech(10) + quiet(16) + speech(5)) is Segment.ENDED
    assert isinstance(seg.detector, Loud)
    assert seg.detector.frames == 26  # nothing after the end was looked at
    assert seg.process(speech(40)) is Segment.ENDED
    assert seg.detector.frames == 26
    assert seg.elapsed == 26 / 32


@pytest.mark.parametrize("size", [1, 333, 1000, 4096])
def test_chunk_size_does_not_matter(size: int) -> None:
    audio = quiet(3) + speech(12) + quiet(20)
    whole = segmenter()
    whole.process(audio)
    seg = segmenter()
    states = [seg.process(chunk) for chunk in chunked(audio, size)]
    assert Segment.SPEAKING in states
    assert states[-1] is Segment.ENDED
    assert (seg.state, seg.elapsed) == (whole.state, whole.elapsed) == (Segment.ENDED, 31 / 32)


def test_a_partial_frame_waits_for_the_rest() -> None:
    seg = segmenter()
    frame = quiet(1)
    seg.process(frame[:600])
    assert seg.elapsed == 0
    seg.process(frame[600:])
    assert seg.elapsed == 1 / 32


def test_reset_starts_a_new_command() -> None:
    seg = segmenter()
    assert isinstance(seg.detector, Loud)
    assert seg.process(speech(10) + quiet(16)) is Segment.ENDED
    seg.reset()
    assert (seg.state, seg.elapsed, seg.speech_started) == (Segment.WAITING, 0.0, False)
    assert seg.detector.resets == 2  # once when created
    seg.process(quiet(1)[:600])
    seg.reset()
    seg.process(quiet(1)[:500])  # the half frame from before the reset is gone
    assert seg.elapsed == 0
    assert seg.process(quiet(1)[500:] + speech(8)) is Segment.SPEAKING


def test_from_config() -> None:
    config = VadConfig(
        speech_start_timeout=2.0,
        min_speech_seconds=0.5,
        silence_seconds=1.0,
        max_seconds=10.0,
        energy_margin_db=6.0,
        energy_min_dbfs=-50.0,
    )
    seg = VoiceCommandSegmenter.from_config(config)
    assert (seg.speech_start_timeout, seg.min_speech_seconds) == (2.0, 0.5)
    assert (seg.silence_seconds, seg.max_seconds) == (1.0, 10.0)
    assert isinstance(seg.detector, EnergySpeechDetector)
    assert (seg.detector.margin_db, seg.detector.min_dbfs) == (6.0, -50.0)
    detector = Loud()
    assert VoiceCommandSegmenter.from_config(config, detector).detector is detector


@pytest.mark.parametrize(
    ("segment", "finished"),
    [
        (Segment.WAITING, False),
        (Segment.SPEAKING, False),
        (Segment.ENDED, True),
        (Segment.TIMEOUT, True),
        (Segment.MAX_LENGTH, True),
    ],
)
def test_finished_states(segment: Segment, finished: bool) -> None:
    assert segment.finished is finished


# ---------------------------------------------------------------------------
# With the energy detector (the default)


def run(seg: VoiceCommandSegmenter, audio: bytes) -> list[Segment]:
    return [seg.process(chunk) for chunk in chunked(audio, 1024)]


def test_a_spoken_command() -> None:
    seg = VoiceCommandSegmenter.from_config(VadConfig())
    states = run(seg, silence(0.5) + tone(1.0) + silence(1.5))
    assert states[0] is Segment.WAITING
    assert Segment.SPEAKING in states
    assert states[-1] is Segment.ENDED
    assert seg.elapsed == pytest.approx(0.5 + 1.0 + 0.8, abs=0.03)


def test_nobody_speaks() -> None:
    seg = VoiceCommandSegmenter.from_config(VadConfig())
    assert run(seg, silence(6.0))[-1] is Segment.TIMEOUT
    assert seg.elapsed == pytest.approx(5.0, abs=0.03)


def test_nobody_stops_speaking() -> None:
    seg = VoiceCommandSegmenter.from_config(VadConfig())
    assert run(seg, silence(0.3) + tone(16.0))[-1] is Segment.MAX_LENGTH
    assert seg.elapsed == pytest.approx(15.0, abs=0.03)


# ---------------------------------------------------------------------------
# Speech detectors


def test_create_speech_detector() -> None:
    detector = create_speech_detector(VadConfig(energy_margin_db=12.0, energy_min_dbfs=-60.0))
    assert isinstance(detector, EnergySpeechDetector)
    assert (detector.margin_db, detector.min_dbfs) == (12.0, -60.0)
    assert detector.frame_bytes == 960  # 30 ms


def test_silence_is_not_speech() -> None:
    assert classify(EnergySpeechDetector(), silence(0.3)) == [False] * 10


def test_a_voice_after_silence_is_speech() -> None:
    assert classify(EnergySpeechDetector(), silence(0.3) + tone(0.3)) == [False] * 10 + [True] * 10


def test_a_steady_sound_from_the_start_is_background_noise() -> None:
    assert not any(classify(EnergySpeechDetector(), tone(1.0)))


def test_speech_has_to_stand_out_from_the_noise() -> None:
    detector = EnergySpeechDetector(margin_db=10.0)
    assert not any(classify(detector, tone(0.3, amplitude=level(-40))))  # a hum
    assert not any(classify(detector, tone(0.3, amplitude=level(-35))))
    assert all(classify(detector, tone(0.3, amplitude=level(-20))))


def test_speech_has_to_be_loud_enough() -> None:
    detector = EnergySpeechDetector(min_dbfs=-55.0)
    assert not any(classify(detector, silence(0.3) + tone(0.3, amplitude=level(-65))))
    assert all(classify(detector, tone(0.3, amplitude=level(-45))))


def test_the_noise_floor_drops_quickly_when_the_room_goes_quiet() -> None:
    detector = EnergySpeechDetector()
    audio = tone(0.3, amplitude=level(-30)) + silence(0.3) + tone(0.3, amplitude=level(-35))
    assert classify(detector, audio)[-10:] == [True] * 10


def test_long_speech_does_not_become_the_noise_floor() -> None:
    assert all(classify(EnergySpeechDetector(), silence(0.3) + tone(3.0))[10:])


def test_reset_forgets_the_noise_floor() -> None:
    detector = EnergySpeechDetector()
    classify(detector, silence(0.3))
    detector.reset()
    assert detector.noise_floor is None
    assert not any(classify(detector, tone(0.3)))  # the first frame sets the floor again


class FakeMicroVad:
    def __init__(self, probabilities: list[float]) -> None:
        self.probabilities = list(probabilities)
        self.frames: list[bytes] = []
        self.resets = 0

    def process_10ms(self, frame: bytes) -> float:
        self.frames.append(frame)
        return self.probabilities.pop(0)

    def reset(self) -> None:
        self.resets += 1


def test_microvad_keeps_its_last_estimate() -> None:
    vad = FakeMicroVad([0.9, -1.0, 0.2, -1.0, 0.5])
    detector = MicroVadSpeechDetector(threshold=0.5, vad=vad)
    assert detector.frame_bytes == 320  # 10 ms
    frame = tone(0.01)
    assert [detector.is_speech(frame) for _ in range(5)] == [True, True, False, False, True]
    assert vad.frames == [frame] * 5


def test_microvad_reset() -> None:
    vad = FakeMicroVad([0.9, -1.0])
    detector = MicroVadSpeechDetector(vad=vad)
    assert detector.is_speech(bytes(320))
    detector.reset()
    assert vad.resets == 1
    assert not detector.is_speech(bytes(320))  # no estimate since the reset
