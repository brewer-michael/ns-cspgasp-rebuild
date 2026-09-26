"""Wake word detection engines.

``microwakeword`` and ``openwakeword`` run on the speaker itself; ``wyoming`` streams
audio to a Wyoming wake word server (for example ``wyoming-openwakeword``) running on
the speaker or anywhere on your network.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import WakeConfig


class WakeWordEngine(ABC):
    """Consumes 16 kHz mono audio and reports detected wake words."""

    name: str = "wake word"

    async def start(self) -> None:  # noqa: B027 - optional hook
        """Load models / open connections."""

    async def stop(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""

    @abstractmethod
    async def process(self, chunk: bytes) -> str | None:
        """Feed audio; return the wake word's name when it was just detected."""

    async def reset(self) -> None:  # noqa: B027 - optional hook
        """Forget buffered audio (called after a detection or playback)."""


def create_wake_engine(config: WakeConfig) -> WakeWordEngine | None:
    if config.engine == "none":
        return None
    if config.engine == "wyoming":
        from .wyoming import WyomingWakeEngine

        assert config.uri is not None
        return WyomingWakeEngine(config.uri, config.names)
    from .local import MicroWakeWordEngine, OpenWakeWordEngine

    if config.engine == "microwakeword":
        return MicroWakeWordEngine(config.model, config.threshold)
    return OpenWakeWordEngine(config.model, config.threshold)


__all__ = ["WakeWordEngine", "create_wake_engine"]
