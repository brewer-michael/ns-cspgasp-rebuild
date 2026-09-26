"""Conversation agents: turn a transcript into a spoken reply (and actions)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import aiohttp

from ..config import AgentConfig
from ..homeassistant import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AgentError(RuntimeError):
    pass


@dataclass
class AgentResponse:
    text: str
    # False means "not understood": the next agent in the chain gets a turn.
    handled: bool = True
    continue_conversation: bool = False
    conversation_id: str | None = None


class ConversationAgent(ABC):
    name: str = "agent"

    @abstractmethod
    async def process(
        self, text: str, language: str, conversation_id: str | None
    ) -> AgentResponse: ...


class AgentChain(ConversationAgent):
    """Asks each agent in turn until one understands the request.

    A typical chain is Home Assistant first (fast, local home control), then a
    language model on your network for everything else.
    """

    name = "chain"

    def __init__(self, agents: list[ConversationAgent]) -> None:
        if not agents:
            raise ValueError("at least one agent is required")
        self.agents = agents

    async def process(self, text: str, language: str, conversation_id: str | None) -> AgentResponse:
        response: AgentResponse | None = None
        last_error: Exception | None = None
        for agent in self.agents:
            try:
                response = await agent.process(text, language, conversation_id)
            except AgentError as err:
                _LOGGER.warning("Agent %s failed: %s", agent.name, err)
                last_error = err
                continue
            if response.handled:
                return response
            _LOGGER.debug("Agent %s did not understand %r", agent.name, text)
        if response is not None:
            return response
        raise AgentError(f"no agent could answer: {last_error}")


def create_agents(
    configs: list[AgentConfig],
    session: aiohttp.ClientSession,
    homeassistant: HomeAssistant | None,
) -> AgentChain:
    agents: list[ConversationAgent] = []
    for config in configs:
        if config.engine == "homeassistant":
            from .homeassistant import HomeAssistantAgent

            if homeassistant is None:
                raise ValueError("the homeassistant agent needs homeassistant.url and token")
            agents.append(HomeAssistantAgent(homeassistant, config.agent_id))
        else:
            from .openai_compat import OpenAiAgent

            assert config.url is not None and config.model is not None
            agents.append(
                OpenAiAgent(
                    session,
                    config.url,
                    config.model,
                    api_key=config.api_key,
                    system_prompt=config.system_prompt,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    history_turns=config.history_turns,
                    history_timeout=config.history_timeout,
                    timeout=config.timeout,
                )
            )
    return AgentChain(agents)


__all__ = [
    "AgentChain",
    "AgentError",
    "AgentResponse",
    "ConversationAgent",
    "create_agents",
]
