"""Wyoming clients: wake word detection, speech-to-text and text-to-speech."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import socket
import struct
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from conftest import chunked, tone, wait_for, wyoming_server
from wyoming.asr import Transcribe, Transcript, TranscriptChunk, TranscriptStart, TranscriptStop
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event, async_read_event
from wyoming.tts import Synthesize
from wyoming.wake import Detect, Detection

from open_speaker.audio.playback import PcmFormat, PcmStream
from open_speaker.stt import SttError
from open_speaker.stt.wyoming import WyomingStt
from open_speaker.tts import TtsError
from open_speaker.tts.wyoming import WyomingTts
from open_speaker.wake import wyoming as wake_wyoming
from open_speaker.wake.wyoming import WyomingWakeEngine

Read = Callable[[], Awaitable[Event | None]]
Write = Callable[[Event], Awaitable[None]]

CHUNK = 1024  # 512 samples: one microphone read
TTS_RATE = 22050


def closed_uri() -> str:
    """A tcp:// URI that refuses connections."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"tcp://127.0.0.1:{port}"


@contextlib.asynccontextmanager
async def crashing_server(events: int) -> AsyncIterator[str]:
    """Reads ``events`` events, then resets the connection like a server that crashed."""

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        for _ in range(events):
            await async_read_event(reader)
        sock = writer.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        writer.close()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    try:
        yield f"tcp://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    finally:
        server.close()
        await server.wait_closed()


async def read_all(read: Read) -> list[Event]:
    events: list[Event] = []
    while (event := await read()) is not None:
        events.append(event)
    return events


async def audio_stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def collect(chunks: AsyncIterable[bytes]) -> list[bytes]:
    return [chunk async for chunk in chunks]


def audio_of(events: list[Event]) -> bytes:
    assert all(AudioChunk.is_type(event.type) for event in events)
    return b"".join(AudioChunk.from_event(event).audio for event in events)


# ---------------------------------------------------------------------------
# Wake word


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@contextlib.asynccontextmanager
async def running(engine: WyomingWakeEngine) -> AsyncIterator[WyomingWakeEngine]:
    await engine.start()
    try:
        yield engine
    finally:
        await engine.stop()


async def detect(engine: WyomingWakeEngine, timeout: float = 2.0) -> str:
    """Feeds silence until the engine reports a wake word."""

    async def feed() -> str:
        while (name := await engine.process(bytes(CHUNK))) is None:
            await asyncio.sleep(0.005)
        return name

    return await asyncio.wait_for(feed(), timeout)


async def test_wake_streams_microphone_audio() -> None:
    received: list[Event] = []

    async def handler(read: Read, write: Write) -> None:
        while (event := await read()) is not None:
            received.append(event)

    audio = chunked(tone(0.25), CHUNK)
    async with wyoming_server(handler) as uri:
        engine = WyomingWakeEngine(uri, ["okay_nabu"])
        assert not engine.connected
        async with running(engine):
            await wait_for(lambda: engine.connected)
            for chunk in audio:
                assert await engine.process(chunk) is None
            await wait_for(lambda: len(received) == 2 + len(audio))

    detect_event, start, *chunks = received
    assert Detect.is_type(detect_event.type)
    assert Detect.from_event(detect_event).names == ["okay_nabu"]
    assert AudioStart.is_type(start.type)
    assert AudioStart.from_event(start) == AudioStart(rate=16000, width=2, channels=1)
    assert audio_of(chunks) == b"".join(audio)
    formats = {(e.data["rate"], e.data["width"], e.data["channels"]) for e in chunks}
    assert formats == {(16000, 2, 1)}


async def test_wake_reports_each_detection_once() -> None:
    async def handler(read: Read, write: Write) -> None:
        detected = False
        while (event := await read()) is not None:
            if AudioChunk.is_type(event.type) and not detected:
                await write(Detection(name="hey_jarvis", timestamp=120).event())
                detected = True

    async with (
        wyoming_server(handler) as uri,
        running(WyomingWakeEngine(uri, ["hey_jarvis"])) as engine,
    ):
        await wait_for(lambda: engine.connected)
        assert await detect(engine) == "hey_jarvis"
        for _ in range(5):
            assert await engine.process(bytes(CHUNK)) is None
            await asyncio.sleep(0.01)
        assert engine.connected


