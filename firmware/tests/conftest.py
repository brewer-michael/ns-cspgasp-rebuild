"""Shared test helpers: fake audio devices, fake servers and config builders."""

from __future__ import annotations

import asyncio
import contextlib
import math
import struct
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from wyoming.event import Event, async_read_event, async_write_event

from open_speaker.audio.playback import AudioSource, EncodedAudio, PcmFormat, PcmStream
from open_speaker.config import Config, config_from_dict
from open_speaker.pipeline import Conversation, Pipeline, PipelineFailure, Reply

RATE = 16000


def tone(seconds: float, freq: float = 440.0, amplitude: float = 0.3, rate: int = RATE) -> bytes:
    count = int(seconds * rate)
    return struct.pack(
        f"<{count}h",
        *(int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(count)),
    )


def silence(seconds: float, rate: int = RATE) -> bytes:
    return bytes(int(seconds * rate) * 2)


def chunked(data: bytes, size: int = 1024) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def make_config(tmp_path: Path, **overrides: Any) -> Config:
    """A config that needs no hardware, with state kept in ``tmp_path``."""
    data: dict[str, Any] = {
        "state_dir": str(tmp_path / "state"),
        "homeassistant": {"url": "http://ha.test:8123", "token": "secret"},
        "audio": {"output": {"volume_control": None}},
        "display": {"type": "none"},
        "status_leds": {"type": "none"},
        "volume_led": {"pin": None},
        "api": {"enabled": False},
        "wake": {"engine": "none"},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return config_from_dict(data)


# ---------------------------------------------------------------------------
# Fake audio devices


class FakeMic:
    """Feeds chunks pushed with :meth:`feed` to the speaker's microphone loop."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.paused = False
        self.closed = False

    def feed(self, *chunks: bytes) -> None:
        for chunk in chunks:
            self.queue.put_nowait(chunk)

    async def chunks(self) -> AsyncIterator[bytes]:
        while not self.closed:
            chunk = await self.queue.get()
            if not self.paused:
                yield chunk

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    async def close(self) -> None:
        self.closed = True


class FakePlayer:
    """Records what would have been played."""

    def __init__(self, delay: float = 0.0) -> None:
        self.played: list[tuple[str, Any]] = []
        self.software_gain = 1.0
        self.delay = delay
        self._playing = 0
        self.stopped = 0

    @property
    def is_playing(self) -> bool:
        return self._playing > 0

    def stop(self) -> None:
        self.stopped += 1

    async def _play(self, kind: str, value: Any) -> bool:
        self._playing += 1
        try:
            self.played.append((kind, value))
            await asyncio.sleep(self.delay)
            return True
        finally:
            self._playing -= 1

    async def play_pcm(self, pcm: bytes, fmt: PcmFormat, gain: float = 1.0) -> bool:
        return await self._play("pcm", len(pcm))

    async def play_stream(self, fmt: PcmFormat, chunks: Any, gain: float = 1.0) -> bool:
        data = b"".join([c async for c in chunks])
        return await self._play("stream", data)

    async def play(self, source: AudioSource, gain: float = 1.0) -> bool:
        if isinstance(source, PcmStream):
            return await self.play_stream(source.format, source.chunks, gain)
        return await self._play("audio", source.data)

    async def play_encoded(self, data: bytes, gain: float = 1.0) -> bool:
        return await self._play("audio", data)

    @property
    def audio(self) -> list[bytes]:
        return [value for kind, value in self.played if kind == "audio"]


class FakePipeline(Pipeline):
    """Scripted pipeline: each listen() consumes audio and returns the next transcript."""

    def __init__(self, transcripts: list[str | None], replies: dict[str, Reply] | None = None):
        self.transcripts = list(transcripts)
        self.replies = replies or {}
        self.heard_audio: list[int] = []
        self.responded: list[str] = []
        self.spoken: list[str] = []
        self.fail_speak = False

    async def listen(self, audio: AsyncIterator[bytes], conversation: Conversation) -> str | None:
        total = 0
        async for chunk in audio:
            total += len(chunk)
            if total >= 3200:
                break
        self.heard_audio.append(total)
        return self.transcripts.pop(0) if self.transcripts else None

    async def respond(self, text: str, conversation: Conversation) -> Reply:
        self.responded.append(text)
        conversation.id = conversation.id or "conv-1"
        return self.replies.get(text, Reply(f"reply to {text}", EncodedAudio(b"REPLY")))

    async def speak(self, text: str, language: str) -> AudioSource | None:
        if self.fail_speak:
            raise PipelineFailure("tts down")
        self.spoken.append(text)
        return EncodedAudio(f"TTS:{text}".encode())


async def wait_for(condition: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------
# Fake Wyoming server


@contextlib.asynccontextmanager
async def wyoming_server(
    handler: Callable[[Callable[[], Awaitable[Event | None]], Callable[[Event], Awaitable[None]]],
                      Awaitable[None]],
) -> AsyncIterator[str]:  # fmt: skip
    """Run ``handler(read, write)`` for each connection; yields the server's URI."""

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def read() -> Event | None:
            return await async_read_event(reader)

        async def write(event: Event) -> None:
            await async_write_event(event, writer)

        try:
            await handler(read, write)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"tcp://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return make_config(tmp_path)
