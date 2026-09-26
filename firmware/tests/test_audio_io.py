"""Local audio I/O: the microphone recorder, the speaker player, volume and feedback sounds."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import shlex
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import FakePlayer, chunked, silence, tone, wait_for

from open_speaker.audio.capture import Microphone
from open_speaker.audio.pcm import wav_bytes
from open_speaker.audio.playback import (
    AudioPlayer,
    EncodedAudio,
    PcmFormat,
    PcmStream,
    PlaybackError,
)
from open_speaker.audio.sounds import BUILTIN_SOUNDS, Sound, load_sound
from open_speaker.audio.volume import Ducker, Volume
from open_speaker.config import InputConfig, OutputConfig


def samples(data: bytes) -> list[int]:
    return np.frombuffer(data, dtype="<i2").tolist()


def pcm16(values: Any) -> bytes:
    return np.asarray(values, dtype="<i2").tobytes()


# ---------------------------------------------------------------------------
# Microphone

# Stands in for arecord: logs its start, writes the PCM file to stdout, then
# "once": waits to be stopped, "stream": repeats the PCM every 10 ms,
# "exit": exits with code 3, "fail": exits with code 2 without any audio.
RECORDER = r"""
import json, os, signal, sys, time

data_path, log_path, mode = sys.argv[1:4]
with open(log_path, "a") as log:
    entry = {"time": time.monotonic(), "pid": os.getpid(), "argv": sys.argv[4:]}
    log.write(json.dumps(entry) + "\n")


def terminated(*_):
    with open(log_path + ".term", "a") as term:
        term.write(f"{os.getpid()}\n")
    os._exit(0)


signal.signal(signal.SIGTERM, terminated)
out = sys.stdout.buffer
if mode in ("exit", "fail"):
    sys.stderr.write("device lost\n" if mode == "exit" else "device busy\n")
    sys.stderr.flush()
    time.sleep(0.02)
    if mode == "fail":
        sys.exit(2)
with open(data_path, "rb") as f:
    data = f.read()
out.write(data)
out.flush()
if mode == "exit":
    sys.exit(3)
while True:
    time.sleep(0.01)
    if mode == "stream":
        out.write(data)
        out.flush()
