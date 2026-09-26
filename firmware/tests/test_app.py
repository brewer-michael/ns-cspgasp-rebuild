"""The Speaker: conversations, on-device intents, ringing, buttons, display and lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from conftest import FakeMic, FakePipeline, FakePlayer, make_config, silence, wait_for

from open_speaker import app
from open_speaker.app import (
    MAX_TURNS,
    SWAP_SECONDS,
    AssistantState,
    Components,
    Speaker,
    format_temperature,
)
from open_speaker.audio.playback import EncodedAudio, PlaybackError
from open_speaker.config import Config
from open_speaker.hardware.buttons import ButtonEvent
from open_speaker.hardware.leds import Status
from open_speaker.homeassistant import HomeAssistantError
from open_speaker.intents import (
    EVERY_DAY,
    WEEKDAYS,
    AlarmStatus,
    AskAlarmTime,
    AskTimerDuration,
    CancelAlarm,
    CancelTimer,
    ChangeVolume,
    Intent,
    SetAlarm,
    Snooze,
    StartTimer,
    Stop,
    TimerStatus,
)
from open_speaker.pipeline import Conversation, PipelineFailure, Reply
from open_speaker.timers import Ring, Scheduler
from open_speaker.ui import DisplayState

WAKE_WORD = b"\x55\x05" * 512  # the chunk of audio FakeWake recognizes
NOISE = silence(0.032)  # what the microphone hears the rest of the time
DUCKED = ["-M sget Music", "-M -q sset Music 20%"]
RESTORED = "-M -q sset Music 80%"
SENSOR = {
    "entity_id": "sensor.outside",
    "state": "21.6",
    "attributes": {"unit_of_measurement": "°C"},
}
WEATHER = {
    "entity_id": "weather.home",
    "state": "sunny",
    "attributes": {"temperature": 71.6, "temperature_unit": "°F"},
}


# ---------------------------------------------------------------------------
# Fakes


class FakeWake:
    """A wake word engine that hears WAKE_WORD."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.broken = False
        self.started = False
        self.stopped = False
        self.detections = 0
        self.errors = 0
        self.resets = 0

    async def start(self) -> None:
        if self.fail:
            raise RuntimeError("pymicro_wakeword is not installed")
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def process(self, chunk: bytes) -> str | None:
        if self.broken:
            self.errors += 1
            raise RuntimeError("model crashed")
        if chunk != WAKE_WORD:
            return None
        self.detections += 1
        return "okay nabu"

    async def reset(self) -> None:
        self.resets += 1


class FakeLeds:
    """Records status changes (not repeats) and volume flashes."""

    def __init__(self) -> None:
        self.statuses: list[Status] = []
        self.flashes: list[int] = []
        self.night = False
        self.started = False
        self.stopped = False

    @property
    def status(self) -> Status | None:
        return self.statuses[-1] if self.statuses else None

    def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def set(self, status: Status) -> None:
        if status is not self.status:
            self.statuses.append(status)

    def set_night(self, night: bool) -> None:
        self.night = night

    def flash_volume(self, level: int) -> None:
        self.flashes.append(level)


class FakeVolumeLed:
    def __init__(self) -> None:
        self.shown: list[tuple[int, bool]] = []
        self.night = False
        self.closed = False

    def show(self, level: int, muted: bool = False) -> None:
        self.shown.append((level, muted))

    def close(self) -> None:
        self.closed = True


