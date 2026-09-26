"""Speech-to-text engines for the local pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable

import aiohttp

from ..config import SttConfig


class SttError(RuntimeError):
    pass


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio: AsyncIterable[bytes], language: str | None) -> str:
        """Transcribe 16 kHz, 16-bit mono PCM chunks (the iterator ends with the speech)."""


def create_stt(config: SttConfig, session: aiohttp.ClientSession) -> SpeechToText:
    if config.engine == "wyoming":
        from .wyoming import WyomingStt

        assert config.uri is not None
        return WyomingStt(config.uri, model=config.model, timeout=config.timeout)
    from .openai_compat import OpenAiStt

    assert config.url is not None
    return OpenAiStt(
        session,
        config.url,
        model=config.model,
        api_key=config.api_key,
        timeout=config.timeout,
    )


__all__ = ["SpeechToText", "SttError", "create_stt"]
