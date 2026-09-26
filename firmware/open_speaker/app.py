"""The speaker application: ties audio, wake word, voice pipeline, hardware and schedule."""

from __future__ import annotations

import asyncio
import contextlib
import enum
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp

from .audio.playback import AudioPlayer, EncodedAudio, PcmFormat, PlaybackError
from .audio.sounds import Sound, load_sound
from .audio.volume import Ducker, Volume
from .config import Config
from .hardware.buttons import ButtonEvent
from .homeassistant import HomeAssistant, HomeAssistantError
from .intents import (
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
    describe_clock,
    describe_duration,
    recognize,
    recognize_answer,
)
from .pipeline import Conversation, Pipeline, PipelineFailure, Reply
from .timers import Alarm, Ring, Scheduler
from .ui import DisplayState, format_countdown

_LOGGER = logging.getLogger(__name__)

MAX_TURNS = 5
# How long a swapped-in value (volume, mic on/off...) replaces the temperature.
SWAP_SECONDS = 2.5


class AssistantState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class Answer:
    reply: Reply
    question: Intent | None = None  # a follow-up question awaiting an answer
    sound: str | None = None  # earcon to play when there is nothing to say


@dataclass
class Components:
    """Everything the speaker drives; tests pass fakes for any of these."""

    mic: Any
    player: AudioPlayer
    pipeline: Pipeline | None
    wake: Any = None
    homeassistant: HomeAssistant | None = None
    scheduler: Scheduler | None = None
    display: Any = None
    leds: Any = None
    volume_led: Any = None
    buttons: Any = None
    session: aiohttp.ClientSession | None = None
    extra_tasks: list[Any] = field(default_factory=list)


def format_temperature(state: dict[str, Any] | None, unit_override: str | None) -> str | None:
    """Home Assistant sensor or weather entity -> '72°F'."""
    if not state:
        return None
    attributes = state.get("attributes") or {}
    if str(state.get("entity_id", "")).startswith("weather."):
        value = attributes.get("temperature")
        unit = attributes.get("temperature_unit") or ""
    else:
        value = state.get("state")
        unit = attributes.get("unit_of_measurement") or ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    unit = unit_override if unit_override is not None else unit
    text = f"{round(number)}{unit if unit.startswith('°') else '°' + unit if unit else '°'}"
    return text.replace("-", "\u2212")  # typographic minus