class FakeDisplay:
    """Renders the speaker's display state each time it is asked to refresh."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.state: Callable[[], DisplayState] | None = None
        self.shown: list[DisplayState] = []
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        if self.fail:
            raise OSError("no OLED at address 0x3c")
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def refresh(self) -> None:
        if self.state is not None:
            self.shown.append(self.state())


class FakeButtons:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.on_event: Callable[[str, ButtonEvent], Any] | None = None
        self.started = False
        self.closed = False

    def start(self) -> None:
        if self.fail:
            raise RuntimeError("Unable to load any default pin factory!")
        self.started = True

    def close(self) -> None:
        self.closed = True


class FakeHomeAssistant:
    def __init__(self, state: Any = None, files: dict[str, bytes] | None = None) -> None:
        self.state = state  # what get_state returns (raised if it is an exception)
        self.files = files or {}
        self.requested: list[str] = []
        self.closed = False

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        self.requested.append(entity_id)
        if isinstance(self.state, Exception):
            raise self.state
        return self.state

    async def fetch(self, url: str) -> bytes:
        if url not in self.files:
            raise HomeAssistantError(f"{url} not found")
        return self.files[url]

    async def close(self) -> None:
        self.closed = True


class SlowPlayer(FakePlayer):
    """Like the real player: one sound at a time, each lasting ``delay`` seconds (speech:
    ``speech_delay``) unless stop() interrupts it."""

    def __init__(self, delay: float = 0.002, speech_delay: float | None = None) -> None:
        super().__init__(delay)
        self.speech_delay = delay if speech_delay is None else speech_delay
        self.fail_speech = False
        # Called when speech starts playing; the results are kept in ``snapshots``.
        self.snapshot: Callable[[], Any] | None = None
        self.snapshots: list[Any] = []
        self._lock = asyncio.Lock()
        self._interrupt = asyncio.Event()

    def stop(self) -> None:
        super().stop()
        self._interrupt.set()

    async def _play(self, kind: str, value: Any) -> bool:
        speech = kind != "pcm"
        if speech and self.fail_speech:
            raise PlaybackError("audio player exited with code 1")
        async with self._lock:
            self._interrupt.clear()
            self._playing += 1
            self.played.append((kind, value))
            if speech and self.snapshot is not None:
                self.snapshots.append(self.snapshot())
            try:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._interrupt.wait(), self.speech_delay if speech else self.delay
                    )
                    return False
                return True
            finally:
                self._playing -= 1


class ScriptedPipeline(FakePipeline):
    """FakePipeline whose respond() can also fail for given requests."""

    def __init__(
        self,
        transcripts: list[str | None],
        replies: dict[str, Reply] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        super().__init__(transcripts, replies)
        self.errors = errors or {}

    async def respond(self, text: str, conversation: Conversation) -> Reply:
        if text in self.errors:
            self.responded.append(text)
            raise self.errors[text]
        return await super().respond(text, conversation)


class WallClock:
    """The scheduler's clock: 5:00 this morning until a test moves it."""

    def __init__(self) -> None:
        self.now = datetime.combine(date.today(), dtime(5, 0)).timestamp()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Monotonic:
    """Stands in for the ``time`` module inside open_speaker.app."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


# ---------------------------------------------------------------------------
# A speaker built from fakes


@dataclass
class Rig:
    speaker: Speaker
    mic: FakeMic
    player: SlowPlayer
    pipeline: ScriptedPipeline
    wake: FakeWake
    scheduler: Scheduler
    clock: WallClock
    leds: FakeLeds
    display: FakeDisplay
    volume_led: FakeVolumeLed

    def earcons(self) -> list[str]:
        """Names of the feedback sounds played so far, in order."""
        names = {len(s.pcm): name for name, s in self.speaker.sounds.items() if s is not None}
        return [names[size] for kind, size in self.player.played if kind == "pcm"]

    def settings(self) -> dict[str, Any]:
        return json.loads(self.speaker.config.settings_file.read_text())

    async def converse(self) -> None:
        """Say the wake word and wait until the conversation is over."""
        resets = self.wake.resets
        self.mic.feed(WAKE_WORD)
        await wait_for(lambda: self.wake.resets > resets)


def config_for(tmp_path: Path, **overrides: Any) -> Config:
    """make_config, without the pause after a conversation unless one is given."""
    wake = {"refractory_seconds": 0.0, **overrides.pop("wake", {})}
    return make_config(tmp_path, wake=wake, **overrides)


def ducking_config(tmp_path: Path) -> Config:
    return config_for(tmp_path, audio={"output": {"volume_control": None, "duck_control": "Music"}})


async def _stream(mic: FakeMic) -> None:
    """A microphone that never stops: room noise every 2 ms."""
    while True:
        mic.feed(NOISE)
        await asyncio.sleep(0.002)


async def _no_ring(ring: Ring) -> None:
    return None


_DEFAULT: Any = object()


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[Callable[..., Awaitable[Rig]]]:
    speakers: list[Speaker] = []
    streams: list[asyncio.Task[None]] = []

    async def build(
        transcripts: list[str | None] | None = None,
        replies: dict[str, Reply] | None = None,
        *,
        errors: dict[str, Exception] | None = None,
        config: Config | None = None,
        player: SlowPlayer | None = None,
        pipeline: Any = _DEFAULT,
        wake: Any = _DEFAULT,
        scheduler: Any = _DEFAULT,
        display: Any = _DEFAULT,
        homeassistant: Any = None,
        buttons: Any = None,
        session: aiohttp.ClientSession | None = None,
        stream: bool = True,
        start: bool = True,
    ) -> Rig:
        config = config or config_for(tmp_path)
        clock = WallClock()
        if pipeline is _DEFAULT:
            pipeline = ScriptedPipeline(transcripts or [], replies, errors)
        if wake is _DEFAULT:
            wake = FakeWake()
        if scheduler is _DEFAULT:
            scheduler = Scheduler(config.timers_state_file, on_ring=_no_ring, clock=clock)
        if display is _DEFAULT:
            display = FakeDisplay()
        mic, leds, volume_led = FakeMic(), FakeLeds(), FakeVolumeLed()
        player = player or SlowPlayer()
        speaker = Speaker(
            config,
            Components(
                mic=mic,
                player=player,  # type: ignore[arg-type]
                pipeline=pipeline,
                wake=wake,
                homeassistant=homeassistant,
                scheduler=scheduler,
                display=display,
                leds=leds,
                volume_led=volume_led,
                buttons=buttons,
                session=session,
            ),
        )
        if display is not None:
            display.state = speaker.display_state
        speakers.append(speaker)
        if start:
            await speaker.start()
        if stream:
            streams.append(asyncio.create_task(_stream(mic)))
        return Rig(
            speaker, mic, player, pipeline, wake, scheduler, clock, leds, display, volume_led
        )

    yield build
    for task in streams:
        task.cancel()
    await asyncio.gather(*streams, return_exceptions=True)
    for speaker in speakers:
        await asyncio.wait_for(speaker.shutdown(), 5)


@pytest.fixture
def amixer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake ``amixer`` on PATH that logs its arguments; the Music control is at 80%."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "amixer.log"
    script = bin_dir / "amixer"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {shlex.quote(str(log))}\n'
        'case "$*" in *sget*) echo "  Mono: Playback 204 [80%] [on]" ;; esac\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


@contextlib.asynccontextmanager
async def web_server(application: web.Application) -> AsyncIterator[str]:
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        await runner.cleanup()


async def ring(r: Rig, *, alarm: bool = False, name: str | None = None) -> None:
    """Make a timer (or a one-shot alarm) go off by moving the scheduler's clock."""
    if alarm:
        r.clock.now = r.scheduler.add_alarm(6, 0).next_at
    else:
        r.clock.advance(r.scheduler.add_timer(60, name).seconds)
    await r.scheduler.check()
    assert r.speaker.ringing


# ---------------------------------------------------------------------------
# Conversations


async def test_wake_word_starts_a_conversation(rig) -> None:
    reply = Reply("Sunny and 22 degrees.", EncodedAudio(b"SUNNY"))
    r = await rig(["what's the weather like"], {"what's the weather like": reply})
    await r.converse()
    assert r.wake.detections == 1
    assert r.pipeline.heard_audio == [4096]  # four chunks from the microphone
    assert r.pipeline.responded == ["what's the weather like"]
    assert r.player.audio == [b"SUNNY"]
    assert r.earcons() == ["wake"]
    assert r.leds.statuses == [
        Status.IDLE,
        Status.LISTENING,
        Status.THINKING,
        Status.SPEAKING,
        Status.IDLE,
    ]
    assert r.speaker.state is AssistantState.IDLE
    assert not r.speaker.conversation_active
    assert r.speaker.connected


async def test_follow_up_turn_when_the_reply_continues_the_conversation(rig) -> None:
    question = Reply("Which room?", EncodedAudio(b"WHICH ROOM"), continue_conversation=True)
    r = await rig(["turn on the lights", "the kitchen"], {"turn on the lights": question})
    await r.converse()
    assert r.pipeline.responded == ["turn on the lights", "the kitchen"]
    assert r.player.audio == [b"WHICH ROOM", b"REPLY"]
    assert r.earcons() == ["wake", "wake"]
    assert r.wake.detections == 1
    assert r.leds.statuses.count(Status.LISTENING) == 2


async def test_follow_up_can_be_turned_off(rig, tmp_path) -> None:
    question = Reply("Which room?", EncodedAudio(b"WHICH ROOM"), continue_conversation=True)
    r = await rig(
        ["turn on the lights", "the kitchen"],
        {"turn on the lights": question},
        config=config_for(tmp_path, pipeline={"follow_up": False}),
    )
    await r.converse()
    assert r.pipeline.responded == ["turn on the lights"]
    assert r.pipeline.transcripts == ["the kitchen"]


