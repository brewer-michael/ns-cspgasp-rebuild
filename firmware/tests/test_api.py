"""The HTTP API, served on 127.0.0.1 in front of a Speaker built from fakes."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from conftest import FakeMic, FakePipeline, FakePlayer, make_config, wait_for

from open_speaker.api import create_app
from open_speaker.app import Components, Speaker
from open_speaker.homeassistant import HomeAssistantError
from open_speaker.timers import Ring, Scheduler

TOKEN = "s3cret-token"
EVERY_DAY = [0, 1, 2, 3, 4, 5, 6]
_DEFAULT: Any = object()


class FakeHomeAssistant:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def fetch(self, url: str) -> bytes:
        if url not in self.files:
            raise HomeAssistantError(f"{url} not found")
        return self.files[url]

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        return None

    async def close(self) -> None:
        pass


@contextlib.asynccontextmanager
async def web_server(application: web.Application) -> AsyncIterator[str]:
    runner = web.AppRunner(application, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        await runner.cleanup()


@dataclass
class Client:
    url: str
    session: aiohttp.ClientSession
    token: str | None
    speaker: Speaker
    pipeline: FakePipeline
    player: FakePlayer
    mic: FakeMic

    async def request(
        self, method: str, path: str, *, headers: dict[str, str] | None = None, **kwargs: Any
    ) -> tuple[int, Any]:
        if headers is None:
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with self.session.request(
            method, self.url + path, headers=headers, **kwargs
        ) as response:
            if response.content_type == "application/json":
                return response.status, await response.json()
            return response.status, await response.text()

    async def get(self, path: str, **kwargs: Any) -> tuple[int, Any]:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, json: Any = None, **kwargs: Any) -> tuple[int, Any]:
        return await self.request("POST", path, json=json, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> tuple[int, Any]:
        return await self.request("DELETE", path, **kwargs)


async def _no_ring(ring: Ring) -> None:
    return None


@contextlib.asynccontextmanager
async def running_api(
    tmp_path: Path,
    *,
    token: str | None = TOKEN,
    pipeline: Any = _DEFAULT,
    timers: bool = True,
    homeassistant: Any = None,
) -> AsyncIterator[Client]:
    config = make_config(tmp_path)
    mic, player = FakeMic(), FakePlayer(delay=0.005)
    pipeline = FakePipeline([]) if pipeline is _DEFAULT else pipeline
    scheduler = Scheduler(config.timers_state_file, on_ring=_no_ring) if timers else None
    async with aiohttp.ClientSession() as session:
        speaker = Speaker(
            config,
            Components(
                mic=mic,
                player=player,  # type: ignore[arg-type]
                pipeline=pipeline,
                scheduler=scheduler,
                homeassistant=homeassistant,
                session=session,
            ),
        )
        await speaker.start()
        try:
            async with web_server(create_app(speaker, token)) as url:
                yield Client(url, session, token, speaker, pipeline, player, mic)
        finally:
            await speaker.shutdown()


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Client]:
    async with running_api(tmp_path) as client:
        yield client


# ---------------------------------------------------------------------------
# Authorization


async def test_requests_need_the_bearer_token(api) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic czNjcmV0"}):
        assert await api.get("/api/status", headers=headers) == (401, {"error": "unauthorized"})
        assert await api.post("/api/volume", {"level": 10}, headers=headers) == (
            401,
            {"error": "unauthorized"},
        )
        assert await api.post("/api/say", {"text": "hi"}, headers=headers) == (
            401,
            {"error": "unauthorized"},
        )
    assert api.speaker.volume.level == 50
    assert api.pipeline.spoken == []
    status, _ = await api.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert status == 200


@pytest.mark.parametrize("token", [None, ""])
async def test_without_a_token_anyone_on_the_network_may_call(tmp_path, token) -> None:
    async with running_api(tmp_path, token=token) as api:
        for headers in ({}, {"Authorization": "Bearer anything"}):
            status, body = await api.get("/api/status", headers=headers)
            assert (status, body["name"]) == (200, "Open Speaker")


# ---------------------------------------------------------------------------
# Status, speech and playback


async def test_status(api) -> None:
    status, body = await api.get("/api/status")
    assert status == 200
    assert body == api.speaker.status()
    assert body == {
        "name": "Open Speaker",
        "state": "idle",
        "volume": 50,
        "speaker_muted": False,
        "mic_muted": False,
        "ringing": [],
        "temperature": None,
        "timers": [],
        "alarms": [],
    }


async def test_say(api) -> None:
    assert await api.post("/api/say", {"text": "  Dinner is ready "}) == (
        202,
        {"status": "speaking"},
    )
    assert api.pipeline.spoken == ["Dinner is ready"]
    await wait_for(lambda: api.player.audio == [b"TTS:Dinner is ready"])


@pytest.mark.parametrize("payload", [None, {}, {"text": "   "}, {"message": "hello"}])
async def test_say_needs_text(api, payload) -> None:
    assert await api.post("/api/say", payload) == (400, {"error": "text is required"})
    assert api.pipeline.spoken == []


async def test_say_reports_a_speech_failure(api) -> None:
    api.pipeline.fail_speak = True
    assert await api.post("/api/say", {"text": "Dinner is ready"}) == (502, {"error": "tts down"})


async def test_without_a_voice_pipeline(tmp_path) -> None:
    async with running_api(tmp_path, pipeline=None) as api:
        assert await api.post("/api/say", {"text": "hello"}) == (
            502,
            {"error": "no voice pipeline configured"},
        )
        assert await api.post("/api/listen") == (409, {"listening": False})


async def test_play_a_url(api) -> None:
    async def doorbell(request: web.Request) -> web.Response:
        return web.Response(body=b"ID3 DING DONG", content_type="audio/mpeg")

    media = web.Application()
    media.router.add_get("/doorbell.mp3", doorbell)
    async with web_server(media) as media_url:
        assert await api.post("/api/play", {"url": f"{media_url}/doorbell.mp3"}) == (
            202,
            {"status": "playing"},
        )
        await wait_for(lambda: api.player.audio == [b"ID3 DING DONG"])
        status, body = await api.post("/api/play", {"url": f"{media_url}/missing.mp3"})
        assert status == 502
        assert "404" in body["error"]
    assert api.player.audio == [b"ID3 DING DONG"]


async def test_play_home_assistant_media(tmp_path) -> None:
    ha = FakeHomeAssistant({"/api/tts_proxy/abc.mp3": b"ID3 SPEECH"})
    async with running_api(tmp_path, homeassistant=ha) as api:
        assert await api.post("/api/play", {"url": "/api/tts_proxy/abc.mp3"}) == (
            202,
            {"status": "playing"},
        )
        await wait_for(lambda: api.player.audio == [b"ID3 SPEECH"])
        assert await api.post("/api/play", {"url": "/api/tts_proxy/gone.mp3"}) == (
            502,
            {"error": "/api/tts_proxy/gone.mp3 not found"},
        )


@pytest.mark.parametrize("payload", [None, {}, {"url": ""}, {"url": "  "}])
async def test_play_needs_a_url(api, payload) -> None:
    assert await api.post("/api/play", payload) == (400, {"error": "url is required"})


async def test_listen_and_stop(api) -> None:
    assert await api.post("/api/listen") == (202, {"listening": True})
    assert api.speaker.conversation_active
    assert await api.post("/api/listen") == (409, {"listening": False})
    assert (await api.get("/api/status"))[1]["state"] == "listening"
    assert await api.post("/api/stop") == (200, {"status": "stopped"})
    await wait_for(lambda: not api.speaker.conversation_active)
    assert (await api.get("/api/status"))[1]["state"] == "idle"
    await api.post("/api/mute", {"microphone": True})
    assert await api.post("/api/listen") == (409, {"listening": False})
    assert not api.speaker.conversation_active


async def test_stop_silences_a_ringing_timer(api) -> None:
    api.speaker.scheduler.add_timer(0.01)
    await wait_for(lambda: bool(api.speaker.ringing))
    assert (await api.get("/api/status"))[1]["ringing"] == ["timer"]
    stopped = api.player.stopped
    assert await api.post("/api/stop") == (200, {"status": "stopped"})
    assert api.speaker.ringing == []
    assert api.player.stopped > stopped
    assert (await api.get("/api/status"))[1]["ringing"] == []


# ---------------------------------------------------------------------------
# Volume and muting


async def test_volume(api) -> None:
    assert await api.post("/api/volume", {"level": 30}) == (200, {"volume": 30})
    assert await api.post("/api/volume", {"steps": 2}) == (200, {"volume": 40})
    assert await api.post("/api/volume", {"steps": -1}) == (200, {"volume": 35})
    assert await api.post("/api/volume", {"level": "80"}) == (200, {"volume": 80})
    assert await api.post("/api/volume", {"level": 250}) == (200, {"volume": 100})
    assert await api.post("/api/volume", {"level": 20, "steps": 5}) == (200, {"volume": 20})
    assert api.speaker.volume.level == 20
    assert (await api.get("/api/status"))[1]["volume"] == 20


@pytest.mark.parametrize("payload", [None, {}, {"volume": 20}])
async def test_volume_needs_a_level_or_steps(api, payload) -> None:
    assert await api.post("/api/volume", payload) == (400, {"error": "level or steps is required"})


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"level": "loud"}, "level must be a whole number"),
        ({"level": None}, "level must be a whole number"),
        ({"level": [50]}, "level must be a whole number"),
        ({"level": "12.5"}, "level must be a whole number"),
        ({"steps": "up"}, "steps must be a whole number"),
    ],
)
async def test_volume_rejects_bad_values(api, payload, error) -> None:
    assert await api.post("/api/volume", payload) == (400, {"error": error})
    assert api.speaker.volume.level == 50


async def test_mute(api) -> None:
    assert await api.post("/api/mute", {"microphone": True}) == (
        200,
        {"mic_muted": True, "speaker_muted": False},
    )
    assert api.mic.paused
    assert await api.post("/api/mute", {"speaker": True}) == (
        200,
        {"mic_muted": True, "speaker_muted": True},
    )
    assert api.player.software_gain == 0
    assert await api.post("/api/mute", {}) == (200, {"mic_muted": True, "speaker_muted": True})
    assert await api.post("/api/mute", {"microphone": False, "speaker": False}) == (
        200,
        {"mic_muted": False, "speaker_muted": False},
    )
    assert not api.mic.paused
    assert api.player.software_gain > 0
    status, body = await api.get("/api/status")
    assert (status, body["mic_muted"], body["speaker_muted"]) == (200, False, False)


# ---------------------------------------------------------------------------
# Timers and alarms


async def test_timers(api) -> None:
    assert await api.get("/api/timers") == (200, [])
    status, tea = await api.post("/api/timers", {"seconds": 300, "name": "tea"})
    assert (status, tea["seconds"]) == (201, 300)
    status, eggs = await api.post("/api/timers", {"seconds": "90"})
    assert (status, eggs["seconds"]) == (201, 90)
    status, timers = await api.get("/api/timers")
    assert status == 200
    assert [(t["id"], t["name"], t["seconds"]) for t in timers] == [
        (eggs["id"], None, 90),
        (tea["id"], "tea", 300),
    ]
    assert 85 < timers[0]["remaining"] <= 90
    assert timers == (await api.get("/api/status"))[1]["timers"]
    assert await api.delete("/api/timers?name=tea") == (200, {"cancelled": [tea["id"]]})
    assert await api.delete("/api/timers?name=tea") == (200, {"cancelled": []})
    assert await api.delete("/api/timers") == (200, {"cancelled": [eggs["id"]]})
    assert await api.get("/api/timers") == (200, [])


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (None, "seconds is required"),
        ({"name": "tea"}, "seconds is required"),
        ({"seconds": "soon"}, "seconds is required"),
        ({"seconds": None}, "seconds is required"),
        ({"seconds": 0}, "seconds must be positive"),
        ({"seconds": -5}, "seconds must be positive"),
    ],
)
async def test_timer_rejects_bad_values(api, payload, error) -> None:
    assert await api.post("/api/timers", payload) == (400, {"error": error})
    assert await api.get("/api/timers") == (200, [])


async def test_alarms(api) -> None:
    assert await api.get("/api/alarms") == (200, [])
    status, weekdays = await api.post("/api/alarms", {"time": "06:30", "repeat": "weekdays"})
    assert (status, weekdays["time"]) == (201, "06:30")
    status, weekend = await api.post("/api/alarms", {"time": "9:05", "repeat": ["sat", "Sunday"]})
    assert (status, weekend["time"]) == (201, "09:05")
    status, once = await api.post("/api/alarms", {"time": "23:59"})
    assert (status, once["time"]) == (201, "23:59")
    status, alarms = await api.get("/api/alarms")
    assert status == 200
    assert alarms == (await api.get("/api/status"))[1]["alarms"]
    by_id = {alarm.pop("id"): alarm for alarm in alarms}
    for alarm in by_id.values():
        at = datetime.fromisoformat(alarm.pop("next"))
        assert f"{at:%H:%M}" == alarm["time"]
        assert at > datetime.now()
    assert by_id == {
        weekdays["id"]: {"time": "06:30", "repeat": [0, 1, 2, 3, 4]},
        weekend["id"]: {"time": "09:05", "repeat": [5, 6]},
        once["id"]: {"time": "23:59", "repeat": []},
    }
    assert await api.delete("/api/alarms?time=06:30") == (200, {"cancelled": [weekdays["id"]]})
    assert await api.delete("/api/alarms?time=06:30") == (200, {"cancelled": []})
    status, body = await api.delete("/api/alarms")
    assert (status, sorted(body["cancelled"])) == (200, sorted([weekend["id"], once["id"]]))
    assert await api.get("/api/alarms") == (200, [])


@pytest.mark.parametrize(
    ("repeat", "days"),
    [
        (None, []),
        ("", []),
        ("once", []),
        ([], []),
        ("daily", EVERY_DAY),
        ("every day", EVERY_DAY),
        ("Weekdays", [0, 1, 2, 3, 4]),
        ("weekends", [5, 6]),
        ("mon, wed,fri", [0, 2, 4]),
        (["tue", "Thursday"], [1, 3]),
        ([0, 6], [0, 6]),
    ],
)
async def test_alarm_repeat(api, repeat, days) -> None:
    status, _ = await api.post("/api/alarms", {"time": "07:00", "repeat": repeat})
    assert status == 201
    status, (alarm,) = await api.get("/api/alarms")
    assert alarm["repeat"] == days


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (None, "time must be HH:MM (24-hour)"),
        ({"repeat": "daily"}, "time must be HH:MM (24-hour)"),
        ({"time": "7"}, "time must be HH:MM (24-hour)"),
        ({"time": "24:00"}, "time must be HH:MM (24-hour)"),
        ({"time": "06:60"}, "time must be HH:MM (24-hour)"),
        ({"time": "6:30pm"}, "time must be HH:MM (24-hour)"),
        ({"time": 630}, "time must be HH:MM (24-hour)"),
        ({"time": "06:30", "repeat": "fortnightly"}, "unknown day 'fortnightly'"),
        ({"time": "06:30", "repeat": ["mo"]}, "unknown day 'mo'"),
        ({"time": "06:30", "repeat": [7]}, "unknown day 7"),
        (
            {"time": "06:30", "repeat": 3},
            "repeat must be daily, weekdays, weekends or a list of days",
        ),
    ],
)
async def test_alarm_rejects_bad_values(api, payload, error) -> None:
    assert await api.post("/api/alarms", payload) == (400, {"error": error})
    assert await api.get("/api/alarms") == (200, [])


async def test_deleting_alarms_needs_a_valid_time(api) -> None:
    await api.post("/api/alarms", {"time": "06:30"})
    assert await api.delete("/api/alarms?time=6am") == (
        400,
        {"error": "time must be HH:MM (24-hour)"},
    )
    assert len((await api.get("/api/alarms"))[1]) == 1


async def test_timers_and_alarms_can_be_turned_off(tmp_path) -> None:
    async with running_api(tmp_path, timers=False) as api:
        error = (400, {"error": "timers and alarms are disabled in the configuration"})
        assert await api.post("/api/timers", {"seconds": 60}) == error
        assert await api.delete("/api/timers") == error
        assert await api.post("/api/alarms", {"time": "07:00"}) == error
        assert await api.delete("/api/alarms") == error
        assert await api.get("/api/timers") == (200, [])
        assert await api.get("/api/alarms") == (200, [])


# ---------------------------------------------------------------------------
# Bad requests


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ("{not json", "body must be JSON"),
        (b"\xff\xfe{}", "body must be JSON"),
        ('["a", "list"]', "body must be a JSON object"),
        ("42", "body must be a JSON object"),
        ("null", "body must be a JSON object"),
    ],
)
@pytest.mark.parametrize(
    "path", ["/api/say", "/api/play", "/api/volume", "/api/mute", "/api/timers", "/api/alarms"]
)
async def test_bad_json_is_rejected(api, path, data, error) -> None:
    assert await api.post(path, data=data) == (400, {"error": error})