"""


class Recorder:
    def __init__(self, tmp_path: Path) -> None:
        self.script = tmp_path / "recorder.py"
        self.script.write_text(RECORDER)
        self.data = tmp_path / "capture.raw"
        self.log = tmp_path / "recorder.log"
        self.term = tmp_path / "recorder.log.term"

    def config(self, mode: str, pcm: bytes = b"", **options: Any) -> InputConfig:
        self.data.write_bytes(pcm)
        program = shlex.join([sys.executable, str(self.script), str(self.data), str(self.log)])
        return InputConfig(command=f"{program} {mode} {{device}} {{rate}} {{channels}}", **options)

    @property
    def starts(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    @property
    def terminated(self) -> list[int]:
        return [int(pid) for pid in self.term.read_text().split()] if self.term.exists() else []


class Listener:
    """Consumes :meth:`Microphone.chunks` in the background, like the wake-word loop."""

    def __init__(self, mic: Microphone) -> None:
        self.mic = mic
        self.chunks: list[bytes] = []
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async for chunk in self.mic.chunks():
            self.chunks.append(chunk)

    async def close(self) -> None:
        await self.mic.close()
        await asyncio.wait_for(self.task, 3)


@pytest.fixture
def recorder(tmp_path: Path) -> Recorder:
    return Recorder(tmp_path)


@pytest.fixture
async def listen():
    listeners: list[Listener] = []

    def start(mic: Microphone) -> Listener:
        listener = Listener(mic)
        listeners.append(listener)
        return listener

    yield start
    for listener in listeners:
        await listener.close()


def exits(caplog: pytest.LogCaptureFixture) -> list[tuple[Any, ...]]:
    """(exit code, error output, restart delay) for each logged recorder exit."""
    return [
        tuple(r.args)  # type: ignore[arg-type]
        for r in caplog.records
        if r.getMessage().startswith("Microphone recorder exited")
    ]


def test_microphone_command_quotes_each_value() -> None:
    config = InputConfig(
        command="arecord -D {device} -r {rate} -c {channels}", device="plughw:CARD=mics; rm -rf ~"
    )
    argv = Microphone(config).argv
    assert argv == ["arecord", "-D", "plughw:CARD=mics; rm -rf ~", "-r", "16000", "-c", "2"]


async def test_microphone_streams_fixed_size_chunks(recorder: Recorder, listen) -> None:
    pcm = tone(0.03)  # 480 samples: three chunks of 160
    config = recorder.config(
        "once", pcm + tone(0.005), device="mic array", channels=1, samples_per_chunk=160
    )
    mic = Microphone(config)
    assert mic.chunk_bytes == 320
    heard = listen(mic)
    await wait_for(lambda: len(heard.chunks) == 3)
    await asyncio.sleep(0.05)
    assert heard.chunks == chunked(pcm, 320)  # the trailing half chunk is held back
    (start,) = recorder.starts
    assert start["argv"] == ["mic array", "16000", "1"]
    await heard.close()
    assert recorder.terminated == [start["pid"]]


FRAMES = 320
LEFT = np.arange(FRAMES) * 50 - 8000
RIGHT = 3000 - np.arange(FRAMES) * 20


@pytest.mark.parametrize(
    ("channel", "expected"), [("mix", (LEFT + RIGHT) // 2), (0, LEFT), (1, RIGHT)]
)
async def test_microphone_reduces_stereo_to_one_channel(
    recorder: Recorder, listen, channel: int | str, expected: np.ndarray
) -> None:
    stereo = pcm16(np.column_stack([LEFT, RIGHT]))
    config = recorder.config("once", stereo, channels=2, channel=channel, samples_per_chunk=160)
    mic = Microphone(config)
    assert mic.chunk_bytes == 640
    heard = listen(mic)
    await wait_for(lambda: len(heard.chunks) == 2)
    assert [len(chunk) for chunk in heard.chunks] == [320, 320]
    assert b"".join(heard.chunks) == pcm16(expected)
    assert recorder.starts[0]["argv"][1:] == ["16000", "2"]


async def test_microphone_applies_the_configured_gain(recorder: Recorder, listen) -> None:
    loud = [0, 1000, -1000, 16000, 20000, -20000, 32767, -32768] * 20
    config = recorder.config(
        "once", pcm16(loud), channels=1, samples_per_chunk=160, gain_db=20 * math.log10(2)
    )
    heard = listen(Microphone(config))
    await wait_for(lambda: len(heard.chunks) == 1)
    assert samples(heard.chunks[0]) == [0, 2000, -2000, 32000, 32767, -32768, 32767, -32768] * 20


async def test_microphone_pause_stops_the_recorder_until_resumed(
    recorder: Recorder, listen, caplog
) -> None:
    chunk = tone(0.01)
    config = recorder.config("stream", chunk, channels=1, samples_per_chunk=160)
    mic = Microphone(config, restart_delay=0.05)
    heard = listen(mic)
    await wait_for(lambda: len(heard.chunks) >= 3)
    first = recorder.starts[0]["pid"]
    mic.pause()
    assert mic.paused
    await wait_for(lambda: recorder.terminated == [first])
    await asyncio.sleep(0.05)
    count = len(heard.chunks)
    await asyncio.sleep(0.2)
    assert len(heard.chunks) == count  # nothing is captured while paused
    assert len(recorder.starts) == 1
    assert not exits(caplog)
    mic.resume()
    assert not mic.paused
    await wait_for(lambda: len(heard.chunks) > count)
    assert len(recorder.starts) == 2
    assert set(heard.chunks) == {chunk}


async def test_microphone_close_ends_the_stream(recorder: Recorder, listen) -> None:
    mic = Microphone(recorder.config("once", tone(0.01), channels=1, samples_per_chunk=160))
    heard = listen(mic)
    await wait_for(lambda: len(heard.chunks) == 1)
    await mic.close()
    await asyncio.wait_for(heard.task, 1)
    assert recorder.terminated == [recorder.starts[0]["pid"]]


async def test_microphone_close_while_paused(recorder: Recorder, listen) -> None:
    mic = Microphone(recorder.config("stream", tone(0.01), channels=1, samples_per_chunk=160))
    heard = listen(mic)
    await wait_for(lambda: heard.chunks)
    mic.pause()
    await wait_for(lambda: recorder.terminated)
    await mic.close()
    await asyncio.wait_for(heard.task, 1)
    assert len(recorder.starts) == 1


async def test_microphone_restarts_the_recorder_when_it_exits(
    recorder: Recorder, listen, caplog
) -> None:
    chunk = tone(0.01)
    config = recorder.config("exit", chunk, channels=1, samples_per_chunk=160)
    heard = listen(Microphone(config, restart_delay=0.05))
    await wait_for(lambda: len(heard.chunks) >= 3)
    await heard.close()
    assert heard.chunks[:3] == [chunk] * 3
    assert len(exits(caplog)) >= 2
    for code, detail, delay in exits(caplog):
        assert code == 3 and "device lost" in detail
        assert delay == pytest.approx(0.05)  # audio arrived, so no back-off
    times = [start["time"] for start in recorder.starts]
    assert all(b - a >= 0.05 for a, b in itertools.pairwise(times))


async def test_microphone_backs_off_while_the_recorder_keeps_failing(
    recorder: Recorder, listen, caplog
) -> None:
    heard = listen(Microphone(recorder.config("fail", channels=1), restart_delay=0.04))
    await wait_for(lambda: len(exits(caplog)) >= 3)
    await heard.close()
    assert heard.chunks == []
    logged = exits(caplog)[:3]
    assert [delay for *_, delay in logged] == pytest.approx([0.04, 0.08, 0.16])
    assert all(code == 2 and "device busy" in detail for code, detail, _ in logged)
    times = [start["time"] for start in recorder.starts]
    gaps = [b - a for a, b in itertools.pairwise(times[:3])]
    assert len(gaps) == 2 and gaps[0] >= 0.04 and gaps[1] >= 0.08


async def test_microphone_retries_when_the_recorder_cannot_start(
    tmp_path: Path, listen, caplog
) -> None:
    missing = shlex.quote(str(tmp_path / "no-such-recorder"))
    heard = listen(Microphone(InputConfig(command=f"{missing} -D {{device}}"), restart_delay=0.02))

    def failures() -> list[Any]:
        return [r for r in caplog.records if "Cannot start microphone recorder" in r.getMessage()]

    await wait_for(lambda: len(failures()) >= 3)
    await heard.close()
    assert heard.chunks == []
    first, second, third = failures()[:3]
    assert second.created - first.created >= 0.02 - 0.005
    assert third.created - second.created >= 0.04 - 0.005


# ---------------------------------------------------------------------------
# Speaker playback

# Stands in for aplay: copies stdin to <base>.<n> (the n-th sound played) and the
# format to <base>.<n>.json, pausing ``pace`` seconds per read. Afterwards it keeps
# "playing" for ``hold`` seconds, or with a negative hold reports an error and exits 2.
PLAYER = r"""
import json, os, sys, time