async def test_conversation_ends_after_max_turns(rig) -> None:
    questions = [f"question {n}" for n in range(MAX_TURNS + 2)]
    replies = {
        q: Reply("And?", EncodedAudio(q.encode()), continue_conversation=True) for q in questions
    }
    r = await rig(questions, replies)
    await r.converse()
    assert r.pipeline.responded == questions[:MAX_TURNS]
    assert r.player.audio == [q.encode() for q in questions[:MAX_TURNS]]
    assert r.earcons() == ["wake"] * MAX_TURNS
    assert r.speaker.state is AssistantState.IDLE


@pytest.mark.parametrize("transcript", [None, ""])
async def test_hearing_nothing_ends_the_conversation(rig, transcript) -> None:
    r = await rig([transcript])
    await r.converse()
    assert r.pipeline.responded == []
    assert r.player.audio == []
    assert r.earcons() == ["wake", "error"]
    assert r.leds.statuses == [Status.IDLE, Status.LISTENING, Status.IDLE]
    assert r.speaker.connected


async def test_silence_after_a_follow_up_question_ends_quietly(rig) -> None:
    question = Reply("Which scene?", EncodedAudio(b"WHICH SCENE"), continue_conversation=True)
    r = await rig(["set the scene", None], {"set the scene": question})
    await r.converse()
    assert r.pipeline.responded == ["set the scene"]
    assert r.player.audio == [b"WHICH SCENE"]
    assert r.earcons() == ["wake", "wake"]
    assert r.speaker.state is AssistantState.IDLE


async def test_pipeline_failure_plays_the_error_sound(rig) -> None:
    r = await rig(
        ["what's on my calendar", "hello"],
        errors={"what's on my calendar": PipelineFailure("agent unreachable")},
    )
    await r.converse()
    assert r.pipeline.responded == ["what's on my calendar"]
    assert not r.speaker.connected
    assert r.earcons() == ["wake", "error"]
    assert r.leds.statuses == [
        Status.IDLE,
        Status.LISTENING,
        Status.THINKING,
        Status.ERROR,
        Status.IDLE,
    ]
    await r.converse()
    assert r.pipeline.responded == ["what's on my calendar", "hello"]
    assert r.speaker.connected


async def test_unexpected_error_in_a_conversation_is_contained(rig) -> None:
    r = await rig(["hello", "hello again"], errors={"hello": RuntimeError("bug")})
    await r.converse()
    assert r.speaker.connected  # not a network problem
    assert r.earcons() == ["wake", "error"]
    assert r.leds.statuses[-2:] == [Status.ERROR, Status.IDLE]
    await r.converse()
    assert r.player.audio == [b"REPLY"]


async def test_reply_that_cannot_be_played_sounds_the_error_earcon(rig) -> None:
    r = await rig(["hello"])
    r.player.fail_speech = True
    await r.converse()
    assert r.pipeline.responded == ["hello"]
    assert r.earcons() == ["wake", "error"]
    assert r.speaker.state is AssistantState.IDLE


async def test_wake_word_is_ignored_while_the_speaker_talks(rig) -> None:
    r = await rig(["hello"], player=SlowPlayer(speech_delay=10))
    await r.speaker.say("The laundry is done")
    await wait_for(lambda: r.speaker.state is AssistantState.SPEAKING)
    r.mic.feed(WAKE_WORD)
    await asyncio.sleep(0.05)
    assert r.wake.detections == 0
    assert not r.speaker.conversation_active
    r.player.speech_delay = 0.002
    r.player.stop()
    await wait_for(lambda: r.speaker.state is AssistantState.IDLE)
    await r.converse()
    assert r.pipeline.responded == ["hello"]


async def test_wake_word_is_ignored_right_after_a_conversation(rig, tmp_path) -> None:
    config = config_for(tmp_path, wake={"refractory_seconds": 0.3})
    r = await rig(["hello", "hello again"], config=config)
    await r.converse()
    r.mic.feed(WAKE_WORD)
    await wait_for(lambda: r.wake.detections == 2)
    await asyncio.sleep(0.02)
    assert not r.speaker.conversation_active
    await asyncio.sleep(0.3)
    await r.converse()
    assert r.pipeline.responded == ["hello", "hello again"]
    assert r.wake.detections == 3


async def test_wake_word_engine_errors_do_not_stop_the_microphone(rig) -> None:
    r = await rig(["hello"])
    r.wake.broken = True
    await wait_for(lambda: r.wake.errors > 5)
    r.wake.broken = False
    await r.converse()
    assert r.pipeline.responded == ["hello"]


async def test_without_a_pipeline_nothing_listens(rig) -> None:
    r = await rig(pipeline=None)
    assert not r.speaker.start_conversation()
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    assert not r.speaker.conversation_active
    with pytest.raises(PipelineFailure):
        await r.speaker.say("hello")


# ---------------------------------------------------------------------------
# Requests handled on the speaker


async def test_timer_request_is_handled_on_the_speaker(rig) -> None:
    r = await rig(["Set a timer for 5 minutes"])
    await r.converse()
    (timer,) = r.scheduler.timers()
    assert (timer.seconds, timer.name) == (300, None)
    assert r.pipeline.responded == []
    assert r.pipeline.spoken == ["Timer set for 5 minutes."]
    assert r.player.audio == [b"TTS:Timer set for 5 minutes."]
    assert r.earcons() == ["wake"]
    assert r.leds.statuses[-3:] == [Status.THINKING, Status.SPEAKING, Status.IDLE]


async def test_named_timer_request(rig) -> None:
    r = await rig(["set a pizza timer for 10 minutes"])
    await r.converse()
    (timer,) = r.scheduler.timers()
    assert (timer.seconds, timer.name) == (600, "pizza")
    assert r.pipeline.spoken == ["Pizza timer set for 10 minutes."]


async def test_confirmation_falls_back_to_an_earcon_when_tts_fails(rig) -> None:
    r = await rig(["set a timer for 5 minutes"])
    r.pipeline.fail_speak = True
    await r.converse()
    assert [t.seconds for t in r.scheduler.timers()] == [300]
    assert r.player.audio == []
    assert r.earcons() == ["wake", "done"]
    assert r.speaker.connected


async def test_local_intents_can_be_turned_off(rig, tmp_path) -> None:
    config = config_for(tmp_path, pipeline={"local_intents": False})
    r = await rig(["set a timer for 5 minutes"], config=config)
    await r.converse()
    assert r.pipeline.responded == ["set a timer for 5 minutes"]
    assert r.scheduler.timers() == []


