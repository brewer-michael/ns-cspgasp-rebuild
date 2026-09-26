"""Voice pipelines: from recorded speech to a spoken reply.

The speaker splits every interaction into ``listen`` (speech -> text) and ``respond``
(text -> reply audio) so that on-device commands such as timers can be handled in
between, whichever pipeline is used.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ..audio.playback import AudioSource


class PipelineFailure(RuntimeError):
    """A stage failed (as opposed to simply hearing nothing)."""


@dataclass
class Conversation:
    """State that carries over between turns of one conversation."""

    language: str
    id: str | None = None


@dataclass
class Reply:
    text: str
    audio: AudioSource | None = None
    continue_conversation: bool = False


class Pipeline(ABC):
    @abstractmethod
    async def listen(self, audio: AsyncIterator[bytes], conversation: Conversation) -> str | None:
        """Transcribe one spoken command; None when nothing was said."""

    @abstractmethod
    async def respond(self, text: str, conversation: Conversation) -> Reply:
        """Answer (and act on) a command."""

    @abstractmethod
    async def speak(self, text: str, language: str) -> AudioSource | None:
        """Text-to-speech only (announcements and on-device replies)."""


__all__ = ["Conversation", "Pipeline", "PipelineFailure", "Reply"]
