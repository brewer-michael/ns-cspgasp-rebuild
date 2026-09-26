"""A language model behind an OpenAI-compatible ``/chat/completions`` endpoint.

Works with Ollama (``http://host:11434/v1``), llama.cpp's ``llama-server``, vLLM,
LocalAI, LM Studio and similar servers on your network.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

from . import AgentError, AgentResponse, ConversationAgent

DEFAULT_SYSTEM_PROMPT = (
    "You are the voice assistant inside a small smart speaker. Your replies are spoken "
    "aloud, so answer in one to three short sentences of plain conversational text: no "
    "markdown, lists, emoji, URLs or code. If you are unsure, say so briefly."
)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_MARKDOWN = re.compile(r"(\*\*|__|`+|^#+\s*|^\s*[-*]\s+)", re.MULTILINE)


def clean_for_speech(text: str) -> str:
    """Remove reasoning blocks and markdown that would be read out loud."""
    text = _THINK.sub("", text)
    text = _MARKDOWN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class _Conversation:
    messages: list[dict[str, str]] = field(default_factory=list)
    updated: float = field(default_factory=time.monotonic)


class OpenAiAgent(ConversationAgent):
    name = "openai"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        model: str,
        api_key: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = 0.5,
        max_tokens: int | None = 300,
        history_turns: int = 6,
        history_timeout: float = 300.0,
        timeout: float = 30.0,
    ) -> None:
        self.session = session
        self.endpoint = url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.history_turns = history_turns
        self.history_timeout = history_timeout
        self.timeout = timeout
        self._conversations: dict[str, _Conversation] = {}

    def _conversation(self, conversation_id: str | None) -> tuple[str, _Conversation]:
        now = time.monotonic()
        for key in [
            k for k, c in self._conversations.items() if now - c.updated > self.history_timeout
        ]:
            del self._conversations[key]
        if conversation_id is None or conversation_id not in self._conversations:
            conversation_id = conversation_id or uuid.uuid4().hex
            self._conversations[conversation_id] = _Conversation()
        return conversation_id, self._conversations[conversation_id]

    def _system(self, language: str) -> str:
        now = datetime.now().astimezone()
        return (
            f"{self.system_prompt}\nCurrent local time: {now:%A, %B %d, %Y %H:%M %Z}. "
            f"Reply in the language with code '{language}'."
        )

    async def process(self, text: str, language: str, conversation_id: str | None) -> AgentResponse:
        conversation_id, conversation = self._conversation(conversation_id)
        history = conversation.messages[-2 * self.history_turns :] if self.history_turns else []
        messages = [
            {"role": "system", "content": self._system(language)},
            *history,
            {"role": "user", "content": text},
        ]
        payload: dict[str, object] = {"model": self.model, "messages": messages, "stream": False}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
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
                    raise AgentError(f"{self.endpoint} returned HTTP {response.status}: {detail}")
                result = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AgentError(f"language model request to {self.endpoint} failed: {err}") from err

        try:
            content = result["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as err:
            raise AgentError(f"unexpected language model response: {str(result)[:200]}") from err

        reply = clean_for_speech(str(content))
        conversation.messages += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply},
        ]
        conversation.updated = time.monotonic()
        return AgentResponse(
            text=reply,
            handled=bool(reply),
            continue_conversation=reply.endswith("?"),
            conversation_id=conversation_id,
        )