@pytest.mark.parametrize(
    ("request_text", "level"),
    [
        ("volume up", 55),
        ("turn it down", 45),
        ("set the volume to 8", 80),
        ("volume 30 percent", 30),
        ("max volume", 100),
    ],
)
async def test_volume_requests(rig, request_text, level) -> None:
    r = await rig([request_text])
    await r.converse()
    assert r.speaker.volume.level == level
    assert r.earcons() == ["wake", "volume"]
    assert r.pipeline.responded == []
    assert r.pipeline.spoken == []
    assert r.settings()["volume"] == level


async def test_stop_with_nothing_to_stop(rig) -> None:
    r = await rig(["stop"])
    await r.converse()
    assert r.earcons() == ["wake", "done"]
    assert r.pipeline.responded == []
    assert r.pipeline.spoken == []


async def test_alarm_request_sets_an_alarm(rig) -> None:
    r = await rig(["wake me up at 6:30 am every weekday"])
    await r.converse()
    (alarm,) = r.scheduler.alarms()
    assert (alarm.hour, alarm.minute, alarm.repeat) == (6, 30, [0, 1, 2, 3, 4])
    assert r.pipeline.spoken == ["Alarm set for 6:30 AM on weekdays."]
    assert r.pipeline.responded == []
    state = r.speaker.display_state()
    assert (state.secondary, state.swap, state.alarm_set) == ("6:30 AM", True, True)


async def test_alarm_question_is_answered_in_the_next_turn(rig, tmp_path) -> None:
    config = config_for(tmp_path, pipeline={"follow_up": False})  # a question still waits
    r = await rig(["set an alarm", "7:15 pm on weekdays"], config=config)
    await r.converse()
    assert r.pipeline.spoken == [
        "What time should I set the alarm for?",
        "Alarm set for 7:15 PM on weekdays.",
    ]
    assert r.earcons() == ["wake", "wake"]
    assert r.pipeline.responded == []
    (alarm,) = r.scheduler.alarms()
    assert (alarm.hour, alarm.minute, alarm.repeat) == (19, 15, [0, 1, 2, 3, 4])


async def test_timer_question_is_answered_in_the_next_turn(rig) -> None:
    r = await rig(["set a timer", "ten minutes"])
    await r.converse()
    assert r.pipeline.spoken == ["For how long?", "Timer set for 10 minutes."]
    assert [t.seconds for t in r.scheduler.timers()] == [600]


async def test_unrelated_answer_to_a_question_goes_to_the_assistant(rig) -> None:
    r = await rig(["set a timer", "what's the weather"])
    await r.converse()
    assert r.pipeline.spoken == ["For how long?"]
    assert r.pipeline.responded == ["what's the weather"]
    assert r.scheduler.timers() == []


async def reply_text(speaker: Speaker, intent: Intent) -> str:
    return (await speaker.handle_intent(intent)).reply.text


async def test_timer_intents(rig) -> None:
    r = await rig()
    speaker = r.speaker
    assert await reply_text(speaker, TimerStatus()) == "There's no timer running."
    assert await reply_text(speaker, CancelTimer()) == "There's no timer running."
    assert await reply_text(speaker, StartTimer(300)) == "Timer set for 5 minutes."
    assert (
        await reply_text(speaker, StartTimer(90, "pizza"))
        == "Pizza timer set for 1 minute and 30 seconds."
    )
    r.clock.advance(30)
    assert (
        await reply_text(speaker, TimerStatus())
        == "1 minute left on the pizza timer; 4 minutes and 30 seconds left on the timer."
    )
    assert await reply_text(speaker, TimerStatus("pizza")) == "1 minute left on the pizza timer."
    assert await reply_text(speaker, CancelTimer("soup")) == "I couldn't find a soup timer."
    assert await reply_text(speaker, CancelTimer("pizza")) == "Pizza timer cancelled."
    assert await reply_text(speaker, TimerStatus()) == "4 minutes and 30 seconds left."
    assert await reply_text(speaker, CancelTimer()) == "Timer cancelled."
    speaker.scheduler.add_timer(60)
    speaker.scheduler.add_timer(120)
    assert await reply_text(speaker, CancelTimer(all=True)) == "2 timers cancelled."
    answer = await speaker.handle_intent(AskTimerDuration())
    assert (answer.reply.text, answer.question) == ("For how long?", AskTimerDuration())


async def test_alarm_intents(rig) -> None:
    r = await rig()  # the scheduler's clock says 5:00 today
    speaker = r.speaker
    assert await reply_text(speaker, AlarmStatus()) == "You don't have any alarms."
    assert await reply_text(speaker, CancelAlarm()) == "You don't have any alarms."
    assert await reply_text(speaker, SetAlarm(6, 30, EVERY_DAY)) == (
        "Alarm set for 6:30 AM every day."
    )
    assert await reply_text(speaker, AlarmStatus()) == "Your alarm is set for 6:30 AM every day."
    assert await reply_text(speaker, SetAlarm(19, 0, WEEKDAYS)) == "Alarm set for 7 PM on weekdays."
    assert await reply_text(speaker, AlarmStatus()) == (
        "You have 2 alarms: 6:30 AM every day, 7 PM on weekdays."
    )
    assert await reply_text(speaker, CancelAlarm(8, 0)) == "I couldn't find that alarm."
    assert await reply_text(speaker, CancelAlarm(7, 0, ambiguous=True)) == (
        "Alarm for 7 PM on weekdays cancelled."
    )
    assert await reply_text(speaker, SetAlarm(7, 0)) == "Alarm set for 7 AM."
    assert await reply_text(speaker, SetAlarm(4, 0)) == "Alarm set for 4 AM tomorrow."
    in_three_days = date.today() + timedelta(days=3)
    assert await reply_text(speaker, SetAlarm(8, 0, day=in_three_days.weekday())) == (
        f"Alarm set for 8 AM on {in_three_days:%A}."
    )
    assert await reply_text(speaker, CancelAlarm(all=True)) == "4 alarms cancelled."
    answer = await speaker.handle_intent(AskAlarmTime())
    assert (answer.reply.text, answer.question) == (
        "What time should I set the alarm for?",
        AskAlarmTime(),
    )


async def test_alarm_times_follow_the_24_hour_clock_setting(rig, tmp_path) -> None:
    r = await rig(config=config_for(tmp_path, display={"clock_24h": True}))
    assert await reply_text(r.speaker, SetAlarm(6, 30)) == "Alarm set for 06:30."
    state = r.speaker.display_state()
    assert (state.secondary, state.clock_24h) == ("06:30", True)


