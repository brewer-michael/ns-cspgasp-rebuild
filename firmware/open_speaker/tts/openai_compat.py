"""Text-to-speech via an OpenAI-compatible ``/audio/speech`` endpoint.

Works with speaches (Kokoro, Piper), Kokoro-FastAPI, openedai-speech, LocalAI and
similar servers.
"""

from __future__ import annotations

import aiohttp

from ..audio.playback import EncodedAudio
from . import TextToSpeech, TtsError


class OpenAiTts(TextToSpeech):
    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        model: str | None = None,
        voice: str | None = None,
        api_key: str | None = None,
        speed: float | None = None,
        response_format: str = "wav",
        timeout: float = 30.0,
    ) -> None:
        self.session = session
        self.endpoint = url.rstrip("/") + "/audio/speech"
        self.model = model or "tts-1"
        self.voice = voice or "alloy"
        self.api_key = api_key
        self.speed = speed
        self.response_format = response_format
        self.timeout = timeout

    async def synthesize(self, text: str, language: str | None) -> EncodedAudio:
        payload: dict[str, object] = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": self.response_format,
        }
        if self.speed is not None:
            payload["speed"] = self.speed
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with self.session.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    detail = (await response.text())[:300]
                    raise TtsError(f"{self.endpoint} returned HTTP {response.status}: {detail}")
                data = await response.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TtsError(f"text-to-speech request to {self.endpoint} failed: {err}") from err
        if not data:
            raise TtsError("text-to-speech server returned no audio")
        return EncodedAudio(data)
