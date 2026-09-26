"""System volume: an ALSA mixer control (via ``amixer``) or software gain."""

from __future__ import annotations

import asyncio
import logging
import re

from .pcm import silence
from .playback import AudioPlayer, PcmFormat

_LOGGER = logging.getLogger(__name__)
_PERCENT = re.compile(r"\[(\d{1,3})%\]")


class MixerError(RuntimeError):
    pass


async def _amixer(*args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "amixer",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as err:
        raise MixerError(f"cannot run amixer (install alsa-utils): {err}") from err
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise MixerError(err.decode(errors="replace").strip() or f"amixer exited {proc.returncode}")
    return out.decode(errors="replace")


class AlsaControl:
    """One ALSA simple mixer control, set with perceptual (-M) scaling."""

    def __init__(self, name: str, card: str | None = None) -> None:
        self.name = name
        self.card = card

    def _args(self, *args: str) -> list[str]:
        card = ["-c", self.card] if self.card else []
        return [*card, "-M", *args]

    async def get(self) -> int:
        out = await _amixer(*self._args("sget", self.name))
        match = _PERCENT.search(out)
        if match is None:
            raise MixerError(f"cannot read the level of mixer control {self.name!r}")
        return int(match.group(1))

    async def set(self, percent: int) -> None:
        await _amixer(*self._args("-q", "sset", self.name, f"{max(0, min(100, percent))}%"))

    async def exists(self) -> bool:
        try:
            await self.get()
        except MixerError:
            return False
        return True


class Volume:
    """The speaker's volume (0-100) and speaker mute.

    Uses the configured ALSA control when it exists (so music players that share the
    ALSA device follow it too) and falls back to scaling our own audio otherwise.
    """

    def __init__(self, player: AudioPlayer, control: str | None, card: str | None = None) -> None:
        self.player = player
        self.control = AlsaControl(control, card) if control else None
        self.level = 50
        self.muted = False
        self._use_alsa = False

    async def setup(self, level: int) -> None:
        if self.control is not None:
            self._use_alsa = await self.control.exists()
            if not self._use_alsa:
                # softvol controls only appear once their PCM has been opened.
                await self.player.play_pcm(silence(0.05, 16000), PcmFormat(16000))
                self._use_alsa = await self.control.exists()
            if not self._use_alsa:
                _LOGGER.warning(
                    "Mixer control %r not found; using software volume for our own audio",
                    self.control.name,
                )
        await self.set(level)

    @property
    def effective(self) -> int:
        return 0 if self.muted else self.level

    async def _apply(self) -> None:
        level = self.effective
        if self._use_alsa and self.control is not None:
            try:
                await self.control.set(level)
                self.player.software_gain = 1.0
                return
            except MixerError as err:
                _LOGGER.warning("Could not set volume with amixer: %s", err)
        # Square-law taper so the software steps sound roughly even.
        self.player.software_gain = (level / 100) ** 2

    async def set(self, level: int) -> int:
        self.level = max(0, min(100, level))
        await self._apply()
        return self.level

    async def set_muted(self, muted: bool) -> None:
        self.muted = muted
        await self._apply()


class Ducker:
    """Temporarily lowers a second mixer control (e.g. music) while the assistant talks."""

    def __init__(self, control: str | None, card: str | None, level: int) -> None:
        self.control = AlsaControl(control, card) if control else None
        self.level = level
        self._saved: int | None = None
        self._disabled = self.control is None

    async def duck(self) -> None:
        if self._disabled or self._saved is not None:
            return
        assert self.control is not None
        try:
            saved = await self.control.get()
            await self.control.set(min(saved, self.level))
            self._saved = saved
        except MixerError as err:
            _LOGGER.warning("Ducking disabled, mixer control %r: %s", self.control.name, err)
            self._disabled = True

    async def restore(self) -> None:
        if self._saved is None or self.control is None:
            return
        saved, self._saved = self._saved, None
        try:
            await self.control.set(saved)
        except MixerError as err:
            _LOGGER.warning("Could not restore mixer control %r: %s", self.control.name, err)