async def test_turning_off_the_alarm_cancels_the_next_one(rig) -> None:
    r = await rig()
    await reply_text(r.speaker, SetAlarm(6, 30, EVERY_DAY))
    assert await reply_text(r.speaker, Stop(alarm=True)) == "Alarm for 6:30 AM every day cancelled."
    assert r.scheduler.alarms() == []
    answer = await r.speaker.handle_intent(Stop(alarm=True))
    assert (answer.reply.text, answer.sound) == ("", "done")


async def test_intents_when_timers_are_turned_off(rig) -> None:
    r = await rig(scheduler=None)
    speaker = r.speaker
    for intent in (StartTimer(60), TimerStatus(), SetAlarm(7, 0), AlarmStatus(), Intent()):
        assert await reply_text(speaker, intent) == (
            "Timers and alarms are turned off on this speaker."
        )
    assert await reply_text(speaker, Snooze()) == "There's no alarm to snooze."
    answer = await speaker.handle_intent(ChangeVolume(level=20))
    assert (answer.reply.text, answer.sound, speaker.volume.level) == ("", "volume", 20)
    answer = await speaker.handle_intent(Stop())
    assert (answer.reply.text, answer.sound) == ("", "done")
    state = speaker.display_state()
    assert not state.alarm_set
    assert (speaker.status()["timers"], speaker.status()["alarms"]) == ([], [])


async def test_unknown_intent(rig) -> None:
    r = await rig()
    assert await reply_text(r.speaker, Intent()) == "Sorry, I can't do that yet."


# ---------------------------------------------------------------------------
# Timers and alarms going off


async def test_short_timer_rings_until_stopped_by_voice(rig, tmp_path) -> None:
    scheduler = Scheduler(tmp_path / "timers.json", on_ring=_no_ring)  # the real clock
    r = await rig(["stop"], scheduler=scheduler)
    scheduler.add_timer(0.05)
    await wait_for(lambda: bool(r.speaker.ringing))
    assert r.speaker.status()["ringing"] == ["timer"]
    assert r.leds.status is Status.ALARM
    await wait_for(lambda: r.earcons().count("timer") >= 2)  # it keeps ringing
    await r.converse()  # the wake word is heard even while the timer sound plays
    assert r.speaker.ringing == []
    assert r.leds.status is Status.IDLE
    assert r.earcons()[-2:] == ["wake", "done"]
    played = len(r.player.played)
    await asyncio.sleep(0.05)
    assert len(r.player.played) == played


async def test_named_timer_is_announced_once(rig) -> None:
    r = await rig()
    await ring(r, name="pizza")
    assert r.speaker.status()["ringing"] == ["pizza timer"]
    await wait_for(lambda: r.earcons().count("timer") >= 3)
    assert r.pipeline.spoken == ["Your pizza timer is done."]
    assert r.player.audio == [b"TTS:Your pizza timer is done."]


@pytest.mark.parametrize(("request_text", "minutes"), [("snooze", 9), ("snooze for 5 minutes", 5)])
async def test_voice_snooze_rings_the_alarm_again_later(rig, request_text, minutes) -> None:
    r = await rig([request_text])
    await ring(r, alarm=True)
    assert r.speaker.status()["ringing"] == ["alarm"]
    assert r.speaker.display_state().ringing == "alarm"
    await wait_for(lambda: "alarm" in r.earcons())
    await r.converse()
    assert r.speaker.ringing == []
    assert r.pipeline.spoken == [f"Snoozing for {minutes} minutes."]
    assert r.earcons()[-1] == "wake"  # the alarm sound paused while listening
    assert r.leds.status is Status.IDLE
    r.clock.advance(minutes * 60 - 1)
    await r.scheduler.check()
    assert r.speaker.ringing == []
    r.clock.advance(1)
    await r.scheduler.check()
    assert r.speaker.status()["ringing"] == ["alarm"]


async def test_voice_stop_silences_an_alarm_for_good(rig) -> None:
    r = await rig(["turn off the alarm"])
    await ring(r, alarm=True)
    await r.converse()
    assert r.speaker.ringing == []
    assert r.earcons()[-2:] == ["wake", "done"]
    r.clock.advance(3600)
    await r.scheduler.check()
    assert r.speaker.ringing == []
    assert r.scheduler.alarms() == []


async def test_snooze_does_not_apply_to_timers(rig) -> None:
    r = await rig(["snooze"])
    await ring(r)
    await r.converse()
    assert r.pipeline.spoken == ["There's no alarm to snooze."]
    assert r.speaker.status()["ringing"] == ["timer"]
    rung = r.earcons().count("timer")
    await wait_for(lambda: r.earcons().count("timer") > rung)  # rings on afterwards


async def test_action_button_snoozes_or_stops_a_ringing_alarm(rig) -> None:
    r = await rig()
    await ring(r, alarm=True)
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    assert r.speaker.ringing == []
    assert not r.speaker.conversation_active
    r.clock.advance(9 * 60)
    await r.scheduler.check()
    assert r.speaker.status()["ringing"] == ["alarm"]
    r.speaker.on_button("action", ButtonEvent.LONG_PRESS)  # a long press stops it
    assert r.speaker.ringing == []
    r.clock.advance(9 * 60)
    await r.scheduler.check()
    assert r.speaker.ringing == []


async def test_action_button_stops_a_ringing_timer(rig) -> None:
    r = await rig()
    await ring(r)
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    assert r.speaker.ringing == []
    assert not r.speaker.conversation_active
    assert r.leds.status is Status.IDLE
    played = len(r.player.played)
    await asyncio.sleep(0.02)
    assert len(r.player.played) == played
    r.clock.advance(3600)
    await r.scheduler.check()
    assert r.speaker.ringing == []


async def test_unattended_ringing_stops_after_the_ring_timeout(rig, tmp_path) -> None:
    r = await rig(config=config_for(tmp_path, timers={"ring_timeout": 0.1}))
    await ring(r)
    await wait_for(lambda: not r.speaker.ringing)
    assert "timer" in r.earcons()
    assert r.leds.status is Status.IDLE
    assert r.speaker.display_state().ringing is None


# ---------------------------------------------------------------------------
# Buttons


