"""Text-to-speech engines for the local pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod

import aiohttp

from ..audio.playback import AudioSource
from ..config import TtsConfig


class TtsError(RuntimeError):
    pass


class TextToSpeech(ABC):
    @abstractmethod
    async def synthesize(self, text: str, language: str | None) -> AudioSource:
        """Return audio for ``text``; a PCM stream may still be arriving."""


def create_tts(config: TtsConfig, session: aiohttp.ClientSession) -> TextToSpeech:
    if config.engine == "wyoming":
        from .wyoming import WyomingTts

        assert config.uri is not None
        return WyomingTts(
            config.uri, voice=config.voice, speaker=config.speaker, timeout=config.timeout
        )
    from .openai_compat import OpenAiTts

    assert config.url is not None
    return OpenAiTts(
        session,
        config.url,
        model=config.model,
        voice=config.voice,
        api_key=config.api_key,
        speed=config.speed,
        response_format=config.response_format,
        timeout=config.timeout,
    )


__all__ = ["TextToSpeech", "TtsError", "create_tts"]
