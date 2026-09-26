"""Home Assistant client: the REST API and Assist pipelines over the WebSocket API.

Protocol details follow Home Assistant's ``assist_pipeline/run`` command: audio is
sent as binary WebSocket messages prefixed with the ``stt_binary_handler_id`` byte
from the ``run-start`` event, and a message containing only that byte ends the stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

_CLOSED = object()


class HomeAssistantError(RuntimeError):
    pass


class HomeAssistantAuthError(HomeAssistantError):
    pass


class PipelineError(HomeAssistantError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class HomeAssistant:
    def __init__(
        self,
        url: str,
        token: str,
        session: aiohttp.ClientSession,
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.session = session
        self.ssl: bool | None = None if verify_ssl else False
        self.timeout = timeout
        self.version: str | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._queues: dict[int, asyncio.Queue[Any]] = {}
        self._next_id = 1
        self._connect_lock = asyncio.Lock()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    # -- REST -----------------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith(("http://", "https://")) else self.url + path
        try:
            async with self.session.request(
                method,
                url,
                headers=self._headers,
                ssl=self.ssl,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                **kwargs,
            ) as response:
                if response.status == 401:
                    raise HomeAssistantAuthError("Home Assistant rejected the access token")
                if response.status == 404:
                    return None
                if response.status >= 400:
                    detail = (await response.text())[:300]
                    raise HomeAssistantError(f"{method} {path}: HTTP {response.status} {detail}")
                if response.content_type == "application/json":
                    return await response.json()
                return await response.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(f"cannot reach Home Assistant at {self.url}: {err}") from err

    async def check(self) -> str:
        """Verify the URL and token; returns Home Assistant's status message."""
        result = await self._request("GET", "/api/")
        if not isinstance(result, dict) or "message" not in result:
            raise HomeAssistantError(f"{self.url} does not look like Home Assistant")
        return str(result["message"])

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        result = await self._request("GET", f"/api/states/{entity_id}")
        return result if isinstance(result, dict) else None

    async def converse(
        self,
        text: str,
        language: str | None = None,
        agent_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if language:
            payload["language"] = language
        if agent_id:
            payload["agent_id"] = agent_id
        if conversation_id:
            payload["conversation_id"] = conversation_id
        result = await self._request("POST", "/api/conversation/process", json=payload)
        if not isinstance(result, dict):
            raise HomeAssistantError("unexpected response from the conversation API")
        return result

    async def fetch(self, url: str) -> bytes:
        """Download a file served by Home Assistant (e.g. a /api/tts_proxy/ URL)."""
        result = await self._request("GET", url)
        if result is None:
            raise HomeAssistantError(f"{url} not found")
        if not isinstance(result, bytes):
            raise HomeAssistantError(f"{url} did not return audio")
        return result

    # -- WebSocket ------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        async with self._connect_lock:
            if self.connected:
                return
            ws_url = "ws" + self.url.removeprefix("http") + "/api/websocket"
            try:
                ws = await self.session.ws_connect(
                    ws_url, heartbeat=30, ssl=self.ssl, timeout=aiohttp.ClientWSTimeout(ws_close=10)
                )
            except (aiohttp.ClientError, TimeoutError) as err:
                raise HomeAssistantError(f"cannot connect to {ws_url}: {err}") from err
            try:
                hello = await asyncio.wait_for(ws.receive_json(), self.timeout)
                if hello.get("type") != "auth_required":
                    raise HomeAssistantError(f"unexpected first message: {hello}")
                await ws.send_json({"type": "auth", "access_token": self.token})
                reply = await asyncio.wait_for(ws.receive_json(), self.timeout)
            except (aiohttp.ClientError, TimeoutError, TypeError, ValueError) as err:
                await ws.close()
                raise HomeAssistantError(f"WebSocket handshake failed: {err}") from err
            if reply.get("type") != "auth_ok":
                await ws.close()
                raise HomeAssistantAuthError(
                    f"Home Assistant rejected the access token: {reply.get('message', reply)}"
                )
            self.version = reply.get("ha_version")
            self._ws = ws
            self._reader = asyncio.create_task(self._read_messages(ws))
            _LOGGER.info("Connected to Home Assistant %s", self.version or "")

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            await ws.close()
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
            self._reader = None

    async def _read_messages(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        try:
            async for message in ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = message.json()
                for item in data if isinstance(data, list) else [data]:
                    queue = self._queues.get(item.get("id"))
                    if queue is not None:
                        queue.put_nowait(item)
        except Exception:  # pragma: no cover - defensive, logged below
            _LOGGER.exception("Home Assistant WebSocket reader failed")
        finally:
            if self._ws is ws:
                self._ws = None
                _LOGGER.warning("Disconnected from Home Assistant")
            for queue in self._queues.values():
                queue.put_nowait(_CLOSED)

    def _register(self) -> tuple[int, asyncio.Queue[Any]]:
        msg_id = self._next_id
        self._next_id += 1
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._queues[msg_id] = queue
        return msg_id, queue

    async def _next(self, queue: asyncio.Queue[Any], timeout: float) -> dict[str, Any]:
        try:
            item = await asyncio.wait_for(queue.get(), timeout)
        except TimeoutError as err:
            raise HomeAssistantError("timed out waiting for Home Assistant") from err
        if item is _CLOSED:
            raise HomeAssistantError("lost connection to Home Assistant")
        return item

    async def command(self, payload: dict[str, Any]) -> Any:
        """Send one WebSocket command and return its result."""
        await self.connect()
        assert self._ws is not None
        msg_id, queue = self._register()
        try:
            await self._ws.send_json({"id": msg_id, **payload})
            reply = await self._next(queue, self.timeout)
            if not reply.get("success"):
                error = reply.get("error") or {}
                raise HomeAssistantError(f"{error.get('code')}: {error.get('message')}")
            return reply.get("result")
        finally:
            self._queues.pop(msg_id, None)

    async def run_pipeline(
        self,
        start_stage: str,
        end_stage: str,
        pipeline_input: dict[str, Any],
        *,
        pipeline: str | None = None,
        conversation_id: str | None = None,
        audio: AsyncIterable[bytes] | None = None,
        event_timeout: float = 60.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run an Assist pipeline and yield its events until ``run-end``.

        When ``audio`` is given it is streamed to Home Assistant from ``run-start``
        until the audio ends or Home Assistant reports the end of speech.
        """
        await self.connect()
        ws = self._ws
        assert ws is not None
        msg_id, queue = self._register()
        payload: dict[str, Any] = {
            "id": msg_id,
            "type": "assist_pipeline/run",
            "start_stage": start_stage,
            "end_stage": end_stage,
            "input": pipeline_input,
        }
        if pipeline:
            payload["pipeline"] = pipeline
        if conversation_id:
            payload["conversation_id"] = conversation_id

        streamer: _AudioStreamer | None = None
        finished = False
        try:
            await ws.send_json(payload)
            reply = await self._next(queue, self.timeout)
            if reply.get("type") == "result" and not reply.get("success"):
                error = reply.get("error") or {}
                raise PipelineError(
                    str(error.get("code", "unknown")), str(error.get("message", ""))
                )
            while True:
                message = await self._next(queue, event_timeout)
                if message.get("type") != "event":
                    continue
                event = message.get("event") or {}
                event_type = event.get("type")
                data = event.get("data") or {}
                if event_type == "run-start" and audio is not None:
                    handler_id = (data.get("runner_data") or {}).get("stt_binary_handler_id")
                    if handler_id is None:
                        raise HomeAssistantError("pipeline did not accept audio")
                    streamer = _AudioStreamer(ws, int(handler_id), audio)
                elif event_type in ("stt-vad-end", "stt-end", "error", "run-end") and streamer:
                    await streamer.finish()
                if event_type == "run-end":
                    finished = True
                yield event
                if finished:
                    return
        finally:
            if streamer is not None:
                await streamer.finish()
            self._queues.pop(msg_id, None)
            if not finished and self.connected:
                # Cancel the pipeline run if we stopped early.
                with contextlib.suppress(Exception):
                    await ws.send_json(
                        {
                            "id": self._register()[0],
                            "type": "unsubscribe_events",
                            "subscription": msg_id,
                        }
                    )


class _AudioStreamer:
    """Forwards audio chunks to a pipeline's binary handler, then ends the stream once."""

    def __init__(
        self, ws: aiohttp.ClientWebSocketResponse, handler_id: int, audio: AsyncIterable[bytes]
    ) -> None:
        self.ws = ws
        self.prefix = bytes([handler_id])
        self.audio = audio
        self._ended = False
        self._task = asyncio.create_task(self._send())

    async def _send(self) -> None:
        async for chunk in self.audio:
            await self.ws.send_bytes(self.prefix + chunk)
        await self._end()

    async def _end(self) -> None:
        if self._ended:
            return
        self._ended = True
        if not self.ws.closed:
            with contextlib.suppress(Exception):
                await self.ws.send_bytes(self.prefix)

    async def finish(self) -> None:
        if not self._task.done():
            self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        await self._end()