base, rate, channels, hold, pace = sys.argv[1:6]
index = 0
while os.path.exists(f"{base}.{index}"):
    index += 1
path = f"{base}.{index}"
with open(path, "wb") as out:
    with open(path + ".json", "w") as info:
        json.dump({"rate": int(rate), "channels": int(channels)}, info)
    while chunk := sys.stdin.buffer.read1(4096):
        out.write(chunk)
        out.flush()
        time.sleep(float(pace))
if float(hold) < 0:
    sys.stderr.write("device unplugged\n")
    sys.exit(2)
time.sleep(float(hold))
"""

# Stands in for mpg123: "decodes" data that starts with b"MP3!" by dropping that header.
DECODER = r"""
import sys

data = sys.stdin.buffer.read()
if not data.startswith(b"MP3!"):
    sys.stderr.write("not an mp3 stream\n")
    sys.exit(1)
sys.stdout.buffer.write(data[4:])
"""


class Speaker:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.script = tmp_path / "player.py"
        self.script.write_text(PLAYER)
        self.base = tmp_path / "played"

    def config(self, hold: float = 0.0, pace: float = 0.0, **options: Any) -> OutputConfig:
        program = shlex.join([sys.executable, str(self.script)])
        command = f"{program} {{device}} {{rate}} {{channels}} {hold} {pace}"
        return OutputConfig(command=command, device=str(self.base), **options)

    def path(self, index: int = 0) -> Path:
        return Path(f"{self.base}.{index}")

    def output(self, index: int = 0) -> bytes:
        return self.path(index).read_bytes()

    def format(self, index: int = 0) -> tuple[int, int]:
        info = json.loads(Path(f"{self.base}.{index}.json").read_text())
        return info["rate"], info["channels"]

    def size(self, index: int = 0) -> int:
        path = self.path(index)
        return path.stat().st_size if path.exists() else 0


@pytest.fixture
def speaker(tmp_path: Path) -> Speaker:
    return Speaker(tmp_path)


def endless(chunk: bytes, closed: asyncio.Event):
    """A source that keeps delivering audio, like a long text-to-speech stream."""

    async def source():
        try:
            while True:
                yield chunk
                await asyncio.sleep(0.005)
        finally:
            closed.set()

    return source()


async def test_play_pcm_sends_the_samples_to_the_player(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    pcm = tone(0.4, rate=22050)
    assert not player.is_playing
    assert await player.play_pcm(pcm, PcmFormat(22050)) is True
    assert speaker.output() == pcm
    assert speaker.format() == (22050, 1)
    assert not player.is_playing


async def test_play_pcm_applies_gain_and_the_software_volume(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    player.software_gain = 0.5
    assert await player.play_pcm(pcm16([4000, -4000, 1000, 30000] * 100), PcmFormat(16000), 0.5)
    assert samples(speaker.output()) == [1000, -1000, 250, 7500] * 100


async def test_play_stream_accepts_async_and_plain_iterables(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    pieces = chunked(tone(0.1), 1000)

    async def arriving():
        for piece in pieces:
            await asyncio.sleep(0)
            yield piece

    assert await player.play_stream(PcmFormat(16000), arriving()) is True
    assert await player.play_stream(PcmFormat(16000), iter(pieces)) is True
    assert speaker.output(0) == speaker.output(1) == b"".join(pieces)


async def test_play_stream_converts_to_16_bit_and_passes_the_format(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    wide = np.array([100 << 16, -5 << 16, 32767 << 16, -32768 << 16], dtype="<i4").tobytes()
    assert await player.play_stream(PcmFormat(48000, width=4, channels=2), [wide])
    assert samples(speaker.output(0)) == [100, -5, 32767, -32768]
    assert speaker.format(0) == (48000, 2)
    assert await player.play_stream(PcmFormat(8000, width=1), [bytes([0, 128, 255, 129])])
    assert samples(speaker.output(1)) == [-32768, 0, 32512, 256]
    assert speaker.format(1) == (8000, 1)


async def test_play_wav_uses_the_format_in_the_header(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    stereo = pcm16([1, -1, 2, -2] * 50)
    assert await player.play_wav(wav_bytes(stereo, 44100, width=2, channels=2)) is True
    assert speaker.output(0) == stereo
    assert speaker.format(0) == (44100, 2)
    assert await player.play_wav(wav_bytes(bytes([0, 128, 255]), 11025, width=1)) is True
    assert samples(speaker.output(1)) == [-32768, 0, 32512]
    assert speaker.format(1) == (11025, 1)


async def test_play_handles_streams_wav_and_compressed_audio(speaker: Speaker) -> None:
    decoder = speaker.tmp_path / "decoder.py"
    decoder.write_text(DECODER)
    command = shlex.join([sys.executable, str(decoder)]) + " -r {rate}"
    player = AudioPlayer(speaker.config(decoder=command, decode_rate=24000))
    pcm = tone(0.05)

    async def stream():
        yield pcm

    assert await player.play(PcmStream(PcmFormat(16000), stream())) is True
    assert await player.play(EncodedAudio(wav_bytes(pcm, 22050))) is True
    assert await player.play(EncodedAudio(b"MP3!" + pcm)) is True
    assert [speaker.output(i) for i in range(3)] == [pcm] * 3
    assert [speaker.format(i) for i in range(3)] == [(16000, 1), (22050, 1), (24000, 1)]
    with pytest.raises(PlaybackError, match="audio decoder failed: not an mp3 stream"):
        await player.play(EncodedAudio(b"OGG?" + pcm))


async def test_is_playing_while_the_player_runs(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config(hold=0.15))
    playing = asyncio.create_task(player.play_pcm(tone(0.05), PcmFormat(16000)))
    await wait_for(lambda: player.is_playing)
    assert await asyncio.wait_for(playing, 2) is True
    assert not player.is_playing


async def test_stop_interrupts_a_stream_and_closes_its_source(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    chunk = tone(0.01)
    closed = asyncio.Event()
    playing = asyncio.create_task(player.play_stream(PcmFormat(16000), endless(chunk, closed)))
    await wait_for(lambda: player.is_playing and speaker.size() >= 3 * len(chunk))
    player.stop()
    assert await asyncio.wait_for(playing, 2) is False
    assert closed.is_set()
    assert not player.is_playing


async def test_stop_interrupts_a_sound_that_is_still_playing(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config(hold=30))
    pcm = tone(0.1)
    playing = asyncio.create_task(player.play_pcm(pcm, PcmFormat(16000)))
    await wait_for(lambda: speaker.size() == len(pcm))
    assert player.is_playing
    player.stop()
    assert await asyncio.wait_for(playing, 2) is False
    assert not player.is_playing


async def test_stop_interrupts_a_long_write(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config(pace=0.01))  # reads about as fast as aplay plays
    pcm = bytes(1 << 20)
    playing = asyncio.create_task(player.play_pcm(pcm, PcmFormat(16000)))
    await wait_for(lambda: speaker.size() > 0)
    await asyncio.sleep(0.05)
    player.stop()
    assert await asyncio.wait_for(playing, 2) is False
    assert speaker.size() < len(pcm)
    assert not player.is_playing


async def test_stop_leaves_queued_sounds_to_play(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    closed = asyncio.Event()
    first = asyncio.create_task(player.play_stream(PcmFormat(16000), endless(tone(0.01), closed)))
    await wait_for(lambda: speaker.size(0) > 0)
    pcm = tone(0.05)
    second = asyncio.create_task(player.play_pcm(pcm, PcmFormat(16000)))
    await asyncio.sleep(0.02)
    assert not second.done()
    player.stop()
    assert await asyncio.wait_for(first, 2) is False
    assert await asyncio.wait_for(second, 2) is True
    assert speaker.output(1) == pcm


async def test_stop_while_idle_does_not_affect_the_next_sound(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    player.stop()
    pcm = tone(0.05)
    assert await player.play_pcm(pcm, PcmFormat(16000)) is True
    assert speaker.output() == pcm


async def test_a_missing_player_raises_playback_error(tmp_path: Path) -> None:
    player = AudioPlayer(OutputConfig(command=f"{tmp_path / 'aplay'} -r {{rate}}"))
    with pytest.raises(PlaybackError, match="cannot start audio player"):
        await player.play_pcm(tone(0.01), PcmFormat(16000))
    assert not player.is_playing


async def test_player_errors_are_logged(speaker: Speaker, caplog) -> None:
    player = AudioPlayer(speaker.config(hold=-1))
    assert await player.play_pcm(tone(0.05), PcmFormat(16000)) is True  # not interrupted
    assert "Audio player exited with code 2: device unplugged" in caplog.text


# ---------------------------------------------------------------------------
# Volume


@pytest.fixture
def no_amixer(tmp_path: Path, monkeypatch) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


async def test_software_volume_without_a_mixer_control() -> None:
    player = FakePlayer()
    volume = Volume(player, control=None)
    await volume.setup(50)
    assert (volume.level, volume.effective, player.software_gain) == (50, 50, 0.25)
    assert await volume.set(80) == 80
    assert player.software_gain == pytest.approx(0.64)
    assert await volume.set(150) == 100
    assert player.software_gain == 1.0
    assert await volume.set(-5) == 0
    assert player.software_gain == 0.0
    assert player.played == []


async def test_speaker_mute_silences_and_restores_the_level() -> None:
    player = FakePlayer()
    volume = Volume(player, control=None)
    await volume.setup(60)
    await volume.set_muted(True)
    assert (volume.muted, volume.effective, player.software_gain) == (True, 0, 0.0)
    await volume.set(70)
    assert (volume.level, player.software_gain) == (70, 0.0)
    await volume.set_muted(False)
    assert volume.effective == 70
    assert player.software_gain == pytest.approx(0.49)


async def test_volume_falls_back_to_software_without_amixer(no_amixer, caplog) -> None:
    player = FakePlayer()
    volume = Volume(player, "Master")
    await volume.setup(40)
    # a softvol control only appears once its PCM has been opened, so it plays 50 ms of silence
    assert player.played == [("pcm", len(silence(0.05)))]
    assert player.software_gain == pytest.approx(0.16)
    assert "Mixer control 'Master' not found" in caplog.text


async def test_software_volume_scales_what_the_player_sends(speaker: Speaker) -> None:
    player = AudioPlayer(speaker.config())
    await Volume(player, None).setup(50)
    assert await player.play_pcm(pcm16([4000, -4000] * 100), PcmFormat(16000))
    assert samples(speaker.output()) == [1000, -1000] * 100


async def test_ducker_without_a_control_does_nothing(no_amixer, caplog) -> None:
    ducker = Ducker(None, None, 20)
    await ducker.duck()
    await ducker.restore()
    assert caplog.records == []


async def test_ducker_disables_itself_without_amixer(no_amixer, caplog) -> None:
    ducker = Ducker("Music", None, 20)
    await ducker.duck()
    await ducker.duck()
    await ducker.restore()
    assert caplog.text.count("Ducking disabled, mixer control 'Music'") == 1
    assert "Could not restore" not in caplog.text


# ---------------------------------------------------------------------------
# Sounds

# name: (seconds, loudest frequency)
EXPECTED_SOUNDS = {
    "wake": (0.18, 1175),
    "done": (0.15, 880),
    "error": (0.35, 262),
    "volume": (0.045, 1318),
    "timer": (1.16, 1568),
    "alarm": (1.2, 1000),
}


def test_every_builtin_sound_is_described() -> None:
    assert set(BUILTIN_SOUNDS) == set(EXPECTED_SOUNDS)


@pytest.mark.parametrize("name", BUILTIN_SOUNDS)
def test_builtin_sounds(name: str) -> None:
    seconds, frequency = EXPECTED_SOUNDS[name]
    sound = load_sound(f"builtin:{name}")
    assert isinstance(sound, Sound)
    assert sound.rate == 22050
    assert sound.seconds == pytest.approx(seconds, abs=0.002)
    wave = np.frombuffer(sound.pcm, dtype="<i2").astype(np.int32)
    assert wave[0] == 0 and abs(wave[-1]) < 100  # no clicks
    assert 8000 < np.abs(wave).max() < 0.9 * 32767
    spectrum = np.abs(np.fft.rfft(wave))
    loudest = np.fft.rfftfreq(len(wave), 1 / sound.rate)[spectrum.argmax()]
    assert abs(loudest - frequency) < 30


def test_ringing_sounds_end_with_a_pause() -> None:
    timer = np.frombuffer(load_sound("builtin:timer").pcm, dtype="<i2")
    alarm = np.frombuffer(load_sound("builtin:alarm").pcm, dtype="<i2")
    assert not timer[-int(0.5 * 22050) :].any()
    assert not alarm[-int(0.6 * 22050) :].any()
    error = np.frombuffer(load_sound("builtin:error").pcm, dtype="<i2")
    gap = error[int(0.12 * 22050) : int(0.17 * 22050)]
    assert not gap.any() and error[: int(0.12 * 22050)].any() and error[-100:].any()


def test_load_sound_specs() -> None:
    assert load_sound(None) is None
    assert load_sound("") is None
    with pytest.raises(KeyError):
        load_sound("builtin:doorbell")


def test_load_sound_from_wav_files(tmp_path: Path, monkeypatch) -> None:
    mono = tone(0.1, rate=16000)
    (tmp_path / "chime.wav").write_bytes(wav_bytes(mono, 16000))
    assert load_sound(str(tmp_path / "chime.wav")) == Sound(mono, 16000)

    left = [1000, 2000, -3000] * 10
    right = [3000, 0, -1000] * 10
    stereo = tmp_path / "stereo.wav"
    stereo.write_bytes(wav_bytes(pcm16(np.column_stack([left, right])), 44100, channels=2))
    sound = load_sound(str(stereo))
    assert sound is not None and sound.rate == 44100
    assert samples(sound.pcm) == [2000, 1000, -2000] * 10

    eight_bit = tmp_path / "beep8.wav"
    eight_bit.write_bytes(wav_bytes(bytes([0, 128, 255]), 8000, width=1))
    assert load_sound(str(eight_bit)) == Sound(pcm16([-32768, 0, 32512]), 8000)

    monkeypatch.setenv("HOME", str(tmp_path))
    assert load_sound("~/chime.wav") == Sound(mono, 16000)
