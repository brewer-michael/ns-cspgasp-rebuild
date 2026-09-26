"""Home Assistant client (REST and WebSocket APIs) and the two voice pipelines."""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import socket
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import aiohttp
import pytest
from aiohttp import WSMsgType, web
from conftest import chunked, silence, tone, wait_for

from open_speaker.agents import AgentChain, AgentError, AgentResponse, ConversationAgent
from open_speaker.audio.playback import AudioSource, EncodedAudio
from open_speaker.config import VadConfig
from open_speaker.homeassistant import (
    HomeAssistant,
    HomeAssistantAuthError,
    HomeAssistantError,
    PipelineError,
)
from open_speaker.pipeline import Conversation, PipelineFailure, Reply
from open_speaker.pipeline.homeassistant import HomeAssistantPipeline
from open_speaker.pipeline.local import LocalPipeline
from open_speaker.stt import SpeechToText, SttError
from open_speaker.tts import TextToSpeech, TtsError

TOKEN = "secret"
VERSION = "2026.9.0"
TTS_URL = "/api/tts_proxy/0a1b2c3d.mp3"
MP3 = b"ID3\x04\x00fake mp3 audio"
CHUNK = 4000  # 0.125 s
BYTES_PER_SECOND = 32000
CONFIG = {"location_name": "Home", "version": VERSION}
OUTSIDE = {
    "entity_id": "sensor.outside_temperature",
    "state": "21.5",
    "attributes": {"unit_of_measurement": "°C", "friendly_name": "Outside"},
}
CONVERSATION_RESULT = {
    "response": {
        "speech": {"plain": {"speech": "Turned on the light", "extra_data": None}},
        "card": {},
        "language": "en",
        "response_type": "action_done",
        "data": {"targets": [], "success": [], "failed": []},
    },
    "conversation_id": "01jconversation",
    "continue_conversation": False,
}


@dataclass
class Recorded:
    method: str
    path: str
    headers: Mapping[str, str]
    json: Any = None


class FakeRun:
    """One ``assist_pipeline/run`` subscription on the fake Home Assistant."""

    def __init__(self, ws: web.WebSocketResponse, message: dict[str, Any], handler_id: int) -> None:
        self.ws = ws
        self.message = message
        self.id: int = message["id"]
        self.handler_id = handler_id
        self.frames: list[bytes] = []
        self.ended = asyncio.Event()
        self._arrived = asyncio.Event()

    @property
    def audio(self) -> bytes:
        return b"".join(self.frames)

    def feed(self, data: bytes) -> None:
        if data:
            self.frames.append(data)
        else:
            self.ended.set()
        self._arrived.set()

    async def wait_audio(self, size: int) -> None:
        """Waits for ``size`` bytes of audio (or the end of the stream)."""
        async with asyncio.timeout(2):
            while len(self.audio) < size and not self.ended.is_set():
                self._arrived.clear()
                await self._arrived.wait()

    async def wait_end(self) -> None:
        await asyncio.wait_for(self.ended.wait(), 2)

    async def result(self, error: dict[str, str] | None = None) -> None:
        reply: dict[str, Any] = {"id": self.id, "type": "result", "success": error is None}
        if error is None:
            reply["result"] = None
        else:
            reply["error"] = error
        await self.ws.send_json(reply)

    async def event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        event = {"type": event_type, "data": data or {}, "timestamp": "2026-09-26T12:00:00+00:00"}
        await self.ws.send_json({"id": self.id, "type": "event", "event": event})

    async def start(self, conversation_id: str | None = None, *, audio: bool | None = None) -> None:
        """Accepts the run and sends ``run-start``; runs that take audio get a handler."""
        if audio is None:
            audio = self.message["start_stage"] == "stt"
        await self.result()
        runner_data = {"stt_binary_handler_id": self.handler_id if audio else None, "timeout": 300}
        data = {"pipeline": "01jpipeline", "language": "en", "runner_data": runner_data}
        await self.event("run-start", {**data, "conversation_id": conversation_id})


Script = Callable[[FakeRun], Awaitable[None]]


def speech(text: str) -> dict[str, Any]:
    return {"plain": {"speech": text, "extra_data": None}}


def answer(
    reply: str = "Turned on the lights.",
    *,
    conversation_id: str = "01jconversation",
    url: str | None = TTS_URL,
) -> Script:
    """A text run (``intent`` or ``tts`` to ``tts``) that answers every request."""

    async def script(run: FakeRun) -> None:
        await run.start(conversation_id)
        if run.message["start_stage"] == "intent":
            await run.event("intent-start", {"intent_input": run.message["input"]["text"]})
            response = {"speech": speech(reply), "response_type": "action_done", "data": {}}
            output = {
                "response": response,
                "conversation_id": conversation_id,
                "continue_conversation": False,
            }
            await run.event("intent-end", {"intent_output": output})
        await run.event("tts-start", {"engine": "tts.piper", "tts_input": reply})
        tts_output = {"media_id": "media-source://tts/tts.piper", "mime_type": "audio/mpeg"}
        if url is not None:
            tts_output["url"] = url
        await run.event("tts-end", {"tts_output": tts_output})
        await run.event("run-end")

    return script


