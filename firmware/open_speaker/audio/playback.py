"""Speaker playback through an external player (``aplay`` by default)."""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass

from ..config import OutputConfig
from .capture import drain_stderr, format_command, terminate
from .pcm import apply_gain, is_wav, read_wav, to_int16

_LOGGER = logging.getLogger(__name__)

_WRITE_BYTES = 4096


@dataclass(frozen=True)
class PcmFormat:
    rate: int
    width: int = 2
    channels: int = 1


@dataclass
class PcmStream:
    """Raw audio that is still arriving (e.g. streamed text-to-speech)."""

    format: PcmFormat
    chunks: AsyncIterable[bytes]


@dataclass
class EncodedAudio:
    """A complete audio file: WAV, or anything the decoder understands (MP3, OGG...)."""

    data: bytes


AudioSource = PcmStream | EncodedAudio


class PlaybackError(RuntimeError):
    pass


async def _iterate(chunks: AsyncIterable[bytes] | Iterable[bytes]):
    if isinstance(chunks, AsyncIterable):
        async for chunk in chunks:
            yield chunk
    else:
        for chunk in chunks:
            yield chunk


def _split(data: bytes, size: int = _WRITE_BYTES) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


class AudioPlayer:
    """Plays one sound at a time; :meth:`stop` interrupts whatever is playing."""

    def __init__(self, config: OutputConfig) -> None:
        self.config = config
        self.software_gain = 1.0
        self._lock = asyncio.Lock()
        self._proc: asyncio.subprocess.Process | None = None
        self._feeder: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def is_playing(self) -> bool:
        return self._proc is not None

    def stop(self) -> None:
        """Interrupt the current sound (queued sounds still play)."""
        self._stopped = True
        if self._feeder is not None:
            # also stops waiting on a source that has stalled (e.g. a slow TTS server)
            self._feeder.cancel()
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()

    async def play_stream(
        self,
        fmt: PcmFormat,
        chunks: AsyncIterable[bytes] | Iterable[bytes],
        gain: float = 1.0,
    ) -> bool:
        """Play PCM chunks. Returns False if playback was interrupted."""
        channels = fmt.channels
        argv = format_command(
            self.config.command, device=self.config.device, rate=fmt.rate, channels=channels
        )
        async with self._lock:
            self._stopped = False
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as err:
                raise PlaybackError(f"cannot start audio player {argv[0]!r}: {err}") from err

            self._proc = proc
            errors: collections.deque[str] = collections.deque(maxlen=10)
            stderr_task = asyncio.create_task(drain_stderr(proc.stderr, errors))
            assert proc.stdin is not None
            stdin = proc.stdin
            iterator = _iterate(chunks)

            async def feed() -> None:
                async for chunk in iterator:
                    if self._stopped:
                        break
                    chunk = to_int16(chunk, fmt.width)
                    chunk = apply_gain(chunk, gain * self.software_gain)
                    stdin.write(chunk)
                    await stdin.drain()
                if not self._stopped:
                    stdin.close()
                    await proc.wait()

            self._feeder = asyncio.create_task(feed())
            if self._stopped:  # stop() came while the player was starting
                self._feeder.cancel()
            try:
                await self._feeder
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    raise  # our caller is being cancelled, not just this sound
            except (BrokenPipeError, ConnectionResetError):
                # The player went away; let it exit by itself so its exit code is kept.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), 1.0)
            finally:
                self._feeder = None
                # Release the source (e.g. a network connection) if we stopped early.
                await iterator.aclose()
                aclose = getattr(chunks, "aclose", None)
                if aclose is not None:
                    with contextlib.suppress(Exception):
                        await aclose()
                await terminate(proc)
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task
                self._proc = None

            if proc.returncode not in (0, None) and not self._stopped:
                _LOGGER.warning(
                    "Audio player exited with code %s: %s",
                    proc.returncode,
                    "; ".join(errors) or "no error output",
                )
            return not self._stopped

    async def play_pcm(self, pcm: bytes, fmt: PcmFormat, gain: float = 1.0) -> bool:
        return await self.play_stream(fmt, _split(pcm), gain)

    async def play_wav(self, data: bytes, gain: float = 1.0) -> bool:
        pcm, rate, width, channels = read_wav(data)
        return await self.play_pcm(pcm, PcmFormat(rate, width, channels), gain)

    async def decode(self, data: bytes) -> bytes:
        """Decode compressed audio to mono 16-bit PCM at ``decode_rate``."""
        argv = format_command(self.config.decoder, rate=self.config.decode_rate)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as err:
            raise PlaybackError(
                f"cannot start audio decoder {argv[0]!r} (install it or change "
                f"audio.output.decoder): {err}"
            ) from err
        pcm, err = await proc.communicate(data)
        if proc.returncode != 0:
            raise PlaybackError(f"audio decoder failed: {err.decode(errors='replace').strip()}")
        return pcm

    async def play_encoded(self, data: bytes, gain: float = 1.0) -> bool:
        if is_wav(data):
            return await self.play_wav(data, gain)
        pcm = await self.decode(data)
        return await self.play_pcm(pcm, PcmFormat(self.config.decode_rate), gain)

    async def play(self, source: AudioSource, gain: float = 1.0) -> bool:
        if isinstance(source, PcmStream):
            return await self.play_stream(source.format, source.chunks, gain)
        return await self.play_encoded(source.data, gain)
