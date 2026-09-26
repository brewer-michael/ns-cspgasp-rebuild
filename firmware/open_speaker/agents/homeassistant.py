"""Home Assistant's conversation API (its built-in intents or any agent it hosts)."""

from __future__ import annotations

from typing import Any

from ..homeassistant import HomeAssistant, HomeAssistantError
from . import AgentError, AgentResponse, ConversationAgent

# Error codes meaning "I did not understand" rather than "I understood but failed".
_NOT_UNDERSTOOD = {"no_intent_match"}


def speech_text(response: dict[str, Any]) -> str:
    speech = response.get("speech") or {}
    for kind in ("plain", "ssml"):
        text = (speech.get(kind) or {}).get("speech")
        if text:
            return str(text)
    return ""


class HomeAssistantAgent(ConversationAgent):
    name = "homeassistant"

    def __init__(self, homeassistant: HomeAssistant, agent_id: str | None = None) -> None:
        self.homeassistant = homeassistant
        self.agent_id = agent_id

    async def process(self, text: str, language: str, conversation_id: str | None) -> AgentResponse:
        try:
            result = await self.homeassistant.converse(
                text, language=language, agent_id=self.agent_id, conversation_id=conversation_id
            )
        except HomeAssistantError as err:
            raise AgentError(str(err)) from err

        response = result.get("response") or {}
        code = (response.get("data") or {}).get("code")
        handled = not (response.get("response_type") == "error" and code in _NOT_UNDERSTOOD)
        return AgentResponse(
            text=speech_text(response),
            handled=handled,
            continue_conversation=bool(result.get("continue_conversation")),
            conversation_id=result.get("conversation_id"),
        )
