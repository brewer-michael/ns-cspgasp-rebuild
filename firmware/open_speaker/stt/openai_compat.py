"""Speech-to-text via an OpenAI-compatible ``/audio/transcriptions`` endpoint.

Works with speaches (faster-whisper), LocalAI, vLLM, whisper.cpp's server started
with ``--inference-path /v1/audio/transcriptions``, and similar servers.
"""

from __future__ import annotations

from collections.abc import AsyncIterable

import aiohttp

from ..audio.pcm import wav_bytes
from ..const import SAMPLE_CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH
from . import SpeechToText, SttError


def iso_language(language: str | None) -> str | None:
    """'en-US' -> 'en' (the transcription API expects ISO-639-1)."""
    if not language:
        return None
    return language.replace("_", "-").split("-")[0].lower()


class OpenAiStt(SpeechToText):
    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.session = session
        self.endpoint = url.rstrip("/") + "/audio/transcriptions"
        self.model = model or "whisper-1"
        self.api_key = api_key
        self.timeout = timeout

    async def transcribe(self, audio: AsyncIterable[bytes], language: str | None) -> str:
        pcm = b"".join([chunk async for chunk in audio])
        form = aiohttp.FormData()
        form.add_field(
            "file",
            wav_bytes(pcm, SAMPLE_RATE, SAMPLE_WIDTH, SAMPLE_CHANNELS),
            filename="speech.wav",
            content_type="audio/wav",
        )
        form.add_field("model", self.model)
        form.add_field("response_format", "json")
        if (code := iso_language(language)) is not None:
            form.add_field("language", code)

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            async with self.session.post(
                self.endpoint,
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as response:
                if response.status != 200:
                    detail = (await response.text())[:300]
                    raise SttError(f"{self.endpoint} returned HTTP {response.status}: {detail}")
                result = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SttError(f"speech-to-text request to {self.endpoint} failed: {err}") from err
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str):
            raise SttError(f"unexpected speech-to-text response: {str(result)[:200]}")
        return text.strip()
