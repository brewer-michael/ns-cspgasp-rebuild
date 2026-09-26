"""Local pipeline: the speaker calls your speech and language servers directly."""

from __future__ import annotations

from collections.abc import AsyncIterator

from ..agents import AgentChain, AgentError
from ..audio.playback import AudioSource
from ..config import VadConfig
from ..stt import SpeechToText, SttError
from ..tts import TextToSpeech, TtsError
from ..vad import Segment, SpeechDetector, VoiceCommandSegmenter
from . import Conversation, Pipeline, PipelineFailure, Reply


class LocalPipeline(Pipeline):
    def __init__(
        self,
        stt: SpeechToText,
        agents: AgentChain,
        tts: TextToSpeech,
        vad: VadConfig,
        stt_language: str | None = None,
        detector: SpeechDetector | None = None,
    ) -> None:
        self.stt = stt
        self.agents = agents
        self.tts = tts
        self.vad = vad
        self.stt_language = stt_language
        self.detector = detector

    async def listen(self, audio: AsyncIterator[bytes], conversation: Conversation) -> str | None:
        segmenter = VoiceCommandSegmenter.from_config(self.vad, self.detector)
        buffered: list[bytes] = []

        # Only contact the speech-to-text server once someone is actually talking.
        async for chunk in audio:
            buffered.append(chunk)
            state = segmenter.process(chunk)
            if state is Segment.SPEAKING or state.finished:
                break
        if not segmenter.speech_started:
            return None

        async def speech() -> AsyncIterator[bytes]:
            for chunk in buffered:
                yield chunk
            if segmenter.state.finished:
                return
            async for chunk in audio:
                yield chunk
                if segmenter.process(chunk).finished:
                    return

        try:
            text = await self.stt.transcribe(speech(), self.stt_language or conversation.language)
        except SttError as err:
            raise PipelineFailure(str(err)) from err
        return text or None

    async def respond(self, text: str, conversation: Conversation) -> Reply:
        try:
            answer = await self.agents.process(text, conversation.language, conversation.id)
        except AgentError as err:
            raise PipelineFailure(str(err)) from err
        conversation.id = answer.conversation_id or conversation.id
        audio = await self.speak(answer.text, conversation.language) if answer.text else None
        return Reply(answer.text, audio, answer.continue_conversation)

    async def speak(self, text: str, language: str) -> AudioSource | None:
        try:
            return await self.tts.synthesize(text, language)
        except TtsError as err:
            raise PipelineFailure(str(err)) from err
