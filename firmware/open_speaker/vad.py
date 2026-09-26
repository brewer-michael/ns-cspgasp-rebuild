"""Detecting when a spoken command starts and ends (used by the local pipeline).

Home Assistant pipelines do their own end-of-speech detection; the local pipeline
needs to decide on the speaker when to stop recording and send the audio to
speech-to-text.
"""

from __future__ import annotations

import enum
import math
from abc import ABC, abstractmethod
from typing import Any

from .audio.pcm import rms_dbfs
from .config import VadConfig
from .const import SAMPLE_RATE, SAMPLE_WIDTH


class SpeechDetector(ABC):
    """Classifies fixed-size frames of 16 kHz mono audio as speech or not."""

    frame_seconds: float

    @property
    def frame_bytes(self) -> int:
        return int(self.frame_seconds * SAMPLE_RATE) * SAMPLE_WIDTH

    @abstractmethod
    def is_speech(self, frame: bytes) -> bool: ...

    def reset(self) -> None:  # noqa: B027 - optional hook
        pass


class EnergySpeechDetector(SpeechDetector):
    """Loudness relative to an adaptive noise floor. No dependencies, no training."""

    frame_seconds = 0.03

    def __init__(self, margin_db: float = 10.0, min_dbfs: float = -55.0) -> None:
        self.margin_db = margin_db
        self.min_dbfs = min_dbfs
        self.noise_floor: float | None = None

    def is_speech(self, frame: bytes) -> bool:
        level = rms_dbfs(frame)
        if not math.isfinite(level):
            level = -120.0
        if self.noise_floor is None:
            self.noise_floor = level
        speech = level > max(self.noise_floor + self.margin_db, self.min_dbfs)
        # Follow the floor down quickly and up slowly (not at all during speech).
        if level < self.noise_floor:
            self.noise_floor = 0.7 * self.noise_floor + 0.3 * level
        elif not speech:
            self.noise_floor = 0.97 * self.noise_floor + 0.03 * level
        return speech

    def reset(self) -> None:
        self.noise_floor = None


class MicroVadSpeechDetector(SpeechDetector):
    """The small neural VAD from the microWakeWord project (``pymicro-vad``)."""

    frame_seconds = 0.01

    def __init__(self, threshold: float = 0.5, vad: Any = None) -> None:
        if vad is None:
            from pymicro_vad import MicroVad

            vad = MicroVad()
        self.vad = vad
        self.threshold = threshold
        self._probability = 0.0

    def is_speech(self, frame: bytes) -> bool:
        probability = self.vad.process_10ms(frame)
        if probability >= 0:  # negative means "no new estimate yet"
            self._probability = probability
        return self._probability >= self.threshold

    def reset(self) -> None:
        self.vad.reset()
        self._probability = 0.0


def create_speech_detector(config: VadConfig) -> SpeechDetector:
    if config.engine == "microvad":
        return MicroVadSpeechDetector(config.threshold)
    return EnergySpeechDetector(config.energy_margin_db, config.energy_min_dbfs)


class Segment(enum.Enum):
    WAITING = "waiting"  # no speech yet
    SPEAKING = "speaking"  # speech in progress
    ENDED = "ended"  # speech followed by enough silence
    TIMEOUT = "timeout"  # nobody spoke
    MAX_LENGTH = "max_length"  # command too long; stop recording anyway

    @property
    def finished(self) -> bool:
        return self in (Segment.ENDED, Segment.TIMEOUT, Segment.MAX_LENGTH)


class VoiceCommandSegmenter:
    """Tracks one voice command from wake word to end of speech.

    Time is measured in audio samples, not wall-clock time, so behaviour is exact and
    testable.
    """

    def __init__(
        self,
        detector: SpeechDetector,
        speech_start_timeout: float = 5.0,
        min_speech_seconds: float = 0.25,
        silence_seconds: float = 0.8,
        max_seconds: float = 15.0,
    ) -> None:
        self.detector = detector
        self.speech_start_timeout = speech_start_timeout
        self.min_speech_seconds = min_speech_seconds
        self.silence_seconds = silence_seconds
        self.max_seconds = max_seconds
        self.reset()

    @classmethod
    def from_config(cls, config: VadConfig, detector: SpeechDetector | None = None):
        return cls(
            detector or create_speech_detector(config),
            speech_start_timeout=config.speech_start_timeout,
            min_speech_seconds=config.min_speech_seconds,
            silence_seconds=config.silence_seconds,
            max_seconds=config.max_seconds,
        )

    def reset(self) -> None:
        self.detector.reset()
        self.state = Segment.WAITING
        self.elapsed = 0.0
        self._buffer = b""
        self._speech_run = 0.0
        self._silence_run = 0.0

    @property
    def speech_started(self) -> bool:
        return self.state in (Segment.SPEAKING, Segment.ENDED, Segment.MAX_LENGTH)

    def process(self, chunk: bytes) -> Segment:
        if self.state.finished:
            return self.state
        self._buffer += chunk
        frame_bytes = self.detector.frame_bytes
        frame_seconds = frame_bytes / (SAMPLE_RATE * SAMPLE_WIDTH)
        while len(self._buffer) >= frame_bytes and not self.state.finished:
            frame, self._buffer = self._buffer[:frame_bytes], self._buffer[frame_bytes:]
            self.elapsed += frame_seconds
            self._step(self.detector.is_speech(frame), frame_seconds)
        return self.state

    def _step(self, speech: bool, seconds: float) -> None:
        if self.state is Segment.WAITING:
            self._speech_run = self._speech_run + seconds if speech else 0.0
            if self._speech_run >= self.min_speech_seconds:
                self.state = Segment.SPEAKING
                self._silence_run = 0.0
            elif self.elapsed >= self.speech_start_timeout:
                self.state = Segment.TIMEOUT
        elif self.state is Segment.SPEAKING:
            self._silence_run = 0.0 if speech else self._silence_run + seconds
            if self._silence_run >= self.silence_seconds:
                self.state = Segment.ENDED
        if not self.state.finished and self.elapsed >= self.max_seconds:
            self.state = Segment.MAX_LENGTH if self.speech_started else Segment.TIMEOUT
