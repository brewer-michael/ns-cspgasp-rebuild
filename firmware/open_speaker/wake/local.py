"""On-device wake word engines (microWakeWord and openWakeWord via TFLite)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import WakeWordEngine


class _ThreadedEngine(WakeWordEngine):
    """Runs model inference on one worker thread so the event loop stays responsive."""

    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None

    async def start(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wake-word")
        await self._run(self._load)

    async def stop(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    async def _run(self, func: Any, *args: Any) -> Any:
        if self._executor is None:
            raise RuntimeError("wake word engine not started")
        return await asyncio.get_running_loop().run_in_executor(self._executor, func, *args)

    async def process(self, chunk: bytes) -> str | None:
        return self.name if await self._run(self._detect, chunk) else None

    async def reset(self) -> None:
        await self._run(self._reset)

    def _load(self) -> None:
        raise NotImplementedError

    def _detect(self, chunk: bytes) -> bool:
        raise NotImplementedError

    def _reset(self) -> None:
        raise NotImplementedError


class MicroWakeWordEngine(_ThreadedEngine):
    """microWakeWord: tiny streaming models, light enough for a Pi Zero 2 W."""

    def __init__(self, model: str, threshold: float | None = None) -> None:
        super().__init__()
        self.model = model
        self.threshold = threshold
        self._mww: Any = None
        self._features: Any = None

    def _load(self) -> None:
        from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures, Model

        try:
            self._mww = MicroWakeWord.from_builtin(Model(self.model))
        except ValueError:
            self._mww = MicroWakeWord.from_config(Path(self.model).expanduser())
        if self.threshold is not None:
            self._mww.probability_cutoff = self.threshold
        self._features = MicroWakeWordFeatures()
        self.name = self._mww.wake_word

    def _detect(self, chunk: bytes) -> bool:
        detected = False
        for features in self._features.process_streaming(chunk):
            if self._mww.process_streaming(features):
                detected = True
        return detected

    def _reset(self) -> None:
        self._mww.reset()
        self._features.reset()


class OpenWakeWordEngine(_ThreadedEngine):
    """openWakeWord: more built-in and community models, needs more CPU."""

    def __init__(self, model: str, threshold: float | None = None) -> None:
        super().__init__()
        self.model = model
        self.threshold = 0.5 if threshold is None else threshold
        self._oww: Any = None
        self._features: Any = None

    def _load(self) -> None:
        from pyopen_wakeword import Model, OpenWakeWord, OpenWakeWordFeatures

        try:
            self._oww = OpenWakeWord.from_builtin(Model(self.model))
        except ValueError:
            self._oww = OpenWakeWord.from_model(Path(self.model).expanduser())
        self._features = OpenWakeWordFeatures.from_builtin()
        self.name = self._oww.id.replace("_", " ")

    def _detect(self, chunk: bytes) -> bool:
        detected = False
        for features in self._features.process_streaming(chunk):
            for probability in self._oww.process_streaming(features):
                if probability > self.threshold:
                    detected = True
        return detected

    def _reset(self) -> None:
        self._oww.reset()
        self._features.reset()
