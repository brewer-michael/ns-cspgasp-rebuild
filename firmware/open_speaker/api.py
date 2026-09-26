"""A small HTTP API for Home Assistant automations and scripts.

Examples (with ``api.token`` set, add ``-H "Authorization: Bearer <token>"``)::

    curl -X POST http://speaker.local:10800/api/say -d '{"text": "Dinner is ready"}'
    curl -X POST http://speaker.local:10800/api/timers -d '{"seconds": 300, "name": "tea"}'
    curl -X POST http://speaker.local:10800/api/alarms -d '{"time": "06:30", "repeat": "weekdays"}'
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError, web

from .config import ApiConfig
from .homeassistant import HomeAssistantError
from .intents import DAY_NAMES, EVERY_DAY, WEEKDAYS, WEEKENDS
from .pipeline import PipelineFailure

if TYPE_CHECKING:
    from .app import Speaker

_LOGGER = logging.getLogger(__name__)

_REPEAT_NAMES = {"daily": EVERY_DAY, "every day": EVERY_DAY, "weekdays": WEEKDAYS,
                 "weekends": WEEKENDS}  # fmt: skip


class BadRequest(ValueError):
    pass


def parse_repeat(value: Any) -> frozenset[int]:
    if value in (None, "", "once", []):
        return frozenset()
    if isinstance(value, str):
        if value.lower() in _REPEAT_NAMES:
            return _REPEAT_NAMES[value.lower()]
        value = [v.strip() for v in value.split(",")]
    if not isinstance(value, list):
        raise BadRequest("repeat must be daily, weekdays, weekends or a list of days")
    days = set()
    for item in value:
        if isinstance(item, int) and 0 <= item <= 6:
            days.add(item)
            continue
        name = str(item).lower()[:3]
        matches = [i for i, day in enumerate(DAY_NAMES) if day.startswith(name)]
        if len(name) < 3 or not matches:
            raise BadRequest(f"unknown day {item!r}")
        days.add(matches[0])
    return frozenset(days)


def parse_time(value: Any) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or ""))
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        raise BadRequest("time must be HH:MM (24-hour)")
    return int(match.group(1)), int(match.group(2))


def create_app(speaker: Speaker, token: str | None = None) -> web.Application:
    @web.middleware
    async def middleware(request: web.Request, handler: Any) -> web.StreamResponse:
        if token:
            supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return web.json_response({"error": "unauthorized"}, status=401)
        try:
            return await handler(request)
        except BadRequest as err:
            return web.json_response({"error": str(err)}, status=400)
        except (PipelineFailure, HomeAssistantError, ClientError) as err:
            return web.json_response({"error": str(err)}, status=502)

    async def body(request: web.Request) -> dict[str, Any]:
        if not request.can_read_body:
            return {}
        try:
            data = await request.json()
        except ValueError as err:
            raise BadRequest("body must be JSON") from err
        if not isinstance(data, dict):
            raise BadRequest("body must be a JSON object")
        return data

    def scheduler() -> Any:
        if speaker.scheduler is None:
            raise BadRequest("timers and alarms are disabled in the configuration")
        return speaker.scheduler

    async def status(request: web.Request) -> web.Response:
        return web.json_response(speaker.status())

    async def say(request: web.Request) -> web.Response:
        text = str((await body(request)).get("text", "")).strip()
        if not text:
            raise BadRequest("text is required")
        await speaker.say(text)
        return web.json_response({"status": "speaking"}, status=202)

    async def play(request: web.Request) -> web.Response:
        url = str((await body(request)).get("url", "")).strip()
        if not url:
            raise BadRequest("url is required")
        await speaker.play_url(url)
        return web.json_response({"status": "playing"}, status=202)

    async def listen(request: web.Request) -> web.Response:
        started = speaker.start_conversation()
        return web.json_response({"listening": started}, status=202 if started else 409)

    async def stop(request: web.Request) -> web.Response:
        speaker.stop_everything()
        return web.json_response({"status": "stopped"})

    def integer(data: dict[str, Any], key: str) -> int:
        try:
            return int(data[key])
        except (TypeError, ValueError) as err:
            raise BadRequest(f"{key} must be a whole number") from err

    async def volume(request: web.Request) -> web.Response:
        data = await body(request)
        if "level" in data:
            level = await speaker.change_volume(level=integer(data, "level"))
        elif "steps" in data:
            level = await speaker.change_volume(steps=integer(data, "steps"))
        else:
            raise BadRequest("level or steps is required")
        return web.json_response({"volume": level})

    async def mute(request: web.Request) -> web.Response:
        data = await body(request)
        if "microphone" in data:
            await speaker.set_mic_muted(bool(data["microphone"]))
        if "speaker" in data:
            await speaker.set_speaker_muted(bool(data["speaker"]))
        return web.json_response(
            {"mic_muted": speaker.mic_muted, "speaker_muted": speaker.volume.muted}
        )

    async def list_timers(request: web.Request) -> web.Response:
        return web.json_response(speaker.status()["timers"])

    async def add_timer(request: web.Request) -> web.Response:
        data = await body(request)
        try:
            seconds = float(data["seconds"])
        except (KeyError, TypeError, ValueError) as err:
            raise BadRequest("seconds is required") from err
        if seconds <= 0:
            raise BadRequest("seconds must be positive")
        timer = scheduler().add_timer(seconds, data.get("name"))
        speaker._update_indicators()
        return web.json_response({"id": timer.id, "seconds": timer.seconds}, status=201)

    async def delete_timers(request: web.Request) -> web.Response:
        name = request.query.get("name")
        cancelled = scheduler().cancel_timers(name, all=name is None)
        return web.json_response({"cancelled": [t.id for t in cancelled]})

    async def list_alarms(request: web.Request) -> web.Response:
        return web.json_response(speaker.status()["alarms"])

    async def add_alarm(request: web.Request) -> web.Response:
        data = await body(request)
        hour, minute = parse_time(data.get("time"))
        alarm = scheduler().add_alarm(hour, minute, parse_repeat(data.get("repeat")))
        speaker._update_indicators()
        return web.json_response({"id": alarm.id, "time": f"{hour:02d}:{minute:02d}"}, status=201)

    async def delete_alarms(request: web.Request) -> web.Response:
        if "time" in request.query:
            hour, minute = parse_time(request.query["time"])
            cancelled = scheduler().cancel_alarms(hour, minute)
        else:
            cancelled = scheduler().cancel_alarms(all=True)
        speaker._update_indicators()
        return web.json_response({"cancelled": [a.id for a in cancelled]})

    app = web.Application(middlewares=[middleware])
    app.add_routes(
        [
            web.get("/api/status", status),
            web.post("/api/say", say),
            web.post("/api/play", play),
            web.post("/api/listen", listen),
            web.post("/api/stop", stop),
            web.post("/api/volume", volume),
            web.post("/api/mute", mute),
            web.get("/api/timers", list_timers),
            web.post("/api/timers", add_timer),
            web.delete("/api/timers", delete_timers),
            web.get("/api/alarms", list_alarms),
            web.post("/api/alarms", add_alarm),
            web.delete("/api/alarms", delete_alarms),
        ]
    )
    return app


async def serve(speaker: Speaker, config: ApiConfig) -> None:
    runner = web.AppRunner(create_app(speaker, config.token), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    try:
        await site.start()
    except OSError as err:
        _LOGGER.error(
            "HTTP API disabled: cannot listen on %s:%s: %s", config.host, config.port, err
        )
        await runner.cleanup()
        return
    _LOGGER.info("HTTP API listening on %s:%s", config.host, config.port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
