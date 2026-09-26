"""OpenAI-compatible speech-to-text, text-to-speech and language model clients, and agents."""

from __future__ import annotations

import asyncio
import io
import re
import socket
import wave
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from conftest import chunked, make_config, tone

from open_speaker.agents import (
    AgentChain,
    AgentError,
    AgentResponse,
    ConversationAgent,
    create_agents,
)
from open_speaker.agents import openai_compat as openai_agent
from open_speaker.agents.openai_compat import DEFAULT_SYSTEM_PROMPT, OpenAiAgent, clean_for_speech
from open_speaker.audio.playback import EncodedAudio
from open_speaker.homeassistant import HomeAssistant
from open_speaker.stt import SttError
from open_speaker.stt.openai_compat import OpenAiStt, iso_language
from open_speaker.tts import TtsError
from open_speaker.tts.openai_compat import OpenAiTts

TRANSCRIPTIONS = "/v1/audio/transcriptions"
SPEECH = "/v1/audio/speech"
CHAT = "/v1/chat/completions"
CONVERSATION = "/api/conversation/process"


@dataclass
class Recorded:
    path: str
    headers: Mapping[str, str]
    json: Any = None
    form: dict[str, str] = field(default_factory=dict)
    files: dict[str, tuple[str, str, bytes]] = field(default_factory=dict)


Responder = Callable[[Recorded], web.StreamResponse]


def completion(content: str | None) -> web.Response:
    message = {"role": "assistant", "content": content}
    return web.json_response(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": "llama3.2",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        }
    )


def not_understood(recorded: Recorded) -> web.Response:
    """Home Assistant's conversation API when no intent matched."""
    return web.json_response(
        {
            "response": {
                "speech": {"plain": {"speech": "Sorry, I couldn't understand that"}},
                "card": {},
                "language": "en",
                "response_type": "error",
                "data": {"code": "no_intent_match"},
            },
            "conversation_id": "01jhaconversation",
            "continue_conversation": False,
        }
    )


class FakeServer:
    """OpenAI-compatible endpoints (and Home Assistant's conversation API)."""

    def __init__(self) -> None:
        self.base = ""
        self.requests: list[Recorded] = []
        self.stall = False
        self.release = asyncio.Event()
        self.replies: dict[str, Responder] = {
            TRANSCRIPTIONS: lambda r: web.json_response({"text": " hello world "}),
            SPEECH: lambda r: web.Response(body=b"RIFF fake wav", content_type="audio/wav"),
            CHAT: lambda r: completion("Sure."),
            CONVERSATION: not_understood,
        }
        self.app = web.Application()
        self.app.router.add_post("/{path:.*}", self._handle)

    @property
    def url(self) -> str:
        return self.base + "/v1"

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        recorded = Recorded(request.path, request.headers.copy())
        if request.content_type == "multipart/form-data":
            for name, value in (await request.post()).items():
                if isinstance(value, web.FileField):
                    recorded.files[name] = (value.filename, value.content_type, value.file.read())
                else:
                    recorded.form[name] = str(value)
        else:
            recorded.json = await request.json()
        self.requests.append(recorded)
        if self.stall:
            await self.release.wait()
        return self.replies[request.path](recorded)


@pytest.fixture
async def server() -> AsyncIterator[FakeServer]:
    fake = FakeServer()
    runner = web.AppRunner(fake.app, shutdown_timeout=1.0)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    fake.base = f"http://127.0.0.1:{runner.addresses[0][1]}"
    yield fake
    fake.release.set()
    await runner.cleanup()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