def transcribe(text: str = " Turn on the lights ", *, end_at: int = 4 * CHUNK) -> Script:
    """An audio run that hears speech after one chunk and its end after ``end_at`` bytes."""

    async def script(run: FakeRun) -> None:
        await run.start()
        await run.event("stt-start", {"engine": "stt.faster_whisper"})
        await run.wait_audio(CHUNK)
        await run.event("stt-vad-start", {"timestamp": 125})
        await run.wait_audio(end_at)
        await run.event("stt-vad-end", {"timestamp": 500})
        await run.wait_end()
        await run.event("stt-end", {"stt_output": {"text": text}})
        await run.event("run-end")

    return script


def failing(code: str, message: str, *, after_audio: int = 0) -> Script:
    """A run that reports an error, then waits for the speaker to cancel it."""

    async def script(run: FakeRun) -> None:
        await run.start()
        if after_audio:
            await run.wait_audio(after_audio)
        await run.event("error", {"code": code, "message": message})
        await asyncio.Event().wait()

    return script


async def stalled(run: FakeRun) -> None:
    await run.start()
    await asyncio.Event().wait()


class FakeHomeAssistant:
    """Home Assistant's REST and WebSocket APIs; Assist pipeline runs follow ``pipeline``."""

    def __init__(self) -> None:
        self.url = ""
        self.hello: dict[str, Any] = {"type": "auth_required", "ha_version": VERSION}
        self.api_root: Callable[[], web.StreamResponse] = lambda: web.json_response(
            {"message": "API running."}
        )
        self.conversation: Callable[[Any], web.StreamResponse] = lambda body: web.json_response(
            CONVERSATION_RESULT
        )
        self.files = {TTS_URL: MP3}
        self.stall = False
        self.release = asyncio.Event()
        self.requests: list[Recorded] = []
        self.pipeline: Script = answer()
        self.connections = 0
        self.sockets: set[web.WebSocketResponse] = set()
        self.auth: list[dict[str, Any]] = []
        self.received: list[dict[str, Any]] = []
        self.binary: list[bytes] = []
        self.runs: list[FakeRun] = []
        self.unsubscribed: list[int] = []
        self._handler_ids = itertools.count(3)
        self._run_tasks: dict[int, asyncio.Task[Any]] = {}
        self.app = web.Application()
        self.app.router.add_get("/api/websocket", self._websocket)
        self.app.router.add_route("*", "/{path:.*}", self._rest)
        self.app.on_shutdown.append(self._close_sockets)

    async def _rest(self, request: web.Request) -> web.StreamResponse:
        body = await request.json() if request.can_read_body else None
        self.requests.append(Recorded(request.method, request.path, request.headers.copy(), body))
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return web.Response(status=401, text="401: Unauthorized")
        if self.stall:
            await self.release.wait()
        path = request.path
        if path == "/api/":
            return self.api_root()
        if path == "/api/states/sensor.outside_temperature":
            return web.json_response(OUTSIDE)
        if path == "/api/conversation/process" and request.method == "POST":
            return self.conversation(body)
        if path in self.files:
            return web.Response(body=self.files[path], content_type="audio/mpeg")
        return web.json_response({"message": "Not found."}, status=404)

    async def _websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.connections += 1
        self.sockets.add(ws)
        tasks: set[asyncio.Task[None]] = set()
        try:
            await ws.send_json(self.hello)
            message = await ws.receive()
            if message.type is not WSMsgType.TEXT:
                return ws
            self.auth.append(message.json())
            if message.json() != {"type": "auth", "access_token": TOKEN}:
                await ws.send_json(
                    {"type": "auth_invalid", "message": "Invalid access token or password"}
                )
                return ws
            await ws.send_json({"type": "auth_ok", "ha_version": VERSION})
            async for message in ws:
                if message.type is WSMsgType.BINARY:
                    self.binary.append(message.data)
                    for run in self.runs:
                        if run.handler_id == message.data[0]:
                            run.feed(message.data[1:])
                elif message.type is WSMsgType.TEXT:
                    data = message.json()
                    self.received.append(data)
                    task = asyncio.create_task(self._handle(ws, data))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
        finally:
            for task in tasks:
                task.cancel()
            self.sockets.discard(ws)
            await ws.close()
        return ws

    async def _handle(self, ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
        kind, msg_id = message["type"], message["id"]
        if kind == "assist_pipeline/run":
            run = FakeRun(ws, message, next(self._handler_ids))
            self.runs.append(run)
            task = asyncio.current_task()
            assert task is not None
            self._run_tasks[run.id] = task
            await self.pipeline(run)
        elif kind == "unsubscribe_events":
            self.unsubscribed.append(message["subscription"])
            if (task := self._run_tasks.get(message["subscription"])) is not None:
                task.cancel()
            await self._result(ws, msg_id)
        elif kind == "get_config":
            await self._result(ws, msg_id, CONFIG)
        elif kind == "echo":
            await asyncio.sleep(message.get("delay", 0))
            await self._result(ws, msg_id, message["value"])
        elif kind == "echo_batched":
            other = {"id": 999, "type": "event", "event": {"event_type": "state_changed"}}
            result = {"id": msg_id, "type": "result", "success": True, "result": message["value"]}
            await ws.send_json([other, result])
        elif kind == "drop":
            await ws.close()
        elif kind != "ignore":
            error = {"code": "unknown_command", "message": "Unknown command."}
            await ws.send_json({"id": msg_id, "type": "result", "success": False, "error": error})

    @staticmethod
    async def _result(ws: web.WebSocketResponse, msg_id: int, result: Any = None) -> None:
        await ws.send_json({"id": msg_id, "type": "result", "success": True, "result": result})

    async def _close_sockets(self, app: web.Application) -> None:
        for ws in list(self.sockets):
            await ws.close(code=aiohttp.WSCloseCode.GOING_AWAY)


@pytest.fixture
async def fake_ha() -> AsyncIterator[FakeHomeAssistant]:
    fake = FakeHomeAssistant()
    runner = web.AppRunner(fake.app, shutdown_timeout=1.0)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    fake.url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    yield fake
    fake.release.set()
    await runner.cleanup()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
async def ha(
    fake_ha: FakeHomeAssistant, session: aiohttp.ClientSession
) -> AsyncIterator[HomeAssistant]:
    client = HomeAssistant(fake_ha.url, TOKEN, session, timeout=2.0)
    yield client
    await client.close()


def closed_url() -> str:
    """An http:// URL that refuses connections."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


class Mic:
    """Like the speaker's microphone: ``audio`` in chunks, then silence forever."""

    def __init__(self, audio: bytes = b"", chunk: int = CHUNK, pause: float = 0.002) -> None:
        self.chunks = chunked(audio, chunk)
        self.chunk = chunk
        self.pause = pause
        self.pulled: list[bytes] = []

    async def stream(self) -> AsyncIterator[bytes]:
        for index in itertools.count():
            chunk = self.chunks[index] if index < len(self.chunks) else bytes(self.chunk)
            self.pulled.append(chunk)
            yield chunk
            await asyncio.sleep(self.pause)

    @property
    def audio(self) -> bytes:
        return b"".join(self.pulled)


async def finite(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk
        await asyncio.sleep(0)


async def run_events(ha: HomeAssistant, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    async def collect() -> list[dict[str, Any]]:
        return [event async for event in ha.run_pipeline(*args, **kwargs)]

    return await asyncio.wait_for(collect(), 3)


def types(events: list[dict[str, Any]]) -> list[str]:
    return [event["type"] for event in events]


def without_id(message: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key != "id"}


# ---------------------------------------------------------------------------
# REST API


async def test_check_returns_status_message(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    assert await ha.check() == "API running."

    [request] = fake_ha.requests
    assert (request.method, request.path) == ("GET", "/api/")
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_check_with_rejected_token(
    fake_ha: FakeHomeAssistant, session: aiohttp.ClientSession
) -> None:
    with pytest.raises(HomeAssistantAuthError, match="rejected the access token"):
        await HomeAssistant(fake_ha.url, "wrong", session).check()


@pytest.mark.parametrize(
    "response",
    [
        lambda: web.Response(text="<html>Router login</html>", content_type="text/html"),
        lambda: web.json_response({"status": "ok"}),
    ],
    ids=["html", "other-json"],
)
async def test_check_detects_other_servers(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant, response: Callable[[], web.Response]
) -> None:
    fake_ha.api_root = response
    with pytest.raises(HomeAssistantError, match="does not look like Home Assistant"):
        await ha.check()


async def test_rest_http_error(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.api_root = lambda: web.Response(status=500, text="Internal Server Error")
    with pytest.raises(HomeAssistantError, match="GET /api/: HTTP 500 Internal Server Error"):
        await ha.check()


async def test_rest_unreachable(session: aiohttp.ClientSession) -> None:
    with pytest.raises(HomeAssistantError, match="cannot reach Home Assistant"):
        await HomeAssistant(closed_url(), TOKEN, session, timeout=1).check()


async def test_rest_timeout(fake_ha: FakeHomeAssistant, session: aiohttp.ClientSession) -> None:
    fake_ha.stall = True
    ha = HomeAssistant(fake_ha.url, TOKEN, session, timeout=0.1)
    with pytest.raises(HomeAssistantError, match="cannot reach Home Assistant"):
        await asyncio.wait_for(ha.converse("turn on the light"), 2)


async def test_get_state(ha: HomeAssistant) -> None:
    assert await ha.get_state("sensor.outside_temperature") == OUTSIDE
    assert await ha.get_state("sensor.missing") is None


async def test_converse(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    result = await ha.converse(
        "turn on the kitchen light",
        language="en",
        agent_id="conversation.ollama",
        conversation_id="01jconversation",
    )

    assert result == CONVERSATION_RESULT
    [request] = fake_ha.requests
    assert (request.method, request.path) == ("POST", "/api/conversation/process")
    assert request.json == {
        "text": "turn on the kitchen light",
        "language": "en",
        "agent_id": "conversation.ollama",
        "conversation_id": "01jconversation",
    }


async def test_converse_sends_only_given_fields(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    await ha.converse("hello", language="", agent_id=None, conversation_id=None)
    assert fake_ha.requests[0].json == {"text": "hello"}


@pytest.mark.parametrize(
    "response",
    [lambda: web.json_response(["not", "a", "result"]), lambda: web.Response(status=404)],
    ids=["list", "not-found"],
)
async def test_converse_rejects_unexpected_response(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant, response: Callable[[], web.Response]
) -> None:
    fake_ha.conversation = lambda body: response()
    with pytest.raises(HomeAssistantError, match="unexpected response from the conversation API"):
        await ha.converse("hello")


async def test_fetch_downloads_tts_audio(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    assert await ha.fetch(TTS_URL) == MP3
    assert await ha.fetch(fake_ha.url + TTS_URL) == MP3

    assert [request.path for request in fake_ha.requests] == [TTS_URL, TTS_URL]
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in fake_ha.requests)


async def test_fetch_missing_file(ha: HomeAssistant) -> None:
    with pytest.raises(HomeAssistantError, match="not found"):
        await ha.fetch("/api/tts_proxy/missing.mp3")


async def test_fetch_rejects_json(ha: HomeAssistant) -> None:
    with pytest.raises(HomeAssistantError, match="did not return audio"):
        await ha.fetch("/api/")


# ---------------------------------------------------------------------------
# WebSocket API


async def test_connect_authenticates(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    assert not ha.connected
    await ha.connect()
    await ha.connect()

    assert ha.connected
    assert ha.version == VERSION
    assert fake_ha.auth == [{"type": "auth", "access_token": TOKEN}]
    assert fake_ha.connections == 1


async def test_connect_with_rejected_token(
    fake_ha: FakeHomeAssistant, session: aiohttp.ClientSession
) -> None:
    ha = HomeAssistant(fake_ha.url, "wrong", session, timeout=2)
    with pytest.raises(HomeAssistantAuthError, match="Invalid access token or password"):
        await ha.connect()

    assert not ha.connected
    assert fake_ha.auth == [{"type": "auth", "access_token": "wrong"}]
    await wait_for(lambda: not fake_ha.sockets)


async def test_connect_rejects_unexpected_greeting(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    fake_ha.hello = {"type": "hello", "server": "not Home Assistant"}
    with pytest.raises(HomeAssistantError, match="unexpected first message"):
        await ha.connect()

    assert not ha.connected
    await wait_for(lambda: not fake_ha.sockets)  # the WebSocket was closed


async def test_connect_unreachable(session: aiohttp.ClientSession) -> None:
    ha = HomeAssistant(closed_url(), TOKEN, session, timeout=1)
    with pytest.raises(HomeAssistantError, match=r"cannot connect to ws://127\.0\.0\.1"):
        await ha.connect()


async def test_command_returns_result(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    assert await ha.command({"type": "get_config"}) == CONFIG
    assert fake_ha.received == [{"id": 1, "type": "get_config"}]


async def test_command_error(ha: HomeAssistant) -> None:
    with pytest.raises(HomeAssistantError, match=r"unknown_command: Unknown command\."):
        await ha.command({"type": "bogus"})


async def test_concurrent_commands_get_their_own_results(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    slow = ha.command({"type": "echo", "value": "slow", "delay": 0.1})
    fast = ha.command({"type": "echo", "value": "fast"})

    assert await asyncio.wait_for(asyncio.gather(slow, fast), 2) == ["slow", "fast"]
    assert fake_ha.connections == 1
    assert sorted(message["id"] for message in fake_ha.received) == [1, 2]


async def test_command_result_in_batched_message(ha: HomeAssistant) -> None:
    assert await ha.command({"type": "echo_batched", "value": 42}) == 42


async def test_command_times_out(
    fake_ha: FakeHomeAssistant, session: aiohttp.ClientSession
) -> None:
    ha = HomeAssistant(fake_ha.url, TOKEN, session, timeout=0.2)
    try:
        with pytest.raises(HomeAssistantError, match="timed out waiting for Home Assistant"):
            await ha.command({"type": "ignore"})
    finally:
        await ha.close()


async def test_lost_connection_fails_command_and_reconnects(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    with pytest.raises(HomeAssistantError, match="lost connection to Home Assistant"):
        await asyncio.wait_for(ha.command({"type": "drop"}), 2)
    assert not ha.connected

    assert await ha.command({"type": "get_config"}) == CONFIG
    assert fake_ha.connections == 2


async def test_close_disconnects(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    await ha.connect()
    await ha.close()

    assert not ha.connected
    await wait_for(lambda: not fake_ha.sockets)


# ---------------------------------------------------------------------------
# Assist pipelines over the WebSocket API


async def test_run_pipeline_yields_events_until_run_end(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    events = await run_events(
        ha,
        "intent",
        "tts",
        {"text": "turn on the lights"},
        pipeline="01jpipeline",
        conversation_id="01jconversation",
    )

    assert types(events) == [
        "run-start",
        "intent-start",
        "intent-end",
        "tts-start",
        "tts-end",
        "run-end",
    ]
    assert events[4]["data"]["tts_output"]["url"] == TTS_URL
    [run] = fake_ha.runs
    assert run.message == {
        "id": run.id,
        "type": "assist_pipeline/run",
        "start_stage": "intent",
        "end_stage": "tts",
        "input": {"text": "turn on the lights"},
        "pipeline": "01jpipeline",
        "conversation_id": "01jconversation",
    }
    # The run finished by itself, so it is not cancelled.
    await ha.command({"type": "get_config"})
    assert [message["type"] for message in fake_ha.received] == [
        "assist_pipeline/run",
        "get_config",
    ]


async def test_run_pipeline_omits_unset_options(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    await run_events(ha, "tts", "tts", {"text": "Your timer is done."})

    [run] = fake_ha.runs
    assert without_id(run.message) == {
        "type": "assist_pipeline/run",
        "start_stage": "tts",
        "end_stage": "tts",
        "input": {"text": "Your timer is done."},
    }


async def test_run_pipeline_streams_audio_to_binary_handler(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    async def script(run: FakeRun) -> None:
        await run.start()
        await run.event("stt-start")
        await run.wait_end()
        await run.event("stt-end", {"stt_output": {"text": "hello"}})
        await run.event("run-end")

    fake_ha.pipeline = script
    audio = chunked(tone(0.5), 3200)
    events = await run_events(ha, "stt", "stt", {"sample_rate": 16000}, audio=finite(audio))

    assert types(events) == ["run-start", "stt-start", "stt-end", "run-end"]
    [run] = fake_ha.runs
    marker = bytes([run.handler_id])
    assert run.handler_id != run.id
    assert fake_ha.binary == [marker + chunk for chunk in audio] + [marker]


async def test_run_pipeline_stops_streaming_when_speech_ends(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    fake_ha.pipeline = transcribe()
    mic = Mic(tone(3.0))
    events = await run_events(ha, "stt", "stt", {"sample_rate": 16000}, audio=mic.stream())

    assert types(events) == [
        "run-start",
        "stt-start",
        "stt-vad-start",
        "stt-vad-end",
        "stt-end",
        "run-end",
    ]
    [run] = fake_ha.runs
    marker = bytes([run.handler_id])
    assert fake_ha.binary[-1] == marker
    assert fake_ha.binary.count(marker) == 1
    assert len(run.audio) >= 4 * CHUNK
    assert mic.audio.startswith(run.audio)
    pulled = len(mic.pulled)
    await asyncio.sleep(0.05)
    assert len(mic.pulled) == pulled  # the microphone is no longer read


async def test_run_pipeline_rejected_run(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    async def script(run: FakeRun) -> None:
        await run.result({"code": "pipeline-not-found", "message": "Pipeline not found"})

    fake_ha.pipeline = script
    with pytest.raises(PipelineError) as info:
        await run_events(ha, "intent", "tts", {"text": "hi"}, pipeline="missing")
    assert (info.value.code, info.value.message) == ("pipeline-not-found", "Pipeline not found")


async def test_run_pipeline_yields_error_events(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    async def script(run: FakeRun) -> None:
        await run.start()
        await run.event("intent-start")
        await run.event("error", {"code": "intent-failed", "message": "Intent failed"})
        await run.event("run-end")

    fake_ha.pipeline = script
    events = await run_events(ha, "intent", "tts", {"text": "hi"})

    assert types(events) == ["run-start", "intent-start", "error", "run-end"]
    assert events[2]["data"] == {"code": "intent-failed", "message": "Intent failed"}


async def test_run_pipeline_unsubscribes_when_stopped_early(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    fake_ha.pipeline = stalled
    events = ha.run_pipeline("stt", "stt", {"sample_rate": 16000}, audio=Mic().stream())
    async with asyncio.timeout(3), contextlib.aclosing(events):
        async for event in events:
            assert event["type"] == "run-start"
            break

    [run] = fake_ha.runs
    await wait_for(lambda: fake_ha.unsubscribed == [run.id])
    assert fake_ha.binary[-1] == bytes([run.handler_id])  # the audio stream was ended first
    assert ha._queues == {}  # nothing left waiting for a reply


async def test_run_pipeline_needs_binary_handler_for_audio(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    async def script(run: FakeRun) -> None:
        await run.start(audio=False)
        await asyncio.Event().wait()

    fake_ha.pipeline = script
    with pytest.raises(HomeAssistantError, match="pipeline did not accept audio"):
        await run_events(ha, "stt", "stt", {"sample_rate": 16000}, audio=Mic().stream())

    [run] = fake_ha.runs
    await wait_for(lambda: fake_ha.unsubscribed == [run.id])


async def test_run_pipeline_times_out(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = stalled
    with pytest.raises(HomeAssistantError, match="timed out waiting for Home Assistant"):
        await run_events(ha, "intent", "tts", {"text": "hi"}, event_timeout=0.2)

    [run] = fake_ha.runs
    await wait_for(lambda: fake_ha.unsubscribed == [run.id])


async def test_run_pipeline_connection_lost(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    async def script(run: FakeRun) -> None:
        await run.start()
        await run.ws.close()

    fake_ha.pipeline = script
    with pytest.raises(HomeAssistantError, match="lost connection to Home Assistant"):
        await run_events(ha, "intent", "tts", {"text": "hi"})
    assert not ha.connected


# ---------------------------------------------------------------------------
# Home Assistant pipeline


async def listen(pipeline: HomeAssistantPipeline | LocalPipeline, mic: Mic) -> str | None:
    return await asyncio.wait_for(pipeline.listen(mic.stream(), Conversation("en")), 3)


async def test_ha_listen_transcribes_speech(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = transcribe(" Turn on the lights ")
    pipeline = HomeAssistantPipeline(ha, VadConfig(), pipeline_id="01jpipeline")
    mic = Mic(tone(3.0))

    assert await listen(pipeline, mic) == "Turn on the lights"
    [run] = fake_ha.runs
    assert without_id(run.message) == {
        "type": "assist_pipeline/run",
        "start_stage": "stt",
        "end_stage": "stt",
        "input": {"sample_rate": 16000},
        "pipeline": "01jpipeline",
    }
    assert len(run.audio) >= 4 * CHUNK
    assert mic.audio.startswith(run.audio)
    assert fake_ha.binary[-1] == bytes([run.handler_id])


async def test_ha_listen_nothing_recognized(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = failing("stt-no-text-recognized", "No text recognized", after_audio=CHUNK)
    pipeline = HomeAssistantPipeline(ha, VadConfig())

    assert await listen(pipeline, Mic(tone(3.0))) is None
    [run] = fake_ha.runs
    await wait_for(lambda: fake_ha.binary[-1] == bytes([run.handler_id]))


async def test_ha_listen_empty_transcript(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = transcribe("   ")
    assert await listen(HomeAssistantPipeline(ha, VadConfig()), Mic(tone(3.0))) is None


async def test_ha_listen_gives_up_when_nobody_speaks(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    async def script(run: FakeRun) -> None:
        await run.start()
        await run.wait_end()  # the speaker ends the stream by itself
        await run.event("error", {"code": "stt-no-text-recognized", "message": "No text"})
        await run.event("run-end")

    fake_ha.pipeline = script
    pipeline = HomeAssistantPipeline(ha, VadConfig(speech_start_timeout=0.5, max_seconds=10.0))
    mic = Mic()

    assert await listen(pipeline, mic) is None
    [run] = fake_ha.runs
    assert len(run.audio) == BYTES_PER_SECOND // 2
    assert len(mic.pulled) == 4
    assert fake_ha.binary[-1] == bytes([run.handler_id])


async def test_ha_listen_stops_at_max_length(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    speech_reported = asyncio.Event()

    async def script(run: FakeRun) -> None:
        await run.start()
        await run.wait_audio(CHUNK)
        await run.event("stt-vad-start", {"timestamp": 0})
        speech_reported.set()
        await run.wait_end()  # the speech never ends; the speaker stops at max_seconds
        await run.event("stt-end", {"stt_output": {"text": "a very long request"}})
        await run.event("run-end")

    async def microphone() -> AsyncIterator[bytes]:
        for index, chunk in enumerate(chunked(tone(3.0), CHUNK)):
            if index == 1:
                # Home Assistant hears the speech well before the start timeout (chunk 4).
                await asyncio.wait_for(speech_reported.wait(), 2)
            yield chunk
            await asyncio.sleep(0.01)

    fake_ha.pipeline = script
    pipeline = HomeAssistantPipeline(ha, VadConfig(speech_start_timeout=0.5, max_seconds=1.0))
    text = await asyncio.wait_for(pipeline.listen(microphone(), Conversation("en")), 3)

    assert text == "a very long request"
    [run] = fake_ha.runs
    assert len(run.audio) == BYTES_PER_SECOND


async def test_ha_listen_pipeline_error(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = failing("stt-stream-failed", "Speech-to-text failed", after_audio=CHUNK)
    pipeline = HomeAssistantPipeline(ha, VadConfig())

    with pytest.raises(PipelineFailure, match="stt-stream-failed: Speech-to-text failed"):
        await listen(pipeline, Mic(tone(3.0)))
    [run] = fake_ha.runs
    await wait_for(lambda: fake_ha.unsubscribed == [run.id])  # the run is cancelled...
    assert fake_ha.binary[-1] == bytes([run.handler_id])  # ...after the audio has ended


async def test_ha_respond(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = answer("Turned on the lights.")
    pipeline = HomeAssistantPipeline(ha, VadConfig(), pipeline_id="01jpipeline")
    conversation = Conversation("en")

    reply = await asyncio.wait_for(pipeline.respond("turn on the lights", conversation), 3)

    assert reply == Reply("Turned on the lights.", EncodedAudio(MP3), continue_conversation=False)
    assert conversation.id == "01jconversation"
    [run] = fake_ha.runs
    assert without_id(run.message) == {
        "type": "assist_pipeline/run",
        "start_stage": "intent",
        "end_stage": "tts",
        "input": {"text": "turn on the lights"},
        "pipeline": "01jpipeline",
    }
    assert fake_ha.requests[-1].path == TTS_URL

    await asyncio.wait_for(pipeline.respond("and the kitchen", conversation), 3)
    assert fake_ha.runs[1].message["conversation_id"] == "01jconversation"


async def test_ha_respond_with_follow_up_question(
    ha: HomeAssistant, fake_ha: FakeHomeAssistant
) -> None:
    async def script(run: FakeRun) -> None:
        await run.start()  # older Home Assistant versions send no conversation id here
        await run.event("intent-start")
        output = {
            "response": {"speech": speech("Which room?"), "response_type": "question"},
            "conversation_id": "01jfollowup",
            "continue_conversation": True,
        }
        await run.event("intent-end", {"intent_output": output})
        await run.event("tts-start")
        await run.event("tts-end", {"tts_output": {"url": TTS_URL, "mime_type": "audio/mpeg"}})
        await run.event("run-end")

    fake_ha.pipeline = script
    conversation = Conversation("en")
    pipeline = HomeAssistantPipeline(ha, VadConfig())

    reply = await asyncio.wait_for(pipeline.respond("turn on the light", conversation), 3)

    assert reply == Reply("Which room?", EncodedAudio(MP3), continue_conversation=True)
    assert conversation.id == "01jfollowup"


async def test_ha_respond_without_speech_url(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = answer("Done.", url=None)
    reply = await HomeAssistantPipeline(ha, VadConfig()).respond("hi", Conversation("en"))

    assert reply == Reply("Done.", None)
    assert fake_ha.requests == []


async def test_ha_respond_pipeline_error(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = failing("intent-failed", "Unexpected error during intent recognition")
    with pytest.raises(PipelineFailure, match="intent-failed"):
        await HomeAssistantPipeline(ha, VadConfig()).respond("hi", Conversation("en"))


async def test_ha_respond_download_failure(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = answer(url="/api/tts_proxy/missing.mp3")
    with pytest.raises(PipelineFailure, match="could not download speech audio"):
        await HomeAssistantPipeline(ha, VadConfig()).respond("hi", Conversation("en"))


async def test_ha_speak(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    pipeline = HomeAssistantPipeline(ha, VadConfig(), pipeline_id="01jpipeline")

    assert await pipeline.speak("Your timer is done.", "en") == EncodedAudio(MP3)
    [run] = fake_ha.runs
    assert without_id(run.message) == {
        "type": "assist_pipeline/run",
        "start_stage": "tts",
        "end_stage": "tts",
        "input": {"text": "Your timer is done."},
        "pipeline": "01jpipeline",
    }


async def test_ha_speak_pipeline_error(ha: HomeAssistant, fake_ha: FakeHomeAssistant) -> None:
    fake_ha.pipeline = failing("tts-failed", "Text-to-speech failed")
    with pytest.raises(PipelineFailure, match="tts-failed: Text-to-speech failed"):
        await HomeAssistantPipeline(ha, VadConfig()).speak("hello", "en")


async def test_ha_pipeline_unreachable(session: aiohttp.ClientSession) -> None:
    ha = HomeAssistant(closed_url(), TOKEN, session, timeout=1)
    pipeline = HomeAssistantPipeline(ha, VadConfig())

    with pytest.raises(PipelineFailure, match="cannot connect"):
        await pipeline.speak("hello", "en")
    with pytest.raises(PipelineFailure, match="cannot connect"):
        await listen(pipeline, Mic())


# ---------------------------------------------------------------------------
# Local pipeline


class RecordingStt(SpeechToText):
    """Reads the audio stream like a streaming speech-to-text server."""

    def __init__(self, mic: Mic, text: str = "what time is it", error: Exception | None = None):
        self.mic = mic
        self.text = text
        self.error = error
        self.audio: bytes | None = None
        self.language: str | None = None
        self.pulled_at_start = 0

    async def transcribe(self, audio: AsyncIterable[bytes], language: str | None) -> str:
        self.pulled_at_start = len(self.mic.pulled)
        self.language = language
        self.audio = b"".join([chunk async for chunk in audio])
        if self.error is not None:
            raise self.error
        return self.text


class FakeTts(TextToSpeech):
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    async def synthesize(self, text: str, language: str | None) -> AudioSource:
        self.calls.append((text, language))
        if self.error is not None:
            raise self.error
        return EncodedAudio(f"TTS:{text}".encode())


class FakeAgent(ConversationAgent):
    name = "fake"

    def __init__(self, result: AgentResponse | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str | None]] = []

    async def process(self, text: str, language: str, conversation_id: str | None) -> AgentResponse:
        self.calls.append((text, language, conversation_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def local_pipeline(
    stt: SpeechToText | None = None,
    agent: ConversationAgent | None = None,
    tts: TextToSpeech | None = None,
    vad: VadConfig | None = None,
    stt_language: str | None = None,
) -> LocalPipeline:
    return LocalPipeline(
        stt or RecordingStt(Mic()),
        AgentChain([agent or FakeAgent(AgentResponse("OK."))]),
        tts or FakeTts(),
        vad or VadConfig(),
        stt_language=stt_language,
    )


def local_mic(audio: bytes = b"") -> Mic:
    return Mic(audio, chunk=1024, pause=0)  # 32 ms chunks, as fast as they can be read


async def test_local_listen_streams_speech_to_stt() -> None:
    lead, words = silence(0.6), tone(1.0)
    mic = local_mic(lead + words + silence(1.5))
    stt = RecordingStt(mic)

    assert await listen(local_pipeline(stt), mic) == "what time is it"
    # Speech-to-text is only contacted once someone has talked for 0.25 s...
    started = len(lead) + BYTES_PER_SECOND // 4
    assert started <= stt.pulled_at_start * 1024 < started + 2 * 1024
    # ...and receives everything from the wake word to 0.8 s after the speech.
    assert stt.audio == mic.audio
    ended = len(lead + words) + int(0.8 * BYTES_PER_SECOND)
    assert ended <= len(stt.audio) < ended + 2 * 1024


async def test_local_listen_ignores_silence() -> None:
    mic = local_mic()
    stt = RecordingStt(mic)

    assert await listen(local_pipeline(stt, vad=VadConfig(speech_start_timeout=1.0)), mic) is None
    assert stt.audio is None
    assert BYTES_PER_SECOND <= len(mic.audio) < BYTES_PER_SECOND + 2 * 1024


async def test_local_listen_stops_at_max_length() -> None:
    lead = silence(0.3)
    mic = local_mic(lead + tone(3.0))
    stt = RecordingStt(mic)

    assert await listen(local_pipeline(stt, vad=VadConfig(max_seconds=1.0)), mic) is not None
    assert stt.audio is not None
    assert BYTES_PER_SECOND <= len(stt.audio) < BYTES_PER_SECOND + 2 * 1024


@pytest.mark.parametrize(("stt_language", "expected"), [(None, "en"), ("de-DE", "de-DE")])
async def test_local_listen_language(stt_language: str | None, expected: str) -> None:
    mic = local_mic(silence(0.3) + tone(0.5) + silence(1.0))
    stt = RecordingStt(mic)

    await listen(local_pipeline(stt, stt_language=stt_language), mic)
    assert stt.language == expected


async def test_local_listen_empty_transcript() -> None:
    mic = local_mic(silence(0.3) + tone(0.5) + silence(1.0))
    assert await listen(local_pipeline(RecordingStt(mic, text="")), mic) is None


async def test_local_listen_stt_failure() -> None:
    mic = local_mic(silence(0.3) + tone(0.5) + silence(1.0))
    stt = RecordingStt(mic, error=SttError("speech-to-text server timed out"))
    with pytest.raises(PipelineFailure, match="speech-to-text server timed out"):
        await listen(local_pipeline(stt), mic)


async def test_local_respond_speaks_the_answer() -> None:
    agent = FakeAgent(
        AgentResponse("It is ten past nine.", continue_conversation=True, conversation_id="c7")
    )
    tts = FakeTts()
    pipeline = local_pipeline(agent=agent, tts=tts)
    conversation = Conversation("en-GB")

    reply = await pipeline.respond("what time is it", conversation)

    assert reply == Reply("It is ten past nine.", EncodedAudio(b"TTS:It is ten past nine."), True)
    assert conversation.id == "c7"
    assert agent.calls == [("what time is it", "en-GB", None)]
    assert tts.calls == [("It is ten past nine.", "en-GB")]

    await pipeline.respond("and in Tokyo?", conversation)
    assert agent.calls[1] == ("and in Tokyo?", "en-GB", "c7")


async def test_local_respond_keeps_conversation_id() -> None:
    pipeline = local_pipeline(agent=FakeAgent(AgentResponse("Sure.")))
    conversation = Conversation("en", id="c1")

    await pipeline.respond("thanks", conversation)
    assert conversation.id == "c1"


async def test_local_respond_without_text_is_silent() -> None:
    tts = FakeTts()
    pipeline = local_pipeline(agent=FakeAgent(AgentResponse("")), tts=tts)

    assert await pipeline.respond("hmm", Conversation("en")) == Reply("", None, False)
    assert tts.calls == []


async def test_local_respond_agent_failure() -> None:
    pipeline = local_pipeline(agent=FakeAgent(AgentError("language model request failed")))
    with pytest.raises(PipelineFailure, match="language model request failed"):
        await pipeline.respond("hello", Conversation("en"))


async def test_local_respond_tts_failure() -> None:
    pipeline = local_pipeline(tts=FakeTts(TtsError("text-to-speech server closed")))
    with pytest.raises(PipelineFailure, match="text-to-speech server closed"):
        await pipeline.respond("hello", Conversation("en"))


async def test_local_speak() -> None:
    tts = FakeTts()
    pipeline = local_pipeline(tts=tts)

    assert await pipeline.speak("Your timer is done.", "de") == EncodedAudio(
        b"TTS:Your timer is done."
    )
    assert tts.calls == [("Your timer is done.", "de")]

    pipeline = local_pipeline(tts=FakeTts(TtsError("voice not found")))
    with pytest.raises(PipelineFailure, match="voice not found"):
        await pipeline.speak("hello", "en")
