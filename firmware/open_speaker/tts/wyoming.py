"""Text-to-speech on a Wyoming server (Piper, Kokoro, ...)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient
from wyoming.error import Error
from wyoming.tts import Synthesize, SynthesizeVoice

from ..audio.playback import PcmFormat, PcmStream
from . import TextToSpeech, TtsError


class WyomingTts(TextToSpeech):
    """Returns a live PCM stream so playback starts before synthesis finishes."""

    def __init__(
        self,
        uri: str,
        voice: str | None = None,
        speaker: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.uri = uri
        self.voice = voice
        self.speaker = speaker
        self.timeout = timeout

    def _voice(self, language: str | None) -> SynthesizeVoice | None:
        if self.voice:
            return SynthesizeVoice(name=self.voice, speaker=self.speaker)
        if language:
            return SynthesizeVoice(language=language)
        return None

    async def synthesize(self, text: str, language: str | None) -> PcmStream:
        client = AsyncClient.from_uri(self.uri, connect_timeout=self.timeout)
        try:
            await client.connect()
            await client.write_event(Synthesize(text=text, voice=self._voice(language)).event())
            start = await asyncio.wait_for(self._first_audio(client), self.timeout)
        except BaseException as err:
            with contextlib.suppress(Exception):
                await client.disconnect()
            if isinstance(err, TtsError):
                raise
            if isinstance(err, (OSError, TimeoutError, asyncio.IncompleteReadError)):
                raise TtsError(f"text-to-speech server {self.uri} failed: {err}") from err
            raise
        fmt = PcmFormat(rate=start.rate, width=start.width, channels=start.channels)
        return PcmStream(fmt, self._chunks(client))

    @staticmethod
    async def _first_audio(client: AsyncClient) -> AudioStart:
        while True:
            event = await client.read_event()
            if event is None:
                raise TtsError("text-to-speech server closed the connection")
            if AudioStart.is_type(event.type):
                return AudioStart.from_event(event)
            if Error.is_type(event.type):
                raise TtsError(f"text-to-speech error: {Error.from_event(event).text}")

    async def _chunks(self, client: AsyncClient) -> AsyncIterator[bytes]:
        try:
            while True:
                event = await asyncio.wait_for(client.read_event(), self.timeout)
                if event is None or AudioStop.is_type(event.type):
                    break
                if AudioChunk.is_type(event.type):
                    yield AudioChunk.from_event(event).audio
                elif Error.is_type(event.type):
                    raise TtsError(f"text-to-speech error: {Error.from_event(event).text}")
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()