def closed_url() -> str:
    """An http:// URL that refuses connections."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


async def audio_stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


# ---------------------------------------------------------------------------
# Speech-to-text


async def test_stt_uploads_wav_and_returns_text(
    server: FakeServer, session: aiohttp.ClientSession
) -> None:
    audio = tone(0.4)
    stt = OpenAiStt(session, server.url + "/", model="Systran/faster-whisper-small", api_key="sk-1")
    assert await stt.transcribe(audio_stream(chunked(audio)), "en-US") == "hello world"

    [request] = server.requests
    assert request.path == TRANSCRIPTIONS
    assert request.headers["Authorization"] == "Bearer sk-1"
    assert request.form == {
        "model": "Systran/faster-whisper-small",
        "response_format": "json",
        "language": "en",
    }
    filename, content_type, data = request.files["file"]
    assert (filename, content_type) == ("speech.wav", "audio/wav")
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (16000, 2, 1)
        assert wav.readframes(wav.getnframes()) == audio


async def test_stt_defaults(server: FakeServer, session: aiohttp.ClientSession) -> None:
    await OpenAiStt(session, server.url).transcribe(audio_stream([tone(0.1)]), None)

    [request] = server.requests
    assert "Authorization" not in request.headers
    assert request.form == {"model": "whisper-1", "response_format": "json"}


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", "en"),
        ("en-US", "en"),
        ("pt_BR", "pt"),
        ("DE-de", "de"),
        ("zh-Hant-TW", "zh"),
        ("", None),
        (None, None),
    ],
)
def test_iso_language(language: str | None, expected: str | None) -> None:
    assert iso_language(language) == expected


async def test_stt_http_error(server: FakeServer, session: aiohttp.ClientSession) -> None:
    server.replies[TRANSCRIPTIONS] = lambda r: web.Response(status=500, text="model not loaded")
    with pytest.raises(SttError, match="returned HTTP 500: model not loaded"):
        await OpenAiStt(session, server.url).transcribe(audio_stream([tone(0.1)]), "en")


@pytest.mark.parametrize(
    "reply",
    [
        lambda: web.json_response({"error": {"message": "bad audio"}}),
        lambda: web.json_response({"text": None}),
        lambda: web.json_response(["hello"]),
        lambda: web.Response(text="hello world", content_type="text/plain"),
    ],
    ids=["error-object", "no-text", "list", "not-json"],
)
async def test_stt_unexpected_response(
    server: FakeServer, session: aiohttp.ClientSession, reply: Callable[[], web.Response]
) -> None:
    server.replies[TRANSCRIPTIONS] = lambda r: reply()
    with pytest.raises(SttError):
        await OpenAiStt(session, server.url).transcribe(audio_stream([tone(0.1)]), "en")


async def test_stt_unreachable_server(session: aiohttp.ClientSession) -> None:
    with pytest.raises(SttError, match=r"request to .* failed"):
        await OpenAiStt(session, closed_url()).transcribe(audio_stream([tone(0.1)]), "en")


async def test_stt_timeout(server: FakeServer, session: aiohttp.ClientSession) -> None:
    server.stall = True
    stt = OpenAiStt(session, server.url, timeout=0.1)
    with pytest.raises(SttError, match=r"request to .* failed"):
        await asyncio.wait_for(stt.transcribe(audio_stream([tone(0.1)]), "en"), 2)


# ---------------------------------------------------------------------------
# Text-to-speech


async def test_tts_posts_text_and_returns_encoded_audio(
    server: FakeServer, session: aiohttp.ClientSession
) -> None:
    server.replies[SPEECH] = lambda r: web.Response(body=b"ID3 mp3", content_type="audio/mpeg")
    tts = OpenAiTts(
        session,
        server.url + "/",
        model="kokoro",
        voice="af_heart",
        api_key="sk-2",
        speed=1.25,
        response_format="mp3",
    )
    assert await tts.synthesize("Good morning!", "en") == EncodedAudio(b"ID3 mp3")

    [request] = server.requests
    assert request.path == SPEECH
    assert request.headers["Authorization"] == "Bearer sk-2"
    assert request.json == {
        "model": "kokoro",
        "input": "Good morning!",
        "voice": "af_heart",
        "response_format": "mp3",
        "speed": 1.25,
    }


async def test_tts_defaults(server: FakeServer, session: aiohttp.ClientSession) -> None:
    assert await OpenAiTts(session, server.url).synthesize("Hi", None) == EncodedAudio(
        b"RIFF fake wav"
    )

    [request] = server.requests
    assert "Authorization" not in request.headers
    assert request.json == {
        "model": "tts-1",
        "input": "Hi",
        "voice": "alloy",
        "response_format": "wav",
    }


async def test_tts_http_error(server: FakeServer, session: aiohttp.ClientSession) -> None:
    server.replies[SPEECH] = lambda r: web.Response(status=404, text="voice not found")
    with pytest.raises(TtsError, match="returned HTTP 404: voice not found"):
        await OpenAiTts(session, server.url).synthesize("Hi", "en")


async def test_tts_empty_audio(server: FakeServer, session: aiohttp.ClientSession) -> None:
    server.replies[SPEECH] = lambda r: web.Response(body=b"", content_type="audio/wav")
    with pytest.raises(TtsError, match="returned no audio"):
        await OpenAiTts(session, server.url).synthesize("Hi", "en")


async def test_tts_unreachable_server(session: aiohttp.ClientSession) -> None:
    with pytest.raises(TtsError, match=r"request to .* failed"):
        await OpenAiTts(session, closed_url()).synthesize("Hi", "en")


async def test_tts_timeout(server: FakeServer, session: aiohttp.ClientSession) -> None:
    server.stall = True
    with pytest.raises(TtsError, match=r"request to .* failed"):
        await asyncio.wait_for(
            OpenAiTts(session, server.url, timeout=0.1).synthesize("Hi", "en"), 2
        )


# ---------------------------------------------------------------------------
# Language model agent


class FakeClock:
    def __init__(self) -> None:
        self.now = 5000.0

    def monotonic(self) -> float:
        return self.now


def numbered_answers(server: FakeServer) -> None:
    server.replies[CHAT] = lambda r: completion(f"Answer {len(server.requests)}.")


async def test_agent_request(server: FakeServer, session: aiohttp.ClientSession) -> None:
    server.replies[CHAT] = lambda r: completion("Es ist sonnig.")
    agent = OpenAiAgent(
        session,
        server.url + "/",
        "llama3.2",
        api_key="sk-3",
        system_prompt="You are Jarvis.",
        temperature=0.2,
        max_tokens=120,
    )
    before = datetime.now().astimezone()
    response = await agent.process("Wie ist das Wetter?", "de", None)
    after = datetime.now().astimezone()

    assert (response.text, response.handled, response.continue_conversation) == (
        "Es ist sonnig.",
        True,
        False,
    )
    assert response.conversation_id
    [request] = server.requests
    assert request.path == CHAT
    assert request.headers["Authorization"] == "Bearer sk-3"
    payload = dict(request.json)
    system, user = payload.pop("messages")
    assert payload == {"model": "llama3.2", "stream": False, "temperature": 0.2, "max_tokens": 120}
    assert user == {"role": "user", "content": "Wie ist das Wetter?"}
    assert system["role"] == "system"
    content = system["content"]
    assert content.startswith("You are Jarvis.\nCurrent local time: ")
    assert any(f"{now:%A, %B %d, %Y}" in content for now in (before, after))
    assert re.search(r"\d{4} \d{2}:\d{2}", content)
    assert content.endswith("Reply in the language with code 'de'.")


async def test_agent_defaults(server: FakeServer, session: aiohttp.ClientSession) -> None:
    await OpenAiAgent(session, server.url, "llama3.2").process("Hello", "en", None)

    [request] = server.requests
    assert "Authorization" not in request.headers
    assert (request.json["temperature"], request.json["max_tokens"]) == (0.5, 300)
    assert request.json["messages"][0]["content"].startswith(DEFAULT_SYSTEM_PROMPT + "\n")


async def test_agent_omits_unset_sampling_options(
    server: FakeServer, session: aiohttp.ClientSession
) -> None:
    agent = OpenAiAgent(session, server.url, "llama3.2", temperature=None, max_tokens=None)
    await agent.process("Hello", "en", None)

    assert set(server.requests[0].json) == {"model", "messages", "stream"}


async def test_agent_keeps_history_per_conversation(
    server: FakeServer, session: aiohttp.ClientSession
) -> None:
    numbered_answers(server)
    agent = OpenAiAgent(session, server.url, "llama3.2")
    first = await agent.process("What is the capital of France?", "en", None)
    second = await agent.process("And of Italy?", "en", first.conversation_id)
    other = await agent.process("Tell me a joke.", "en", None)

    assert second.text == "Answer 2."
    assert first.conversation_id == second.conversation_id != other.conversation_id
    history = [request.json["messages"][1:] for request in server.requests]
    assert history[1] == [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "Answer 1."},
        {"role": "user", "content": "And of Italy?"},
    ]
    assert history[2] == [{"role": "user", "content": "Tell me a joke."}]


async def test_agent_continues_conversation_started_elsewhere(
    server: FakeServer, session: aiohttp.ClientSession
) -> None:
    numbered_answers(server)
    agent = OpenAiAgent(session, server.url, "llama3.2")
    first = await agent.process("Hi", "en", "01jhaconversation")
    await agent.process("Again", "en", "01jhaconversation")

    assert first.conversation_id == "01jhaconversation"
    assert server.requests[1].json["messages"][1:] == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Answer 1."},
        {"role": "user", "content": "Again"},
    ]


@pytest.mark.parametrize(("turns", "remembered"), [(0, 0), (1, 1), (2, 2), (6, 3)])
async def test_agent_history_turns(
    server: FakeServer, session: aiohttp.ClientSession, turns: int, remembered: int
) -> None:
    numbered_answers(server)
    agent = OpenAiAgent(session, server.url, "llama3.2", history_turns=turns)
    conversation_id = None
    for n in range(1, 5):
        conversation_id = (
            await agent.process(f"Question {n}", "en", conversation_id)
        ).conversation_id

    expected: list[dict[str, str]] = []
    for n in range(4 - remembered, 4):
        expected += [
            {"role": "user", "content": f"Question {n}"},
            {"role": "assistant", "content": f"Answer {n}."},
        ]
    expected.append({"role": "user", "content": "Question 4"})
    assert server.requests[-1].json["messages"][1:] == expected


async def test_agent_forgets_idle_conversations(
    server: FakeServer, session: aiohttp.ClientSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    monkeypatch.setattr(openai_agent, "time", clock)
    agent = OpenAiAgent(session, server.url, "llama3.2", history_timeout=60)
    first = await agent.process("Dim the lights.", "en", None)
    clock.now += 59
    await agent.process("A bit more.", "en", first.conversation_id)
    clock.now += 61
    late = await agent.process("And warmer?", "en", first.conversation_id)

    assert [len(request.json["messages"]) for request in server.requests] == [2, 4, 2]
    assert late.conversation_id == first.conversation_id


async def test_agent_failed_turn_is_not_remembered(
    server: FakeServer, session: aiohttp.ClientSession
) -> None:
    agent = OpenAiAgent(session, server.url, "llama3.2")
    first = await agent.process("One", "en", None)
    server.replies[CHAT] = lambda r: web.Response(status=503, text="busy")
    with pytest.raises(AgentError):
        await agent.process("Two", "en", first.conversation_id)
    server.replies[CHAT] = lambda r: completion("Three.")
    await agent.process("Three", "en", first.conversation_id)

    messages = server.requests[2].json["messages"][1:]
    assert [message["content"] for message in messages] == ["One", "Sure.", "Three"]


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("<think>The user wants the time.</think>It is 9:15.", "It is 9:15."),
        ("<THINK>\nlong\nreasoning\n</THINK>\n\nSure thing!", "Sure thing!"),
        ("**Paris** is the capital of __France__.", "Paris is the capital of France."),
        ("Run `ls -la` to list files.", "Run ls -la to list files."),
        ("```\nprint('hi')\n```", "print('hi')"),
        ("# Weather\n## Today\nSunny all day.", "Weather Today Sunny all day."),
        ("Options:\n- tea\n- coffee\n  * water", "Options: tea coffee water"),
        ("It is -5 degrees and 3*4 is 12.", "It is -5 degrees and 3*4 is 12."),
        ("  Lots   of\n\nspace  ", "Lots of space"),
    ],
)
def test_clean_for_speech(raw: str, spoken: str) -> None:
    assert clean_for_speech(raw) == spoken


async def test_agent_speaks_and_remembers_cleaned_reply(
    server: FakeServer, session: aiohttp.ClientSession
) -> None:
    server.replies[CHAT] = lambda r: completion(
        "<think>\nThe user wants light.\n</think>\n\nI turned on **all** the lights."
    )
    agent = OpenAiAgent(session, server.url, "qwen3")
    first = await agent.process("Lights on", "en", None)
    await agent.process("Thanks", "en", first.conversation_id)

    assert first.text == "I turned on all the lights."
    assert server.requests[1].json["messages"][2] == {
        "role": "assistant",
        "content": "I turned on all the lights.",
    }


@pytest.mark.parametrize(
    ("content", "follow_up"),
    [
        ("Which room do you mean?", True),
        ("Do you want **more**?\n", True),
        ("Done.", False),
        ("<think>Should I ask?</think>Timer set.", False),
        ("Is that all? Great, done.", False),
    ],
)
async def test_agent_continues_conversation_after_a_question(
    server: FakeServer, session: aiohttp.ClientSession, content: str, follow_up: bool
) -> None:
    server.replies[CHAT] = lambda r: completion(content)
    response = await OpenAiAgent(session, server.url, "llama3.2").process("hi", "en", None)
    assert response.continue_conversation is follow_up


@pytest.mark.parametrize("content", [None, "", "<think>Nothing to add.</think>"])
async def test_agent_empty_reply_is_not_handled(
    server: FakeServer, session: aiohttp.ClientSession, content: str | None
) -> None:
    server.replies[CHAT] = lambda r: completion(content)
    response = await OpenAiAgent(session, server.url, "llama3.2").process("hmm", "en", None)
    assert response.text == ""
    assert not response.handled


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (lambda: web.Response(status=500, text="model not found"), "HTTP 500: model not found"),
        (lambda: web.Response(status=401, text="invalid api key"), "HTTP 401: invalid api key"),
        (
            lambda: web.Response(text="<html>Bad gateway</html>", content_type="text/html"),
            r"language model request to .* failed",
        ),
        (lambda: web.json_response({"choices": []}), "unexpected language model response"),
        (
            lambda: web.json_response({"error": {"message": "context length exceeded"}}),
            "unexpected language model response",
        ),
        (lambda: web.json_response({"choices": [{"message": None}]}), "unexpected"),
        (lambda: web.Response(body=b"", content_type="application/json"), "unexpected"),
    ],
    ids=["server-error", "unauthorized", "not-json", "no-choices", "error", "no-message", "empty"],
)
async def test_agent_errors(
    server: FakeServer,
    session: aiohttp.ClientSession,
    reply: Callable[[], web.Response],
    message: str,
) -> None:
    server.replies[CHAT] = lambda r: reply()
    with pytest.raises(AgentError, match=message):
        await OpenAiAgent(session, server.url, "llama3.2").process("hi", "en", None)


async def test_agent_unreachable_server(session: aiohttp.ClientSession) -> None:
    with pytest.raises(AgentError, match=r"request to .* failed"):
        await OpenAiAgent(session, closed_url(), "llama3.2").process("hi", "en", None)


async def test_agent_timeout(server: FakeServer, session: aiohttp.ClientSession) -> None:
    server.stall = True
    agent = OpenAiAgent(session, server.url, "llama3.2", timeout=0.1)
    with pytest.raises(AgentError, match=r"request to .* failed"):
        await asyncio.wait_for(agent.process("hi", "en", None), 2)


# ---------------------------------------------------------------------------
# Agent chain


class ScriptedAgent(ConversationAgent):
    def __init__(self, name: str, result: AgentResponse | Exception) -> None:
        self.name = name
        self.result = result
        self.calls: list[tuple[str, str, str | None]] = []

    async def process(self, text: str, language: str, conversation_id: str | None) -> AgentResponse:
        self.calls.append((text, language, conversation_id))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_chain_answers_with_first_agent_that_understands() -> None:
    ha = ScriptedAgent("homeassistant", AgentResponse("Turned on the light.", conversation_id="1"))
    llm = ScriptedAgent("openai", AgentResponse("Something else."))

    response = await AgentChain([ha, llm]).process("turn on the light", "en", "conv-0")

    assert response is ha.result
    assert ha.calls == [("turn on the light", "en", "conv-0")]
    assert llm.calls == []


async def test_chain_falls_through_when_not_understood() -> None:
    ha = ScriptedAgent("homeassistant", AgentResponse("Sorry, I didn't get that", handled=False))
    llm = ScriptedAgent("openai", AgentResponse("Spring rain...", continue_conversation=True))

    response = await AgentChain([ha, llm]).process("write a haiku", "en-GB", "conv-0")

    assert response is llm.result
    assert llm.calls == [("write a haiku", "en-GB", "conv-0")]


async def test_chain_falls_through_when_an_agent_fails(caplog: pytest.LogCaptureFixture) -> None:
    ha = ScriptedAgent("homeassistant", AgentError("cannot reach Home Assistant"))
    llm = ScriptedAgent("openai", AgentResponse("It is 9:15."))

    response = await AgentChain([ha, llm]).process("what time is it", "en", None)

    assert response is llm.result
    assert "Agent homeassistant failed: cannot reach Home Assistant" in caplog.text


async def test_chain_returns_last_answer_when_nobody_understands() -> None:
    first = ScriptedAgent("a", AgentResponse("Sorry, I didn't get that", handled=False))
    second = ScriptedAgent("b", AgentResponse("I don't know.", handled=False))

    assert await AgentChain([first, second]).process("blah", "en", None) is second.result
    assert len(first.calls) == len(second.calls) == 1


async def test_chain_keeps_unhandled_answer_when_a_later_agent_fails() -> None:
    ha = ScriptedAgent("homeassistant", AgentResponse("Sorry, I didn't get that", handled=False))
    llm = ScriptedAgent("openai", AgentError("HTTP 500"))

    assert await AgentChain([ha, llm]).process("blah", "en", None) is ha.result


async def test_chain_raises_when_every_agent_fails() -> None:
    chain = AgentChain(
        [
            ScriptedAgent("a", AgentError("first down")),
            ScriptedAgent("b", AgentError("second down")),
        ]
    )
    with pytest.raises(AgentError, match="no agent could answer: second down"):
        await chain.process("hello", "en", None)


def test_chain_needs_an_agent() -> None:
    with pytest.raises(ValueError, match="at least one agent"):
        AgentChain([])


async def test_create_agents_builds_chain_from_config(
    server: FakeServer, session: aiohttp.ClientSession, tmp_path: Path
) -> None:
    server.replies[CHAT] = lambda r: completion("Want to hear another one?")
    config = make_config(
        tmp_path,
        agents=[
            {"engine": "homeassistant", "agent_id": "conversation.home_assistant"},
            {
                "engine": "openai",
                "url": server.url,
                "model": "qwen3:4b",
                "api_key": "sk-4",
                "system_prompt": "You are a pirate.",
                "temperature": 0.9,
                "max_tokens": 64,
                "history_turns": 2,
                "history_timeout": 60,
                "timeout": 12,
            },
        ],
    )
    chain = create_agents(config.agents, session, HomeAssistant(server.base, "secret", session))
    assert [agent.name for agent in chain.agents] == ["homeassistant", "openai"]

    response = await chain.process("Tell me a joke", "en", None)

    assert response.text == "Want to hear another one?"
    assert response.continue_conversation
    ha_request, llm_request = server.requests
    assert ha_request.path == CONVERSATION
    assert ha_request.headers["Authorization"] == "Bearer secret"
    assert ha_request.json == {
        "text": "Tell me a joke",
        "language": "en",
        "agent_id": "conversation.home_assistant",
    }
    assert llm_request.path == CHAT
    assert llm_request.headers["Authorization"] == "Bearer sk-4"
    assert llm_request.json["model"] == "qwen3:4b"
    assert (llm_request.json["temperature"], llm_request.json["max_tokens"]) == (0.9, 64)
    assert llm_request.json["messages"][0]["content"].startswith("You are a pirate.\n")
    llm = chain.agents[1]
    assert isinstance(llm, OpenAiAgent)
    assert (llm.history_turns, llm.history_timeout, llm.timeout) == (2, 60.0, 12.0)


async def test_create_agents_needs_homeassistant(
    session: aiohttp.ClientSession, tmp_path: Path
) -> None:
    config = make_config(tmp_path, agents=[{"engine": "homeassistant"}])
    with pytest.raises(ValueError, match=r"homeassistant\.url and token"):
        create_agents(config.agents, session, None)