async def test_volume_buttons(rig) -> None:
    buttons = FakeButtons()
    r = await rig(buttons=buttons)
    assert buttons.started
    assert buttons.on_event == r.speaker.on_button
    presses = [
        ("volume_up", ButtonEvent.PRESS, 55),
        ("volume_up", ButtonEvent.REPEAT, 60),
        ("volume_down", ButtonEvent.PRESS, 55),
        ("volume_down", ButtonEvent.REPEAT, 50),
    ]
    for count, (name, event, level) in enumerate(presses, 1):
        buttons.on_event(name, event)
        await wait_for(lambda level=level: r.speaker.volume.level == level)
        await wait_for(lambda count=count: r.earcons().count("volume") == count)
        await wait_for(lambda: not r.player.is_playing)
    for event in (ButtonEvent.RELEASE, ButtonEvent.LONG_PRESS, ButtonEvent.SHORT_PRESS):
        r.speaker.on_button("volume_up", event)
    await asyncio.sleep(0.02)
    assert r.speaker.volume.level == 50
    assert r.leds.flashes == [55, 60, 55, 50]
    assert r.volume_led.shown[-1] == (50, False)
    state = r.speaker.display_state()
    assert (state.secondary, state.swap) == ("Vol 50", True)
    assert r.settings() == {"volume": 50, "speaker_muted": False, "mic_muted": False}


async def test_volume_stays_in_range_and_unmutes(rig) -> None:
    r = await rig()
    speaker = r.speaker
    assert await speaker.change_volume(level=98) == 98
    assert await speaker.change_volume(steps=1) == 100
    assert await speaker.change_volume(level=3) == 3
    assert await speaker.change_volume(steps=-1) == 0
    await speaker.set_speaker_muted(True)
    assert r.player.software_gain == 0
    await speaker.change_volume(steps=-1)
    assert speaker.volume.muted  # turning it down does not unmute
    assert await speaker.change_volume(steps=1) == 5
    assert not speaker.volume.muted
    assert r.player.software_gain == pytest.approx(0.05**2)


async def test_volume_tick_is_skipped_while_audio_plays(rig) -> None:
    r = await rig(player=SlowPlayer(speech_delay=10))
    await r.speaker.say("A long story")
    await wait_for(lambda: r.player.is_playing)
    r.speaker.on_button("volume_up", ButtonEvent.PRESS)
    await wait_for(lambda: r.speaker.volume.level == 55)
    await asyncio.sleep(0.02)
    assert "volume" not in r.earcons()


async def test_mute_button_turns_the_microphone_off_and_on(rig) -> None:
    r = await rig(["hello"])
    r.speaker.on_button("mute", ButtonEvent.PRESS)
    await wait_for(lambda: r.speaker.mic_muted)
    assert r.mic.paused
    assert (r.display.shown[-1].secondary, r.display.shown[-1].swap) == ("mic off", True)
    assert r.leds.status is Status.MUTED
    assert r.settings()["mic_muted"] is True
    await wait_for(lambda: r.earcons() == ["error"])
    r.mic.feed(WAKE_WORD)  # not heard: the microphone is off
    await asyncio.sleep(0.05)
    assert r.wake.detections == 0
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)  # refuses to listen
    assert not r.speaker.conversation_active
    await wait_for(lambda: r.earcons() == ["error", "error"])
    r.speaker.on_button("mute", ButtonEvent.RELEASE)
    await asyncio.sleep(0.01)
    assert r.speaker.mic_muted
    r.speaker.on_button("mute", ButtonEvent.PRESS)
    await wait_for(lambda: not r.speaker.mic_muted)
    assert not r.mic.paused
    assert r.speaker.display_state().secondary == "mic on"
    assert r.leds.status is Status.IDLE
    await wait_for(lambda: r.earcons() == ["error", "error", "done"])
    await r.converse()
    assert r.pipeline.responded == ["hello"]


async def test_mute_button_can_mute_the_speaker_instead(rig, tmp_path) -> None:
    r = await rig(config=config_for(tmp_path, buttons={"mute_function": "speaker"}))
    r.speaker.on_button("mute", ButtonEvent.PRESS)
    await wait_for(lambda: r.speaker.volume.muted)
    assert not r.speaker.mic_muted
    assert not r.mic.paused
    assert r.speaker.display_state().secondary == "Vol off"
    assert r.volume_led.shown[-1] == (50, True)
    assert r.speaker.status()["speaker_muted"]
    r.speaker.on_button("mute", ButtonEvent.PRESS)
    await wait_for(lambda: not r.speaker.volume.muted)
    assert r.speaker.display_state().secondary == "Vol 50"
    assert r.volume_led.shown[-1] == (50, False)


async def test_muting_the_microphone_ends_a_conversation(rig) -> None:
    r = await rig(stream=False)
    assert r.speaker.start_conversation()
    await wait_for(lambda: r.speaker.state is AssistantState.LISTENING)
    await r.speaker.set_mic_muted(True)
    await wait_for(lambda: not r.speaker.conversation_active)
    assert r.speaker.state is AssistantState.IDLE
    assert r.leds.status is Status.MUTED
    assert not r.speaker.start_conversation()


async def test_action_tap_while_idle_starts_listening(rig) -> None:
    r = await rig(["what time is it"])
    r.speaker.on_button("action", ButtonEvent.PRESS)  # acts on release (SHORT_PRESS)
    assert not r.speaker.conversation_active
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    assert r.speaker.conversation_active
    await wait_for(lambda: not r.speaker.conversation_active)
    assert r.pipeline.responded == ["what time is it"]
    assert r.wake.detections == 0


async def test_action_tap_while_listening_cancels(rig) -> None:
    r = await rig(stream=False)
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    await wait_for(lambda: r.speaker.state is AssistantState.LISTENING)
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    await wait_for(lambda: not r.speaker.conversation_active)
    assert r.speaker.state is AssistantState.IDLE
    assert r.pipeline.heard_audio == []
    assert r.pipeline.responded == []
    assert r.leds.statuses == [Status.IDLE, Status.LISTENING, Status.IDLE]


async def test_action_tap_while_speaking_interrupts_the_reply(rig) -> None:
    r = await rig(["tell me a story"], player=SlowPlayer(speech_delay=10))
    r.mic.feed(WAKE_WORD)
    await wait_for(lambda: r.speaker.state is AssistantState.SPEAKING)
    stopped = r.player.stopped
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    await wait_for(lambda: not r.speaker.conversation_active)
    assert r.player.stopped > stopped
    assert r.speaker.state is AssistantState.IDLE
    assert r.player.audio == [b"REPLY"]
    assert r.wake.resets == 1


async def test_action_tap_stops_an_announcement(rig) -> None:
    r = await rig(player=SlowPlayer(speech_delay=10))
    await r.speaker.say("The laundry is done")
    await wait_for(lambda: r.speaker.state is AssistantState.SPEAKING)
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)
    await wait_for(lambda: r.speaker.state is AssistantState.IDLE)
    assert not r.speaker.conversation_active
    assert r.player.audio == [b"TTS:The laundry is done"]


