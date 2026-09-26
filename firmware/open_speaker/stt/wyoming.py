"""Speech-to-text on a Wyoming server (faster-whisper, whisper.cpp, Vosk, ...)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterable

from wyoming.asr import Transcribe, Transcript, TranscriptChunk, TranscriptStop
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.client import AsyncClient
from wyoming.error import Error

from ..const import SAMPLE_CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from . import SpeechToText, SttError


class WyomingStt(SpeechToText):
    """Streams audio while you speak, so transcription starts as soon as you stop."""

    def __init__(self, uri: str, model: str | None = None, timeout: float = 30.0) -> None:
        self.uri = uri
        self.model = model
        self.timeout = timeout

    async def transcribe(self, audio: AsyncIterable[bytes], language: str | None) -> str:
        client = AsyncClient.from_uri(self.uri, connect_timeout=self.timeout)
        try:
            await client.connect()
        except (OSError, TimeoutError) as err:
            raise SttError(f"cannot reach speech-to-text server {self.uri}: {err}") from err

        try:
            await client.write_event(Transcribe(name=self.model, language=language).event())
            await client.write_event(
                AudioStart(rate=SAMPLE_RATE, width=SAMPLE_WIDTH, channels=SAMPLE_CHANNELS).event()
            )
            async for chunk in audio:
                await client.write_event(
                    AudioChunk(
                        rate=SAMPLE_RATE,
                        width=SAMPLE_WIDTH,
                        channels=SAMPLE_CHANNELS,
                        audio=chunk,
                    ).event()
                )
            await client.write_event(AudioStop().event())
            return await asyncio.wait_for(self._read_transcript(client), self.timeout)
        except TimeoutError as err:
            raise SttError(f"speech-to-text server {self.uri} timed out") from err
        except (OSError, asyncio.IncompleteReadError) as err:
            raise SttError(f"speech-to-text server {self.uri} failed: {err}") from err
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()

    @staticmethod
    async def _read_transcript(client: AsyncClient) -> str:
        streamed: list[str] = []
        while True:
            event = await client.read_event()
            if event is None:
                if streamed:
                    return "".join(streamed).strip()
                raise SttError("speech-to-text server closed the connection")
            if Transcript.is_type(event.type):
                return Transcript.from_event(event).text.strip()
            if TranscriptChunk.is_type(event.type):
                streamed.append(TranscriptChunk.from_event(event).text)
            elif TranscriptStop.is_type(event.type) and streamed:
                # Servers normally follow with a final transcript; keep waiting for it
                # but fall back to the streamed text if the connection closes.
                continue
            elif Error.is_type(event.type):
                raise SttError(f"speech-to-text error: {Error.from_event(event).text}")