class Speaker:
    def __init__(self, config: Config, components: Components) -> None:
        self.config = config
        self.c = components
        self.mic = components.mic
        self.player = components.player
        self.pipeline = components.pipeline
        self.wake = components.wake
        self.scheduler = components.scheduler
        output = config.audio.output
        self.volume = Volume(self.player, output.volume_control, output.mixer_card)
        self.ducker = Ducker(output.duck_control, output.mixer_card, output.duck_volume)
        self.sounds: dict[str, Sound | None] = {}

        self.state = AssistantState.IDLE
        self.mic_muted = False
        self.connected = True
        self.temperature: str | None = None
        self.ringing: list[Ring] = []
        # A mode that takes over the whole display, e.g. "net" while pairing.
        self.display_mode: str | None = None

        self._listen_queue: asyncio.Queue[bytes] | None = None
        self._conversation: asyncio.Task[None] | None = None
        self._ring_task: asyncio.Task[None] | None = None
        self._ring_allowed = asyncio.Event()
        self._ring_allowed.set()
        self._refractory_until = 0.0
        self._swap_text: str | None = None
        self._swap_until = 0.0
        self._stopping = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []
        self._background: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ setup

    def _load_sounds(self) -> None:
        for name in ("wake", "done", "error", "alarm", "timer", "volume"):
            spec = getattr(self.config.sounds, name)
            try:
                self.sounds[name] = load_sound(spec)
            except (OSError, ValueError, KeyError) as err:
                _LOGGER.error("Cannot load sound %s=%r: %s", name, spec, err)
                self.sounds[name] = None

    def _load_settings(self) -> dict[str, Any]:
        try:
            return json.loads(self.config.settings_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as err:
            _LOGGER.warning("Ignoring unreadable settings file: %s", err)
            return {}

    def _save_settings(self) -> None:
        data = {
            "volume": self.volume.level,
            "speaker_muted": self.volume.muted,
            "mic_muted": self.mic_muted,
        }
        path = self.config.settings_file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(path)
        except OSError as err:
            _LOGGER.warning("Could not save settings: %s", err)

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        """Run a coroutine in the background, keeping a reference until it finishes."""
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def start(self) -> None:
        self._load_sounds()
        settings = self._load_settings()
        await self.volume.setup(int(settings.get("volume", self.config.audio.initial_volume)))
        if settings.get("speaker_muted"):
            await self.volume.set_muted(True)
        if settings.get("mic_muted"):
            self.mic_muted = True
            self.mic.pause()

        if self.wake is not None:
            try:
                await self.wake.start()
            except Exception as err:  # e.g. model library not installed
                _LOGGER.error("Wake word disabled (the action button still works): %s", err)
                self.wake = None
        if self.scheduler is not None:
            self.scheduler.on_ring = self._on_ring
            await self.scheduler.start()
        if self.c.leds is not None:
            self.c.leds.start()
        if self.c.display is not None:
            try:
                await self.c.display.start()
            except Exception as err:  # e.g. no OLED on the I2C bus
                _LOGGER.error("Display unavailable: %s", err)
                self.c.display = None
        if self.c.buttons is not None:
            try:
                self.c.buttons.on_event = self.on_button
                self.c.buttons.start()
            except Exception as err:  # no GPIO (e.g. running on a PC)
                _LOGGER.warning("Buttons unavailable: %s", err)
        self._update_indicators()

        self._tasks.append(asyncio.create_task(self._mic_loop(), name="microphone"))
        self._tasks.append(asyncio.create_task(self._poll_temperature(), name="temperature"))
        for coro in self.c.extra_tasks:
            self._tasks.append(asyncio.create_task(coro))
        _LOGGER.info("%s is ready", self.config.name)

    async def run(self) -> None:
        await self.start()
        try:
            await self._stopping.wait()
        finally:
            await self.shutdown()

    def request_stop(self) -> None:
        self._stopping.set()

    async def shutdown(self) -> None:
        for task in [*self._tasks, self._conversation, self._ring_task, *self._background]:
            if task is not None and not task.done():
                task.cancel()
        for task in [*self._tasks, self._conversation, self._ring_task, *self._background]:
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self.player.stop()
        with contextlib.suppress(Exception):
            await self.mic.close()
        if self.wake is not None:
            with contextlib.suppress(Exception):
                await self.wake.stop()
        if self.scheduler is not None:
            await self.scheduler.stop()
        if self.c.buttons is not None:
            self.c.buttons.close()
        if self.c.display is not None:
            await self.c.display.stop()
        if self.c.leds is not None:
            await self.c.leds.stop()
        if self.c.volume_led is not None:
            self.c.volume_led.close()
        if self.c.homeassistant is not None:
            await self.c.homeassistant.close()
        _LOGGER.info("Stopped")

    # ------------------------------------------------------- state and output

    def _set_state(self, state: AssistantState) -> None:
        if state is not self.state:
            self.state = state
            self._update_indicators()

    def _update_indicators(self) -> None:
        from .hardware.leds import Status

        if self.c.leds is not None:
            if self.ringing:
                status = Status.ALARM
            elif self.state is not AssistantState.IDLE:
                status = Status[self.state.name]
            elif self.mic_muted:
                status = Status.MUTED
            else:
                status = Status.IDLE
            self.c.leds.set(status)
        if self.c.volume_led is not None:
            self.c.volume_led.show(self.volume.level, self.volume.muted)
        if self.c.display is not None:
            self.c.display.refresh()

    def _swap(self, text: str) -> None:
        """Show ``text`` in the temperature slot for a moment."""
        self._swap_text = text
        self._swap_until = time.monotonic() + SWAP_SECONDS
        if self.c.display is not None:
            self.c.display.refresh()

    def on_night(self, night: bool) -> None:
        if self.c.leds is not None:
            self.c.leds.set_night(night)
        if self.c.volume_led is not None:
            self.c.volume_led.night = night
            self.c.volume_led.show(self.volume.level, self.volume.muted)

    def display_state(self) -> DisplayState:
        """Time always; the temperature slot shows the most relevant value."""
        ringing = None
        if self.ringing:
            ringing = "alarm" if any(r.kind == "alarm" for r in self.ringing) else "timer"
        secondary = self.temperature
        swap = False
        timers = self.scheduler.timers() if self.scheduler is not None else []
        if self._swap_text is not None and time.monotonic() < self._swap_until:
            secondary, swap = self._swap_text, True
        elif ringing == "timer":
            secondary = "End"
        elif timers:
            secondary = format_countdown(self.scheduler.remaining(timers[0]))  # type: ignore[union-attr]
        return DisplayState(
            now=datetime.now(),
            clock_24h=self.config.display.clock_24h,
            alarm_set=self.scheduler is not None and self.scheduler.next_alarm() is not None,
            secondary=secondary,
            swap=swap,
            ringing=ringing,
            mode=self.display_mode,
        )

    async def play_sound(self, name: str) -> None:
        sound = self.sounds.get(name)
        if sound is None:
            return
        try:
            await self.player.play_pcm(
                sound.pcm, PcmFormat(sound.rate), gain=self.config.audio.output.sound_volume
            )
        except PlaybackError as err:
            _LOGGER.error("Cannot play %s sound: %s", name, err)

    # ---------------------------------------------------------- microphone

    async def _mic_loop(self) -> None:
        errors = 0
        async for chunk in self.mic.chunks():
            queue = self._listen_queue
            if queue is not None:
                queue.put_nowait(chunk)
                continue
            if self.wake is None or not self._wake_active():
                continue
            try:
                name = await self.wake.process(chunk)
                errors = 0
            except Exception as err:
                errors += 1
                if errors in (1, 100):
                    _LOGGER.error("Wake word engine error: %s", err)
                continue
            if name and time.monotonic() >= self._refractory_until:
                _LOGGER.info("Wake word detected: %s", name)
                self.start_conversation()

    def _wake_active(self) -> bool:
        if self.mic_muted or self.conversation_active:
            return False
        # Ignore our own announcements, but listen during alarms so "stop" works.
        return bool(self.ringing) or not self.player.is_playing

    @property
    def conversation_active(self) -> bool:
        return self._conversation is not None and not self._conversation.done()

    # -------------------------------------------------------- conversation

    def start_conversation(self) -> bool:
        if self.pipeline is None:
            return False
        if self.mic_muted:
            self._swap("mic off")
            self._spawn(self.play_sound("error"))
            return False
        if self.conversation_active:
            return False
        self._conversation = asyncio.create_task(self._converse(), name="conversation")
        return True

    def cancel_conversation(self) -> bool:
        if not self.conversation_active:
            return False
        assert self._conversation is not None
        self._conversation.cancel()
        self.player.stop()
        return True

    async def _converse(self) -> None:
        assert self.pipeline is not None
        self._pause_ringing()
        await self.ducker.duck()
        conversation = Conversation(language=self.config.language)
        question: Intent | None = None
        try:
            for turn in range(MAX_TURNS):
                text = await self._listen(conversation)
                if not text:
                    if turn == 0:
                        await self.play_sound("error")
                    break
                _LOGGER.info("Heard: %s", text)
                self._set_state(AssistantState.THINKING)
                answer = await self._answer(text, conversation, question)
                question = answer.question
                self.connected = True
                await self._deliver(answer)
                follow_up = answer.reply.continue_conversation and self.config.pipeline.follow_up
                if not (follow_up or question is not None):
                    break
        except PipelineFailure as err:
            _LOGGER.error("Voice pipeline failed: %s", err)
            self.connected = False
            self._set_state(AssistantState.ERROR)
            await self.play_sound("error")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Conversation failed")
            self._set_state(AssistantState.ERROR)
            await self.play_sound("error")
        finally:
            self._listen_queue = None
            with contextlib.suppress(Exception):
                await self.ducker.restore()
            self._set_state(AssistantState.IDLE)
            self._refractory_until = time.monotonic() + self.config.wake.refractory_seconds
            if self.wake is not None:
                with contextlib.suppress(Exception):
                    await self.wake.reset()
            self._resume_ringing()

    async def _listen(self, conversation: Conversation) -> str | None:
        assert self.pipeline is not None
        self._set_state(AssistantState.LISTENING)
        await self.play_sound("wake")
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._listen_queue = queue

        async def audio() -> AsyncIterator[bytes]:
            while True:
                yield await queue.get()

        try:
            return await self.pipeline.listen(audio(), conversation)
        finally:
            self._listen_queue = None

    async def _answer(
        self, text: str, conversation: Conversation, question: Intent | None
    ) -> Answer:
        assert self.pipeline is not None
        intent: Intent | None = None
        if self.config.pipeline.local_intents:
            if question is not None:
                intent = recognize_answer(question, text)
            if intent is None:
                intent = recognize(text)
        if intent is None:
            return Answer(await self.pipeline.respond(text, conversation))

        _LOGGER.info("Handling on the speaker: %s", intent)
        answer = await self.handle_intent(intent)
        if answer.reply.text:
            try:
                answer.reply.audio = await self.pipeline.speak(
                    answer.reply.text, conversation.language
                )
            except PipelineFailure as err:
                # The action itself worked; only the spoken confirmation failed.
                _LOGGER.warning("Could not speak the reply: %s", err)
                answer.sound = answer.sound or "done"
        return answer

    async def _deliver(self, answer: Answer) -> None:
        reply = answer.reply
        if reply.text:
            _LOGGER.info("Reply: %s", reply.text)
        if reply.audio is not None:
            self._set_state(AssistantState.SPEAKING)
            try:
                await self.player.play(reply.audio)
            except PlaybackError as err:
                _LOGGER.error("Cannot play the reply: %s", err)
                await self.play_sound("error")
        elif answer.sound:
            await self.play_sound(answer.sound)
        elif not reply.text:
            await self.play_sound("done")

    # ----------------------------------------------------- on-device intents

    async def handle_intent(self, intent: Intent) -> Answer:
        scheduler = self.scheduler
        clock_24h = self.config.display.clock_24h

        def say(text: str, question: Intent | None = None) -> Answer:
            return Answer(Reply(text), question=question)

        if isinstance(intent, Stop):
            if self.ringing:
                self.stop_ringing()
                return Answer(Reply(""), sound="done")
            if intent.alarm and scheduler is not None and scheduler.next_alarm() is not None:
                return await self.handle_intent(CancelAlarm())
            return Answer(Reply(""), sound="done")

        if isinstance(intent, Snooze):
            if self.snooze(intent.minutes):
                minutes = intent.minutes or self.config.timers.snooze_minutes
                return say(f"Snoozing for {describe_duration(minutes * 60)}.")
            return say("There's no alarm to snooze.")

        if isinstance(intent, ChangeVolume):
            await self.change_volume(steps=intent.steps, level=intent.level, sound=False)
            return Answer(Reply(""), sound="volume")

        if scheduler is None:
            return say("Timers and alarms are turned off on this speaker.")

        if isinstance(intent, AskTimerDuration):
            return say("For how long?", question=intent)

        if isinstance(intent, StartTimer):
            scheduler.add_timer(intent.seconds, intent.name)
            what = f"{intent.name} timer" if intent.name else "Timer"
            return say(f"{what.capitalize()} set for {describe_duration(intent.seconds)}.")

        if isinstance(intent, CancelTimer):
            if not scheduler.timers():
                return say("There's no timer running.")
            cancelled = scheduler.cancel_timers(intent.name, intent.all)
            if not cancelled:
                return say(f"I couldn't find a {intent.name} timer.")
            if len(cancelled) > 1:
                return say(f"{len(cancelled)} timers cancelled.")
            return say(f"{cancelled[0].label.capitalize()} cancelled.")

        if isinstance(intent, TimerStatus):
            timers = scheduler.find_timers(intent.name)
            if not timers:
                return say("There's no timer running.")
            parts = [
                f"{describe_duration(scheduler.remaining(t))} left"
                + (f" on the {t.label}" if len(timers) > 1 or t.name else "")
                for t in timers[:3]
            ]
            return say("; ".join(parts).capitalize() + ".")

        if isinstance(intent, AskAlarmTime):
            return say("What time should I set the alarm for?", question=intent)

        if isinstance(intent, SetAlarm):
            alarm = scheduler.add_alarm(
                intent.hour, intent.minute, intent.repeat, intent.day, intent.ambiguous
            )
            self._swap(describe_clock(alarm.hour, alarm.minute, clock_24h))
            return say(f"Alarm set for {self._when(alarm)}.")

        if isinstance(intent, CancelAlarm):
            if not scheduler.alarms():
                return say("You don't have any alarms.")
            cancelled = scheduler.cancel_alarms(
                intent.hour, intent.minute, intent.all, intent.ambiguous
            )
            if not cancelled:
                return say("I couldn't find that alarm.")
            if len(cancelled) > 1:
                return say(f"{len(cancelled)} alarms cancelled.")
            return say(f"Alarm for {self._when(cancelled[0])} cancelled.")

        if isinstance(intent, AlarmStatus):
            alarms = scheduler.alarms()
            if not alarms:
                return say("You don't have any alarms.")
            if len(alarms) == 1:
                return say(f"Your alarm is set for {self._when(alarms[0])}.")
            listed = ", ".join(self._when(a) for a in alarms[:4])
            return say(f"You have {len(alarms)} alarms: {listed}.")

        return say("Sorry, I can't do that yet.")

    def _when(self, alarm: Alarm) -> str:
        clock_24h = self.config.display.clock_24h
        if alarm.repeat:
            return alarm.describe(clock_24h)
        at = datetime.fromtimestamp(alarm.next_at)
        text = describe_clock(alarm.hour, alarm.minute, clock_24h)
        days = (at.date() - datetime.now().date()).days
        if days == 1:
            return f"{text} tomorrow"
        if days > 1:
            return f"{text} on {at:%A}"
        return text

    # ---------------------------------------------------- timers and alarms

    async def _on_ring(self, ring: Ring) -> None:
        _LOGGER.info("%s is going off", ring.label.capitalize())
        self.ringing.append(ring)
        self._update_indicators()
        if self._ring_task is None or self._ring_task.done():
            self._ring_task = asyncio.create_task(self._ring_loop(), name="ringing")

    async def _ring_loop(self) -> None:
        deadline = time.monotonic() + self.config.timers.ring_timeout
        announced: set[str] = set()
        try:
            while self.ringing and time.monotonic() < deadline:
                await self._ring_allowed.wait()
                for ring in list(self.ringing):
                    if (
                        ring.kind == "timer"
                        and ring.label != "timer"
                        and ring.item_id not in announced
                    ):
                        announced.add(ring.item_id)
                        await self._announce(f"Your {ring.label} is done.")
                name = "alarm" if any(r.kind == "alarm" for r in self.ringing) else "timer"
                if self.sounds.get(name) is None:
                    await asyncio.sleep(1)
                else:
                    await self.play_sound(name)
        finally:
            self.ringing.clear()
            self._update_indicators()

    async def _announce(self, text: str) -> None:
        if self.pipeline is None:
            return
        try:
            audio = await asyncio.wait_for(self.pipeline.speak(text, self.config.language), 10)
            if audio is not None:
                await self.player.play(audio)
        except (PipelineFailure, PlaybackError, TimeoutError) as err:
            _LOGGER.debug("Could not announce %r: %s", text, err)

    def _pause_ringing(self) -> None:
        if self.ringing:
            self._ring_allowed.clear()
            self.player.stop()

    def _resume_ringing(self) -> None:
        self._ring_allowed.set()

    def stop_ringing(self) -> bool:
        if not self.ringing:
            return False
        self.ringing.clear()
        if self._ring_task is not None and not self._ring_task.done():
            self._ring_task.cancel()
        self.player.stop()
        self._update_indicators()
        return True

    def snooze(self, minutes: int | None = None) -> bool:
        if self.scheduler is None or not any(r.kind == "alarm" for r in self.ringing):
            return False
        self.scheduler.snooze(minutes or self.config.timers.snooze_minutes)
        self.stop_ringing()
        return True

    # --------------------------------------------------- volume and muting

    async def change_volume(
        self, steps: int = 0, level: int | None = None, sound: bool = True
    ) -> int:
        if self.volume.muted and (steps > 0 or level):
            await self.volume.set_muted(False)
        target = (
            level
            if level is not None
            else self.volume.level + steps * self.config.audio.volume_step
        )
        new_level = await self.volume.set(target)
        self._save_settings()
        self._swap(f"Vol {new_level}")
        if self.c.leds is not None:
            self.c.leds.flash_volume(new_level)
        self._update_indicators()
        if sound and not self.player.is_playing:
            self._spawn(self.play_sound("volume"))
        return new_level

    async def set_speaker_muted(self, muted: bool) -> None:
        await self.volume.set_muted(muted)
        self._save_settings()
        self._swap("Vol off" if muted else f"Vol {self.volume.level}")
        self._update_indicators()

    async def set_mic_muted(self, muted: bool) -> None:
        if muted == self.mic_muted:
            return
        self.mic_muted = muted
        if muted:
            self.mic.pause()
            self.cancel_conversation()
        else:
            self.mic.resume()
        self._save_settings()
        self._swap("mic off" if muted else "mic on")
        self._update_indicators()
        _LOGGER.info("Microphone %s", "muted" if muted else "unmuted")
        self._spawn(self.play_sound("error" if muted else "done"))

    # -------------------------------------------------------------- buttons

    def on_button(self, name: str, event: ButtonEvent) -> None:
        if name in ("volume_up", "volume_down"):
            if event in (ButtonEvent.PRESS, ButtonEvent.REPEAT):
                steps = 1 if name == "volume_up" else -1
                self._spawn(self.change_volume(steps=steps))
        elif name == "mute":
            if event is ButtonEvent.PRESS:
                if self.config.buttons.mute_function == "speaker":
                    self._spawn(self.set_speaker_muted(not self.volume.muted))
                else:
                    self._spawn(self.set_mic_muted(not self.mic_muted))
        elif name == "action":
            if event is ButtonEvent.SHORT_PRESS:
                self.action_tap()
            elif event is ButtonEvent.LONG_PRESS and self.ringing:
                self.stop_ringing()

    def action_tap(self) -> None:
        """The main button: snooze/stop alarms, interrupt, or start listening."""
        if self.ringing:
            if not self.snooze():
                self.stop_ringing()
        elif self.cancel_conversation():
            pass
        elif self.player.is_playing:
            self.player.stop()
        else:
            self.start_conversation()

    # ------------------------------------------------------------- actions

    def stop_everything(self) -> None:
        self.stop_ringing()
        self.cancel_conversation()
        self.player.stop()

    async def say(self, text: str) -> None:
        """Speak an announcement (e.g. from a Home Assistant automation)."""
        if self.pipeline is None:
            raise PipelineFailure("no voice pipeline configured")
        audio = await self.pipeline.speak(text, self.config.language)
        if audio is not None:
            self._spawn(self._play_announcement(audio))

    async def _play_announcement(self, audio: Any) -> None:
        await self.ducker.duck()
        self._set_state(AssistantState.SPEAKING)
        try:
            await self.player.play(audio)
        finally:
            await self.ducker.restore()
            if not self.conversation_active:
                self._set_state(AssistantState.IDLE)

    async def play_url(self, url: str) -> None:
        if self.c.homeassistant is not None and url.startswith("/"):
            data = await self.c.homeassistant.fetch(url)
        else:
            assert self.c.session is not None
            async with self.c.session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                data = await resp.read()
        self._spawn(self._play_announcement(EncodedAudio(data)))

    # ---------------------------------------------------------- temperature

    async def _poll_temperature(self) -> None:
        settings = self.config.display.temperature
        ha = self.c.homeassistant
        if not settings.entity or ha is None:
            return
        while True:
            try:
                state = await ha.get_state(settings.entity)
                self.temperature = format_temperature(state, settings.unit)
                if state is None:
                    _LOGGER.warning("Temperature entity %s not found", settings.entity)
                self.connected = True
            except HomeAssistantError as err:
                _LOGGER.debug("Temperature update failed: %s", err)
                self.connected = False
            if self.c.display is not None:
                self.c.display.refresh()
            await asyncio.sleep(settings.refresh_seconds)

    # --------------------------------------------------------------- status

    def status(self) -> dict[str, Any]:
        scheduler = self.scheduler
        return {
            "name": self.config.name,
            "state": self.state.value,
            "volume": self.volume.level,
            "speaker_muted": self.volume.muted,
            "mic_muted": self.mic_muted,
            "ringing": [r.label for r in self.ringing],
            "temperature": self.temperature,
            "timers": [
                {
                    "id": t.id,
                    "name": t.name,
                    "seconds": t.seconds,
                    "remaining": round(scheduler.remaining(t), 1),
                }
                for t in (scheduler.timers() if scheduler else [])
            ],
            "alarms": [
                {
                    "id": a.id,
                    "time": f"{a.hour:02d}:{a.minute:02d}",
                    "repeat": a.repeat,
                    "next": datetime.fromtimestamp(a.next_at).isoformat(timespec="minutes"),
                }
                for a in (scheduler.alarms() if scheduler else [])
            ],
        }
