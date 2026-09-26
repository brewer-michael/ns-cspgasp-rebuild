"""Wake word detection on a Wyoming server (on the speaker or elsewhere on the LAN)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from wyoming.audio import AudioChunk, AudioStart
from wyoming.client import AsyncClient
from wyoming.error import Error
from wyoming.wake import Detect, Detection

from ..const import SAMPLE_CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from . import WakeWordEngine

_LOGGER = logging.getLogger(__name__)


class WyomingWakeEngine(WakeWordEngine):
    """Streams microphone audio continuously and collects ``detection`` events.

    While the server is unreachable, audio is dropped and the connection is retried in
    the background with backoff, so the microphone loop never blocks.
    """

    def __init__(
        self,
        uri: str,
        names: list[str] | None = None,
        connect_timeout: float = 5.0,
        max_backoff: float = 30.0,
    ) -> None:
        self.uri = uri
        self.names = names or None
        self.name = ", ".join(names) if names else "wake word"
        self.connect_timeout = connect_timeout
        self.max_backoff = max_backoff
        self._client: AsyncClient | None = None
        self._reader: asyncio.Task[None] | None = None
        self._connecting: asyncio.Task[None] | None = None
        self._detections: asyncio.Queue[str] = asyncio.Queue()
        self._backoff = 1.0
        self._next_attempt = 0.0
        self._stopped = False

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def start(self) -> None:
        self._stopped = False
        self._schedule_connect()

    async def stop(self) -> None:
        self._stopped = True
        if self._connecting is not None:
            self._connecting.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._connecting
        await self._disconnect()

    def _schedule_connect(self) -> None:
        if self._stopped or self._client is not None:
            return
        if self._connecting is not None and not self._connecting.done():
            return
        if time.monotonic() < self._next_attempt:
            return
        self._connecting = asyncio.create_task(self._connect())

    async def _connect(self) -> None:
        client = AsyncClient.from_uri(self.uri, connect_timeout=self.connect_timeout)
        try:
            await client.connect()
            await client.write_event(Detect(names=self.names).event())
            await client.write_event(
                AudioStart(rate=SAMPLE_RATE, width=SAMPLE_WIDTH, channels=SAMPLE_CHANNELS).event()
            )
        except (OSError, TimeoutError) as err:
            self._next_attempt = time.monotonic() + self._backoff
            _LOGGER.warning(
                "Wake word server %s unavailable (%s); retrying in %.0f s",
                self.uri,
                err,
                self._backoff,
            )
            self._backoff = min(self._backoff * 2, self.max_backoff)
            with contextlib.suppress(Exception):
                await client.disconnect()
            return

        _LOGGER.info("Connected to wake word server %s", self.uri)
        self._backoff = 1.0
        self._client = client
        self._reader = asyncio.create_task(self._read_events(client))

    async def _read_events(self, client: AsyncClient) -> None:
        try:
            while True:
                event = await client.read_event()
                if event is None:
                    break
                if Detection.is_type(event.type):
                    detection = Detection.from_event(event)
                    self._detections.put_nowait(detection.name or self.name)
                elif Error.is_type(event.type):
                    _LOGGER.error("Wake word server error: %s", Error.from_event(event).text)
        except (OSError, asyncio.IncompleteReadError) as err:
            _LOGGER.debug("Wake word connection read failed: %s", err)
        if not self._stopped:
            _LOGGER.warning("Lost connection to wake word server %s", self.uri)
        if self._client is client:
            self._client = None
            with contextlib.suppress(Exception):
                await client.disconnect()

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()

    async def process(self, chunk: bytes) -> str | None:
        client = self._client
        if client is None:
            self._schedule_connect()
        else:
            try:
                await client.write_event(
                    AudioChunk(
                        rate=SAMPLE_RATE,
                        width=SAMPLE_WIDTH,
                        channels=SAMPLE_CHANNELS,
                        audio=chunk,
                    ).event()
                )
            except (OSError, RuntimeError) as err:
                _LOGGER.warning("Lost connection to wake word server %s: %s", self.uri, err)
                await self._disconnect()
        try:
            return self._detections.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def reset(self) -> None:
        while not self._detections.empty():
            self._detections.get_nowait()
