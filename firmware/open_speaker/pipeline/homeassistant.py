"""Home Assistant pipeline: an Assist pipeline does speech-to-text, the agent and TTS.

Which models those stages use (for example Whisper, Piper and an Ollama agent on
another machine) is configured in Home Assistant under Settings > Voice assistants.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from ..agents.homeassistant import speech_text
from ..audio.playback import AudioSource, EncodedAudio
from ..config import VadConfig
from ..const import SAMPLE_RATE, SAMPLE_WIDTH
from ..homeassistant import HomeAssistant, HomeAssistantError, PipelineError
from . import Conversation, Pipeline, PipelineFailure, Reply

_NOTHING_HEARD = {"stt-no-text-recognized"}


class HomeAssistantPipeline(Pipeline):
    def __init__(
        self, homeassistant: HomeAssistant, vad: VadConfig, pipeline_id: str | None = None
    ) -> None:
        self.ha = homeassistant
        self.vad = vad
        self.pipeline_id = pipeline_id

    async def _run(self, start: str, end: str, data: dict[str, Any], **kwargs: Any):
        events = self.ha.run_pipeline(start, end, data, pipeline=self.pipeline_id, **kwargs)
        try:
            # aclosing: stop streaming audio and cancel the run promptly on error.
            async with contextlib.aclosing(events):
                async for event in events:
                    event_data = event.get("data") or {}
                    if event.get("type") == "error":
                        raise PipelineError(
                            str(event_data.get("code", "unknown")),
                            str(event_data.get("message", "")),
                        )
                    yield event.get("type"), event_data
        except PipelineError as err:
            if err.code in _NOTHING_HEARD:
                raise
            raise PipelineFailure(f"Home Assistant pipeline error {err}") from err
        except HomeAssistantError as err:
            raise PipelineFailure(str(err)) from err

    async def listen(self, audio: AsyncIterator[bytes], conversation: Conversation) -> str | None:
        heard = {"speech": False}
        vad = self.vad

        async def limited() -> AsyncIterator[bytes]:
            # Home Assistant decides when speech ends; we only enforce time limits.
            elapsed = 0.0
            async for chunk in audio:
                yield chunk
                elapsed += len(chunk) / (SAMPLE_RATE * SAMPLE_WIDTH)
                if elapsed >= vad.max_seconds:
                    return
                if not heard["speech"] and elapsed >= vad.speech_start_timeout:
                    return

        text: str | None = None
        try:
            async for event_type, data in self._run(
                "stt", "stt", {"sample_rate": SAMPLE_RATE}, audio=limited()
            ):
                if event_type == "stt-vad-start":
                    heard["speech"] = True
                elif event_type == "stt-end":
                    text = (data.get("stt_output") or {}).get("text")
        except PipelineError:  # nothing recognized
            return None
        return text.strip() if text and text.strip() else None

    async def respond(self, text: str, conversation: Conversation) -> Reply:
        reply = ""
        url: str | None = None
        continue_conversation = False
        try:
            async for event_type, data in self._run(
                "intent", "tts", {"text": text}, conversation_id=conversation.id
            ):
                if event_type == "run-start":
                    conversation.id = data.get("conversation_id") or conversation.id
                elif event_type == "intent-end":
                    output = data.get("intent_output") or {}
                    reply = speech_text(output.get("response") or {})
                    continue_conversation = bool(output.get("continue_conversation"))
                    conversation.id = output.get("conversation_id") or conversation.id
                elif event_type == "tts-end":
                    url = (data.get("tts_output") or {}).get("url")
        except PipelineError as err:
            raise PipelineFailure(f"Home Assistant pipeline error {err}") from err
        audio = await self._download(url) if url else None
        return Reply(reply, audio, continue_conversation)

    async def speak(self, text: str, language: str) -> AudioSource | None:
        url: str | None = None
        try:
            async for event_type, data in self._run("tts", "tts", {"text": text}):
                if event_type == "tts-end":
                    url = (data.get("tts_output") or {}).get("url")
        except PipelineError as err:
            raise PipelineFailure(f"Home Assistant pipeline error {err}") from err
        return await self._download(url) if url else None

    async def _download(self, url: str) -> EncodedAudio:
        try:
            return EncodedAudio(await self.ha.fetch(url))
        except HomeAssistantError as err:
            raise PipelineFailure(f"could not download speech audio: {err}") from err