# ---------------------------------------------------------------------------
# The display


def sensor(state: str, unit: str | None = "°C") -> dict[str, Any]:
    attributes = {"unit_of_measurement": unit} if unit else {}
    return {"entity_id": "sensor.porch", "state": state, "attributes": attributes}


@pytest.mark.parametrize(
    ("state", "unit", "expected"),
    [
        (SENSOR, None, "22°C"),
        (WEATHER, None, "72°F"),
        (sensor("-18.4"), None, "\u221218°C"),  # typographic minus
        (sensor("-0.4"), None, "0°C"),
        (sensor("20", "C"), None, "20°C"),
        (sensor("20", None), None, "20°"),
        (SENSOR, "°", "22°"),
        (SENSOR, "", "22°"),
        (None, None, None),
        ({}, None, None),
        (sensor("unavailable"), None, None),
        ({"entity_id": "weather.home", "state": "sunny", "attributes": {}}, None, None),
        (sensor("nan"), None, None),
        (sensor("inf"), None, None),
    ],
)
def test_format_temperature(state, unit, expected) -> None:
    assert format_temperature(state, unit) == expected


async def test_display_shows_the_temperature_from_home_assistant(rig, tmp_path) -> None:
    ha = FakeHomeAssistant(state=SENSOR)
    config = config_for(
        tmp_path, display={"temperature": {"entity": "sensor.outside", "refresh_seconds": 0.01}}
    )
    r = await rig(config=config, homeassistant=ha)
    await wait_for(lambda: r.speaker.temperature == "22°C")
    assert ha.requested[0] == "sensor.outside"
    state = r.speaker.display_state()
    assert (state.secondary, state.swap, state.ringing, state.mode) == ("22°C", False, None, None)
    assert r.display.shown[-1].secondary == "22°C"
    ha.state = HomeAssistantError("connection refused")
    await wait_for(lambda: not r.speaker.connected)
    assert r.speaker.temperature == "22°C"  # the last reading stays
    ha.state = WEATHER
    await wait_for(lambda: r.speaker.temperature == "72°F")
    assert r.speaker.connected
    ha.state = None  # the entity was removed
    await wait_for(lambda: r.speaker.temperature is None)
    assert r.speaker.status()["temperature"] is None
    ha.state = sensor("nan")  # a broken sensor does not stop the updates
    polls = len(ha.requested)
    await wait_for(lambda: len(ha.requested) > polls + 1)
    assert r.speaker.temperature is None
    ha.state = SENSOR
    await wait_for(lambda: r.speaker.temperature == "22°C")


async def test_volume_change_swaps_into_the_temperature_slot(rig, monkeypatch) -> None:
    clock = Monotonic()
    monkeypatch.setattr(app, "time", clock)
    r = await rig()
    r.speaker.temperature = "21°C"
    assert r.speaker.display_state().secondary == "21°C"
    await r.speaker.change_volume(steps=1)
    state = r.speaker.display_state()
    assert (state.secondary, state.swap) == ("Vol 55", True)
    clock.now += SWAP_SECONDS - 0.01
    assert r.speaker.display_state().secondary == "Vol 55"
    clock.now += 0.02
    state = r.speaker.display_state()
    assert (state.secondary, state.swap) == ("21°C", False)


async def test_display_counts_down_the_next_timer(rig) -> None:
    r = await rig()
    r.speaker.temperature = "21°C"
    r.scheduler.add_timer(3725, "roast")
    r.scheduler.add_timer(125)
    state = r.speaker.display_state()
    assert (state.secondary, state.swap) == ("2:05", False)
    r.clock.advance(65.5)
    assert r.speaker.display_state().secondary == "1:00"
    r.scheduler.cancel_timers()  # the one ending soonest
    assert r.speaker.display_state().secondary == "1:01:00"
    await r.speaker.change_volume(steps=1)
    assert r.speaker.display_state().secondary == "Vol 55"  # a swap wins
    r.scheduler.cancel_timers(all=True)
    assert r.speaker.display_state().secondary == "Vol 55"


async def test_display_while_ringing(rig) -> None:
    r = await rig()
    r.speaker.temperature = "21°C"
    await ring(r)
    state = r.speaker.display_state()
    assert (state.ringing, state.secondary) == ("timer", "End")
    r.speaker.stop_ringing()
    assert r.speaker.display_state().secondary == "21°C"
    await ring(r, alarm=True)
    state = r.speaker.display_state()
    assert (state.ringing, state.secondary) == ("alarm", "21°C")


async def test_display_flags_and_modes(rig) -> None:
    r = await rig()
    state = r.speaker.display_state()
    assert (state.alarm_set, state.clock_24h, state.mode) == (False, False, None)
    assert abs(state.now - datetime.now()) < timedelta(seconds=5)
    r.scheduler.add_alarm(7, 0, WEEKDAYS)
    assert r.speaker.display_state().alarm_set
    r.speaker.display_mode = "net"
    assert r.speaker.display_state().mode == "net"
    r.speaker.display_mode = None
    assert r.speaker.display_state().mode is None


# ---------------------------------------------------------------------------
# Announcements and status


async def test_say_speaks_an_announcement(rig) -> None:
    r = await rig()
    await r.speaker.say("Dinner is ready")
    assert r.pipeline.spoken == ["Dinner is ready"]
    await wait_for(lambda: r.leds.statuses == [Status.IDLE, Status.SPEAKING, Status.IDLE])
    assert r.player.audio == [b"TTS:Dinner is ready"]
    assert r.speaker.state is AssistantState.IDLE


async def test_say_reports_a_tts_failure(rig) -> None:
    r = await rig()
    r.pipeline.fail_speak = True
    with pytest.raises(PipelineFailure):
        await r.speaker.say("Dinner is ready")
    await asyncio.sleep(0.01)
    assert r.player.played == []


async def test_play_url_downloads_and_plays_with_music_ducked(rig, tmp_path, amixer) -> None:
    async def chime(request: web.Request) -> web.Response:
        return web.Response(body=b"ID3 CHIME", content_type="audio/mpeg")

    media = web.Application()
    media.router.add_get("/chime.mp3", chime)
    async with web_server(media) as base, aiohttp.ClientSession() as session:
        r = await rig(config=ducking_config(tmp_path), session=session)
        r.player.snapshot = lambda: lines(amixer)
        await r.speaker.play_url(f"{base}/chime.mp3")
        await wait_for(lambda: RESTORED in lines(amixer))
        assert r.player.audio == [b"ID3 CHIME"]
        assert r.player.snapshots == [DUCKED]  # lowered while it played
        assert lines(amixer) == [*DUCKED, RESTORED]
        await wait_for(lambda: r.leds.statuses == [Status.IDLE, Status.SPEAKING, Status.IDLE])
        with pytest.raises(aiohttp.ClientResponseError):
            await r.speaker.play_url(f"{base}/missing.mp3")


