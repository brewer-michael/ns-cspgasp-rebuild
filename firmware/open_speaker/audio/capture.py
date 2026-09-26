"""Microphone capture through an external recorder (``arecord`` by default)."""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import shlex
from collections.abc import AsyncIterator

from ..config import InputConfig
from ..const import SAMPLE_RATE
from .pcm import apply_gain, db_to_gain, to_int16_mono

_LOGGER = logging.getLogger(__name__)


def format_command(template: str, **values: object) -> list[str]:
    """Fill a command template, quoting each value, and split it into argv."""
    quoted = {key: shlex.quote(str(value)) for key, value in values.items()}
    return shlex.split(template.format(**quoted))


async def drain_stderr(stream: asyncio.StreamReader | None, lines: collections.deque[str]) -> None:
    """Keep reading a child's stderr so a full pipe can never stall it."""
    if stream is None:
        return
    while line := await stream.readline():
        lines.append(line.decode(errors="replace").rstrip())


async def terminate(proc: asyncio.subprocess.Process, timeout: float = 2.0) -> None:
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()


class Microphone:
    """Streams 16 kHz, 16-bit mono chunks from the configured recorder.

    Multi-channel input (two I2S mics share one bus as left/right) is reduced to one
    channel. The recorder is restarted with backoff if it exits, and fully stopped
    while paused, so a muted speaker does not capture any audio at all.
    """

    def __init__(self, config: InputConfig, restart_delay: float = 1.0) -> None:
        self.config = config
        self.restart_delay = restart_delay
        self.chunk_bytes = config.samples_per_chunk * config.channels * 2
        self._gain = db_to_gain(config.gain_db)
        self._proc: asyncio.subprocess.Process | None = None
        self._active = asyncio.Event()
        self._active.set()
        self._closed = False

    @property
    def argv(self) -> list[str]:
        return format_command(
            self.config.command,
            device=self.config.device,
            rate=SAMPLE_RATE,
            channels=self.config.channels,
        )

    @property
    def paused(self) -> bool:
        return not self._active.is_set()

    def pause(self) -> None:
        """Stop the recorder until :meth:`resume` (used for the privacy mute)."""
        self._active.clear()
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()

    def resume(self) -> None:
        self._active.set()

    async def close(self) -> None:
        self._closed = True
        self._active.set()
        if self._proc is not None:
            await terminate(self._proc)

    def process(self, data: bytes) -> bytes:
        mono = to_int16_mono(data, self.config.channels, self.config.channel)
        return apply_gain(mono, self._gain)

    async def chunks(self) -> AsyncIterator[bytes]:
        delay = self.restart_delay
        while not self._closed:
            await self._active.wait()
            if self._closed:
                break
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.argv,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as err:
                _LOGGER.error("Cannot start microphone recorder %r: %s", self.argv[0], err)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue

            self._proc = proc
            errors: collections.deque[str] = collections.deque(maxlen=10)
            stderr_task = asyncio.create_task(drain_stderr(proc.stderr, errors))
            assert proc.stdout is not None
            try:
                while True:
                    data = await proc.stdout.readexactly(self.chunk_bytes)
                    delay = self.restart_delay
                    yield self.process(data)
            except asyncio.IncompleteReadError:
                # The output ended: let the recorder exit by itself first, as signalling
                # a process that has just exited can reap it and lose its exit code.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), 1.0)
            finally:
                await terminate(proc)
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task
                self._proc = None

            if self._closed or self.paused:
                continue
            detail = "; ".join(errors) or "no error output"
            _LOGGER.warning(
                "Microphone recorder exited (code %s): %s. Restarting in %.0f s",
                proc.returncode,
                detail,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