@pytest.mark.parametrize(
    ("names", "requested", "expected"),
    [
        (["okay_nabu", "hey_jarvis"], ["okay_nabu", "hey_jarvis"], "okay_nabu, hey_jarvis"),
        ([], None, "wake word"),
        (None, None, "wake word"),
    ],
)
async def test_wake_names_unnamed_detections(
    names: list[str] | None, requested: list[str] | None, expected: str
) -> None:
    received: list[Event] = []

    async def handler(read: Read, write: Write) -> None:
        received.append(await read())
        received.append(await read())
        await write(Detection().event())
        await read_all(read)

    async with wyoming_server(handler) as uri, running(WyomingWakeEngine(uri, names)) as engine:
        assert await detect(engine) == expected

    assert Detect.from_event(received[0]).names == requested


async def test_wake_logs_server_errors_and_keeps_listening(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def handler(read: Read, write: Write) -> None:
        await read()
        await read()
        await write(Error(text="model not loaded", code="no-model").event())
        await write(Detection(name="okay_nabu").event())
        await read_all(read)

    async with wyoming_server(handler) as uri, running(WyomingWakeEngine(uri)) as engine:
        assert await detect(engine) == "okay_nabu"
        assert engine.connected

    assert "Wake word server error: model not loaded" in caplog.text


@pytest.mark.parametrize(("reset", "expected"), [(False, "okay_nabu"), (True, None)])
async def test_wake_detection_received_before_a_disconnect(
    reset: bool, expected: str | None
) -> None:
    connections = 0
    go = asyncio.Event()

    async def handler(read: Read, write: Write) -> None:
        nonlocal connections
        connections += 1
        await read()
        await read()
        if connections == 1:
            await go.wait()
            await write(Detection(name="okay_nabu").event())
            return
        await read_all(read)

    async with wyoming_server(handler) as uri, running(WyomingWakeEngine(uri)) as engine:
        await wait_for(lambda: engine.connected)
        go.set()
        # The reader handles the detection before it sees the connection close.
        await wait_for(lambda: not engine.connected)
        if reset:
            await engine.reset()
        assert await engine.process(bytes(CHUNK)) == expected
        assert await engine.process(bytes(CHUNK)) is None


async def test_wake_reconnects_after_server_drops() -> None:
    sessions: list[list[Event]] = []
    drop = asyncio.Event()

    async def handler(read: Read, write: Write) -> None:
        events: list[Event] = []
        sessions.append(events)
        if len(sessions) == 1:
            events += [await read(), await read()]
            await drop.wait()
            return
        while (event := await read()) is not None:
            events.append(event)

    audio = chunked(tone(0.2), CHUNK)
    async with (
        wyoming_server(handler) as uri,
        running(WyomingWakeEngine(uri, ["okay_nabu"])) as engine,
    ):
        await wait_for(lambda: engine.connected)
        drop.set()
        await wait_for(lambda: not engine.connected)
        # Audio is dropped while disconnected; the next chunk reconnects right away.
        assert await engine.process(tone(0.032, freq=880)) is None
        await wait_for(lambda: engine.connected, timeout=1.0)
        for chunk in audio:
            assert await engine.process(chunk) is None
        await wait_for(lambda: len(sessions) == 2 and len(sessions[1]) == 2 + len(audio))

    detect_event, start, *chunks = sessions[1]
    assert Detect.from_event(detect_event).names == ["okay_nabu"]
    assert AudioStart.is_type(start.type)
    assert audio_of(chunks) == b"".join(audio)


async def test_wake_retries_unreachable_server_with_backoff(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    attempts: list[float] = []
    real_client = wake_wyoming.AsyncClient

    class CountingClient:
        @staticmethod
        def from_uri(uri: str, **kwargs: Any) -> Any:
            attempts.append(clock.now)
            return real_client.from_uri(uri, **kwargs)

    monkeypatch.setattr(wake_wyoming, "time", clock)
    monkeypatch.setattr(wake_wyoming, "AsyncClient", CountingClient)
    caplog.set_level(logging.WARNING, logger=wake_wyoming.__name__)

    def failures() -> int:
        return sum("unavailable" in record.getMessage() for record in caplog.records)

    async def settle() -> None:
        await asyncio.sleep(0)  # a scheduled attempt starts...
        await wait_for(lambda: failures() == len(attempts))  # ...and fails

    engine = WyomingWakeEngine(closed_uri(), connect_timeout=1.0, max_backoff=5.0)
    await engine.start()
    await settle()
    for _ in range(40):  # 20 s of microphone audio, a chunk every half second
        clock.now += 0.5
        assert await asyncio.wait_for(engine.process(bytes(CHUNK)), 0.5) is None
        await settle()
    await engine.stop()

    assert not engine.connected
    assert attempts[0] == 1000.0
    assert [b - a for a, b in itertools.pairwise(attempts)] == [1.0, 2.0, 4.0, 5.0, 5.0]


async def test_wake_backoff_starts_over_after_connecting(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    monkeypatch.setattr(wake_wyoming, "time", clock)
    caplog.set_level(logging.WARNING, logger=wake_wyoming.__name__)
    drop = asyncio.Event()

    async def handler(read: Read, write: Write) -> None:
        await read()
        await read()
        await drop.wait()

    def retry_delays() -> list[str]:
        messages = [record.getMessage() for record in caplog.records]
        return [m.rsplit("retrying in ", 1)[1] for m in messages if "unavailable" in m]

    async def retries(count: int) -> list[str]:
        await wait_for(lambda: len(retry_delays()) == count)
        return retry_delays()

    async with (
        wyoming_server(handler) as uri,
        running(WyomingWakeEngine(closed_uri(), max_backoff=30.0)) as engine,
    ):
        assert await retries(1) == ["1 s"]
        for count in (2, 3):
            clock.now += 10
            assert await engine.process(bytes(CHUNK)) is None
            await retries(count)
        assert retry_delays() == ["1 s", "2 s", "4 s"]

        engine.uri = uri  # the server is back...
        clock.now += 10
        assert await engine.process(bytes(CHUNK)) is None
        await wait_for(lambda: engine.connected)

        engine.uri = closed_uri()  # ...and gone again
        drop.set()
        await wait_for(lambda: not engine.connected)
        assert await engine.process(bytes(CHUNK)) is None
        assert await retries(4) == ["1 s", "2 s", "4 s", "1 s"]


async def test_wake_stop_disconnects_for_good() -> None:
    connections = 0
    hung_up = asyncio.Event()

    async def handler(read: Read, write: Write) -> None:
        nonlocal connections
        connections += 1
        await read_all(read)
        hung_up.set()

    async with wyoming_server(handler) as uri:
        engine = WyomingWakeEngine(uri)
        await engine.start()
        await wait_for(lambda: engine.connected)
        await engine.stop()
        assert not engine.connected
        await asyncio.wait_for(hung_up.wait(), 2)

        assert await engine.process(bytes(CHUNK)) is None
        await asyncio.sleep(0.05)
        assert connections == 1
        assert not engine.connected


# ---------------------------------------------------------------------------
# Speech-to-text


def stt_server(
    *replies: Event, received: list[Event] | None = None, hang: bool = False
) -> Callable[[Read, Write], Awaitable[None]]:
    """Reads a request up to ``audio-stop``, then sends ``replies``."""

    async def handler(read: Read, write: Write) -> None:
        while (event := await read()) is not None:
            if received is not None:
                received.append(event)
            if AudioStop.is_type(event.type):
                break
        for reply in replies:
            await write(reply)
        if hang:
            await read_all(read)

    return handler


async def transcribe(stt: WyomingStt, audio: bytes = b"", language: str | None = "en") -> str:
    chunks = chunked(audio or tone(0.1), CHUNK)
    return await asyncio.wait_for(stt.transcribe(audio_stream(chunks), language), 3)


async def test_stt_streams_audio_and_returns_transcript() -> None:
    received: list[Event] = []
    audio = tone(0.3)
    handler = stt_server(Transcript(text=" Turn on the kitchen light. ").event(), received=received)
    async with wyoming_server(handler) as uri:
        text = await transcribe(WyomingStt(uri, model="small-int8", timeout=2), audio, "en")

    assert text == "Turn on the kitchen light."
    request, start, *chunks, stop = received
    assert Transcribe.is_type(request.type)
    assert Transcribe.from_event(request) == Transcribe(name="small-int8", language="en")
    assert AudioStart.is_type(start.type)
    assert AudioStart.from_event(start) == AudioStart(rate=16000, width=2, channels=1)
    assert audio_of(chunks) == audio
    assert AudioStop.is_type(stop.type)


async def test_stt_request_without_model_or_language() -> None:
    received: list[Event] = []
    handler = stt_server(Transcript(text="hello").event(), received=received)
    async with wyoming_server(handler) as uri:
        assert await transcribe(WyomingStt(uri, timeout=2), language=None) == "hello"

    assert Transcribe.is_type(received[0].type)
    assert received[0].data == {}


async def test_stt_sends_audio_while_it_is_recorded() -> None:
    first_chunk = asyncio.Event()

    async def handler(read: Read, write: Write) -> None:
        while (event := await read()) is not None:
            if AudioChunk.is_type(event.type):
                first_chunk.set()
            elif AudioStop.is_type(event.type):
                await write(Transcript(text="what time is it").event())
                return

    async def microphone() -> AsyncIterator[bytes]:
        yield tone(0.1)
        # The server has the first chunk before the next one is even recorded.
        await asyncio.wait_for(first_chunk.wait(), 2)
        yield tone(0.1, freq=880)

    async with wyoming_server(handler) as uri:
        stt = WyomingStt(uri, timeout=2)
        assert await asyncio.wait_for(stt.transcribe(microphone(), "en"), 3) == "what time is it"


async def test_stt_prefers_final_transcript_of_streamed_response() -> None:
    handler = stt_server(
        TranscriptStart(language="en").event(),
        TranscriptChunk(text="Turn on").event(),
        TranscriptChunk(text=" the lights").event(),
        Transcript(text="Turn on the lights.").event(),
        TranscriptStop().event(),
    )
    async with wyoming_server(handler) as uri:
        assert await transcribe(WyomingStt(uri, timeout=2)) == "Turn on the lights."


async def test_stt_waits_for_final_transcript_after_transcript_stop() -> None:
    handler = stt_server(
        TranscriptStart().event(),
        TranscriptChunk(text="What time").event(),
        TranscriptStop().event(),
        Transcript(text="What time is it?").event(),
    )
    async with wyoming_server(handler) as uri:
        assert await transcribe(WyomingStt(uri, timeout=2)) == "What time is it?"


@pytest.mark.parametrize("stop", [True, False])
async def test_stt_uses_streamed_text_when_server_hangs_up(stop: bool) -> None:
    replies = [
        TranscriptStart().event(),
        TranscriptChunk(text=" Set a timer").event(),
        TranscriptChunk(text=" for five minutes ").event(),
    ]
    if stop:
        replies.append(TranscriptStop().event())
    async with wyoming_server(stt_server(*replies)) as uri:
        assert await transcribe(WyomingStt(uri, timeout=2)) == "Set a timer for five minutes"


async def test_stt_error_event() -> None:
    handler = stt_server(Error(text="model failed to load", code="load-error").event())
    async with wyoming_server(handler) as uri:
        with pytest.raises(SttError, match="speech-to-text error: model failed to load"):
            await transcribe(WyomingStt(uri, timeout=2))


async def test_stt_server_closes_without_transcript() -> None:
    async with wyoming_server(stt_server()) as uri:
        with pytest.raises(SttError, match="closed the connection"):
            await transcribe(WyomingStt(uri, timeout=2))


async def test_stt_timeout() -> None:
    async with wyoming_server(stt_server(hang=True)) as uri:
        with pytest.raises(SttError, match="timed out"):
            await transcribe(WyomingStt(uri, timeout=0.2))


async def test_stt_unreachable_server() -> None:
    with pytest.raises(SttError, match="cannot reach speech-to-text server"):
        await transcribe(WyomingStt(closed_uri(), timeout=1))


async def test_stt_connection_reset() -> None:
    async with crashing_server(events=3) as uri:
        with pytest.raises(SttError, match="failed"):
            await transcribe(WyomingStt(uri, timeout=2), tone(1.0))


# ---------------------------------------------------------------------------
# Text-to-speech


def tts_server(
    *replies: Event, received: list[Event] | None = None, hang: bool = False
) -> Callable[[Read, Write], Awaitable[None]]:
    """Reads the ``synthesize`` request, then sends ``replies``."""

    async def handler(read: Read, write: Write) -> None:
        event = await read()
        if received is not None and event is not None:
            received.append(event)
        for reply in replies:
            await write(reply)
        if hang:
            await read_all(read)

    return handler


def start_event(rate: int = TTS_RATE) -> Event:
    return AudioStart(rate=rate, width=2, channels=1).event()


def chunk_event(audio: bytes, rate: int = TTS_RATE) -> Event:
    return AudioChunk(rate=rate, width=2, channels=1, audio=audio).event()


async def synthesize(
    tts: WyomingTts, text: str = "Hello", language: str | None = "en"
) -> PcmStream:
    return await asyncio.wait_for(tts.synthesize(text, language), 3)


async def test_tts_streams_audio_before_synthesis_finishes() -> None:
    received: list[Event] = []
    more = asyncio.Event()
    hung_up = asyncio.Event()
    first, second = tone(0.05, rate=TTS_RATE), tone(0.05, freq=660, rate=TTS_RATE)

    async def handler(read: Read, write: Write) -> None:
        received.append(await read())
        await write(start_event())
        await write(chunk_event(first))
        await more.wait()
        await write(chunk_event(second))
        await write(AudioStop().event())
        await read_all(read)
        hung_up.set()

    async with wyoming_server(handler) as uri:
        stream = await synthesize(WyomingTts(uri, timeout=2), "Good morning!")
        assert isinstance(stream, PcmStream)
        assert stream.format == PcmFormat(rate=TTS_RATE, width=2, channels=1)
        chunks = aiter(stream.chunks)
        assert await asyncio.wait_for(anext(chunks), 2) == first
        more.set()
        assert await asyncio.wait_for(collect(chunks), 2) == [second]
        # The connection is released once the audio has been read.
        await asyncio.wait_for(hung_up.wait(), 2)

    assert Synthesize.is_type(received[0].type)
    assert Synthesize.from_event(received[0]).text == "Good morning!"


@pytest.mark.parametrize(
    ("options", "language", "voice"),
    [
        (
            {"voice": "en_US-lessac-medium", "speaker": "p226"},
            "de",
            {"name": "en_US-lessac-medium", "speaker": "p226"},
        ),
        ({"voice": "en_US-lessac-medium"}, "de", {"name": "en_US-lessac-medium"}),
        ({}, "de-DE", {"language": "de-DE"}),
        ({}, None, None),
    ],
)
async def test_tts_voice_selection(
    options: dict[str, str], language: str | None, voice: dict[str, str] | None
) -> None:
    received: list[Event] = []
    handler = tts_server(start_event(), AudioStop().event(), received=received)
    async with wyoming_server(handler) as uri:
        stream = await synthesize(WyomingTts(uri, timeout=2, **options), "Hallo", language)
        assert await collect(stream.chunks) == []

    assert received[0].data.get("voice") == voice


async def test_tts_error_before_audio() -> None:
    handler = tts_server(Error(text="voice not found").event())
    async with wyoming_server(handler) as uri:
        with pytest.raises(TtsError, match="text-to-speech error: voice not found"):
            await synthesize(WyomingTts(uri, timeout=2))


async def test_tts_error_during_audio() -> None:
    audio = tone(0.05, rate=TTS_RATE)
    handler = tts_server(start_event(), chunk_event(audio), Error(text="out of memory").event())
    async with wyoming_server(handler) as uri:
        stream = await synthesize(WyomingTts(uri, timeout=2))
        chunks = aiter(stream.chunks)
        assert await anext(chunks) == audio
        with pytest.raises(TtsError, match="out of memory"):
            await anext(chunks)


async def test_tts_server_closes_before_audio() -> None:
    async with wyoming_server(tts_server()) as uri:
        with pytest.raises(TtsError, match="closed the connection"):
            await synthesize(WyomingTts(uri, timeout=2))


async def test_tts_server_closes_during_audio() -> None:
    audio = [tone(0.05, rate=TTS_RATE), tone(0.05, freq=660, rate=TTS_RATE)]
    handler = tts_server(start_event(), *map(chunk_event, audio))
    async with wyoming_server(handler) as uri:
        stream = await synthesize(WyomingTts(uri, timeout=2))
        # Whatever arrived is played; the missing audio-stop just ends the stream.
        assert await asyncio.wait_for(collect(stream.chunks), 2) == audio


async def test_tts_ignores_unrelated_events_before_audio() -> None:
    audio = tone(0.05, rate=16000)
    handler = tts_server(
        Event(type="synthesize-started"),
        start_event(rate=16000),
        chunk_event(audio, rate=16000),
        AudioStop().event(),
    )
    async with wyoming_server(handler) as uri:
        stream = await synthesize(WyomingTts(uri, timeout=2))
        assert stream.format == PcmFormat(rate=16000)
        assert await collect(stream.chunks) == [audio]


async def test_tts_unreachable_server() -> None:
    with pytest.raises(TtsError, match="failed"):
        await synthesize(WyomingTts(closed_uri(), timeout=1))


async def test_tts_timeout_waiting_for_audio() -> None:
    async with wyoming_server(tts_server(hang=True)) as uri:
        with pytest.raises(TtsError, match="failed"):
            await synthesize(WyomingTts(uri, timeout=0.2))


async def test_tts_connection_reset() -> None:
    async with crashing_server(events=1) as uri:
        with pytest.raises(TtsError, match="failed"):
            await synthesize(WyomingTts(uri, timeout=2))


async def test_tts_closing_stream_early_hangs_up() -> None:
    hung_up = asyncio.Event()

    async def handler(read: Read, write: Write) -> None:
        await read()
        await write(start_event())
        await write(chunk_event(tone(0.05, rate=TTS_RATE)))
        await read_all(read)  # never finishes the audio
        hung_up.set()

    async with wyoming_server(handler) as uri:
        stream = await synthesize(WyomingTts(uri, timeout=2))
        chunks = aiter(stream.chunks)
        await anext(chunks)
        await chunks.aclose()  # e.g. playback was interrupted
        await asyncio.wait_for(hung_up.wait(), 2)