async def test_play_url_fetches_home_assistant_media(rig) -> None:
    ha = FakeHomeAssistant(files={"/api/tts_proxy/abc.mp3": b"ID3 SPEECH"})
    r = await rig(homeassistant=ha)
    await r.speaker.play_url("/api/tts_proxy/abc.mp3")
    await wait_for(lambda: r.player.audio == [b"ID3 SPEECH"])
    with pytest.raises(HomeAssistantError):
        await r.speaker.play_url("/api/tts_proxy/missing.mp3")


async def test_music_is_ducked_during_a_conversation(rig, tmp_path, amixer) -> None:
    r = await rig(["hello"], config=ducking_config(tmp_path))
    r.player.snapshot = lambda: lines(amixer)
    await r.converse()
    assert r.player.snapshots == [DUCKED]
    assert lines(amixer) == [*DUCKED, RESTORED]


async def test_status(rig) -> None:
    r = await rig()
    r.speaker.temperature = "21°C"
    timer = r.scheduler.add_timer(90, "tea")
    r.clock.advance(12.34)
    alarm = r.scheduler.add_alarm(6, 30, WEEKDAYS)
    await r.speaker.change_volume(level=35)
    status = r.speaker.status()
    (entry,) = status.pop("alarms")
    assert status == {
        "name": "Open Speaker",
        "state": "idle",
        "volume": 35,
        "speaker_muted": False,
        "mic_muted": False,
        "ringing": [],
        "temperature": "21°C",
        "timers": [{"id": timer.id, "name": "tea", "seconds": 90, "remaining": 77.7}],
    }
    next_at = datetime.fromisoformat(entry.pop("next"))
    assert entry == {"id": alarm.id, "time": "06:30", "repeat": [0, 1, 2, 3, 4]}
    assert (next_at.hour, next_at.minute, next_at.second, next_at.weekday() < 5) == (6, 30, 0, True)
    await ring(r)
    assert r.speaker.status()["ringing"] == ["timer"]


# ---------------------------------------------------------------------------
# Starting and stopping


async def test_settings_are_saved_and_restored(rig, tmp_path) -> None:
    config = config_for(tmp_path)
    first = await rig(config=config)
    await first.speaker.change_volume(level=70)
    await first.speaker.set_speaker_muted(True)
    await first.speaker.set_mic_muted(True)
    assert first.settings() == {"volume": 70, "speaker_muted": True, "mic_muted": True}
    await first.speaker.shutdown()
    again = await rig(config=config)
    speaker = again.speaker
    assert (speaker.volume.level, speaker.volume.muted, speaker.mic_muted) == (70, True, True)
    assert again.mic.paused
    assert again.player.software_gain == 0
    assert again.leds.status is Status.MUTED
    assert again.volume_led.shown[-1] == (70, True)


async def test_unreadable_settings_are_ignored(rig, tmp_path) -> None:
    config = config_for(tmp_path, audio={"output": {"volume_control": None}, "initial_volume": 30})
    config.settings_file.parent.mkdir(parents=True)
    config.settings_file.write_text("{not json")
    r = await rig(config=config)
    speaker = r.speaker
    assert (speaker.volume.level, speaker.volume.muted, speaker.mic_muted) == (30, False, False)
    assert r.player.software_gain == pytest.approx(0.09)


async def test_disabled_or_missing_earcons_are_skipped(rig, tmp_path) -> None:
    config = config_for(tmp_path, sounds={"wake": None, "done": str(tmp_path / "missing.wav")})
    r = await rig(["stop"], config=config)
    await r.converse()
    assert r.speaker.sounds["wake"] is None
    assert r.speaker.sounds["done"] is None
    assert r.player.played == []


async def test_start_survives_a_failing_wake_word_display_and_buttons(rig) -> None:
    wake, display, buttons = FakeWake(fail=True), FakeDisplay(fail=True), FakeButtons(fail=True)
    r = await rig(["what time is it"], wake=wake, display=display, buttons=buttons)
    assert r.speaker.wake is None
    assert r.speaker.c.display is None
    assert r.leds.started
    r.speaker.on_button("action", ButtonEvent.SHORT_PRESS)  # the button still works
    await wait_for(lambda: r.pipeline.responded == ["what time is it"])
    await wait_for(lambda: not r.speaker.conversation_active)
    assert r.player.audio == [b"REPLY"]
    assert r.speaker.display_state().secondary is None
    await asyncio.wait_for(r.speaker.shutdown(), 2)
    assert buttons.closed
    assert r.mic.closed


async def test_shutdown_cancels_everything_and_releases_the_hardware(rig, tmp_path) -> None:
    ha = FakeHomeAssistant(state=SENSOR)
    buttons = FakeButtons()
    config = config_for(tmp_path, display={"temperature": {"entity": "sensor.outside"}})
    r = await rig(stream=False, homeassistant=ha, buttons=buttons, config=config)
    await ring(r)
    assert r.speaker.start_conversation()
    await wait_for(lambda: r.speaker.state is AssistantState.LISTENING)
    await r.speaker.say("goodbye")
    await asyncio.wait_for(r.speaker.shutdown(), 2)
    assert not r.speaker.conversation_active
    assert r.speaker.ringing == []
    assert r.mic.closed
    assert r.wake.stopped
    assert r.display.stopped
    assert r.leds.stopped
    assert r.volume_led.closed
    assert buttons.closed
    assert ha.closed
    assert r.player.stopped
    assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_run_until_asked_to_stop(rig) -> None:
    r = await rig(start=False, stream=False)
    task = asyncio.create_task(r.speaker.run())
    await wait_for(lambda: r.wake.started and r.leds.started)
    assert not task.done()
    r.speaker.request_stop()
    await asyncio.wait_for(task, 2)
    assert r.mic.closed
    assert r.wake.stopped


async def test_night_mode_dims_the_lights(rig) -> None:
    r = await rig()
    r.speaker.on_night(True)
    assert r.leds.night
    assert r.volume_led.night
    assert r.volume_led.shown[-1] == (50, False)
    r.speaker.on_night(False)
    assert not r.leds.night
    assert not r.volume_led.night
