"""Command line: ``open-speaker run`` and helper commands for setup and testing."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import math
import signal
import sys
import time
from importlib import resources
from pathlib import Path

import aiohttp
import yaml

from . import __version__
from .config import Config, ConfigError, config_to_dict, load_config
from .const import DEFAULT_CONFIG_PATH

_LOGGER = logging.getLogger("open_speaker")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load(args: argparse.Namespace) -> Config:
    try:
        return load_config(args.config)
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------


async def _run(config: Config) -> None:
    from .factory import build_speaker

    async with aiohttp.ClientSession() as session:
        speaker = build_speaker(config, session)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, speaker.request_stop)
        await speaker.run()


def cmd_run(args: argparse.Namespace) -> None:
    config = _load(args)
    _setup_logging("DEBUG" if args.debug else config.log_level)
    _LOGGER.info("Open Speaker %s starting (%s mode)", __version__, config.pipeline.mode)
    asyncio.run(_run(config))


def cmd_check_config(args: argparse.Namespace) -> None:
    config = _load(args)
    print(yaml.safe_dump(config_to_dict(config), sort_keys=False).rstrip())
    print(f"\n{args.config}: OK", file=sys.stderr)


def cmd_example_config(args: argparse.Namespace) -> None:
    text = resources.files("open_speaker").joinpath("data/config.example.yaml").read_text()
    sys.stdout.write(text)


def cmd_doctor(args: argparse.Namespace) -> None:
    from .doctor import run_doctor

    _setup_logging("DEBUG" if args.debug else "WARNING")
    sys.exit(asyncio.run(run_doctor(Path(args.config))))


async def _test_speaker(config: Config, speak: str | None) -> None:
    from .audio.playback import AudioPlayer, PcmFormat
    from .audio.sounds import load_sound

    player = AudioPlayer(config.audio.output)
    for name in ("wake", "done", "timer"):
        sound = load_sound(f"builtin:{name}")
        assert sound is not None
        print(f"Playing {name} sound...")
        await player.play_pcm(sound.pcm, PcmFormat(sound.rate))
        await asyncio.sleep(0.3)
    if speak:
        await _say(config, speak)


def cmd_test_speaker(args: argparse.Namespace) -> None:
    config = _load(args)
    _setup_logging("DEBUG" if args.debug else "WARNING")
    asyncio.run(_test_speaker(config, args.say))


async def _test_mic(config: Config, seconds: float, save: str | None) -> None:
    from .audio.capture import Microphone
    from .audio.pcm import rms_dbfs, wav_bytes
    from .const import SAMPLE_RATE

    mic = Microphone(config.audio.input)
    print(f"Recording {seconds:.0f} s from {config.audio.input.device!r}; speak now...")
    recorded = bytearray()
    start = time.monotonic()
    async for chunk in mic.chunks():
        recorded += chunk
        level = rms_dbfs(chunk)
        width = 0 if math.isinf(level) else max(0, int((level + 70) / 70 * 50))
        print(f"\r{level:6.1f} dBFS |{'#' * width:<50}|", end="", flush=True)
        if time.monotonic() - start >= seconds:
            break
    await mic.close()
    peak = rms_dbfs(bytes(recorded))
    print(f"\nAverage level {peak:.1f} dBFS.")
    if peak < -60:
        print("That is very quiet: check the microphone wiring, L/R pins and audio.input.channel.")
    if save:
        Path(save).write_bytes(wav_bytes(bytes(recorded), SAMPLE_RATE))
        print(f"Saved {save}")


def cmd_test_mic(args: argparse.Namespace) -> None:
    config = _load(args)
    _setup_logging("DEBUG" if args.debug else "WARNING")
    asyncio.run(_test_mic(config, args.seconds, args.save))


async def _say(config: Config, text: str) -> None:
    from .audio.playback import AudioPlayer
    from .factory import create_homeassistant, create_pipeline

    async with aiohttp.ClientSession() as session:
        ha = create_homeassistant(config, session)
        pipeline = create_pipeline(config, session, ha)
        audio = await pipeline.speak(text, config.language)
        if audio is not None:
            await AudioPlayer(config.audio.output).play(audio)
        if ha is not None:
            await ha.close()


def cmd_say(args: argparse.Namespace) -> None:
    config = _load(args)
    _setup_logging("DEBUG" if args.debug else "WARNING")
    asyncio.run(_say(config, " ".join(args.text)))


async def _ask(config: Config, text: str, speak: bool) -> None:
    from .audio.playback import AudioPlayer
    from .factory import create_homeassistant, create_pipeline
    from .intents import recognize
    from .pipeline import Conversation

    intent = recognize(text) if config.pipeline.local_intents else None
    if intent is not None:
        print(f"(handled on the speaker by the running service: {intent})")
        return
    async with aiohttp.ClientSession() as session:
        ha = create_homeassistant(config, session)
        pipeline = create_pipeline(config, session, ha)
        reply = await pipeline.respond(text, Conversation(config.language))
        print(reply.text or "(no spoken reply)")
        if speak and reply.audio is not None:
            await AudioPlayer(config.audio.output).play(reply.audio)
        if ha is not None:
            await ha.close()


def cmd_ask(args: argparse.Namespace) -> None:
    config = _load(args)
    _setup_logging("DEBUG" if args.debug else "WARNING")
    asyncio.run(_ask(config, " ".join(args.text), not args.quiet))


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="open-speaker",
        description="Open-hardware smart speaker and alarm clock for Home Assistant.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-c", "--config", default=DEFAULT_CONFIG_PATH, help=f"default: {DEFAULT_CONFIG_PATH}"
    )
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="run the speaker (default)").set_defaults(func=cmd_run)
    sub.add_parser("check-config", help="validate and print the effective configuration")
    sub.choices["check-config"].set_defaults(func=cmd_check_config)
    sub.add_parser("example-config", help="print a commented example configuration")
    sub.choices["example-config"].set_defaults(func=cmd_example_config)
    sub.add_parser("doctor", help="check hardware, audio devices and servers")
    sub.choices["doctor"].set_defaults(func=cmd_doctor)

    speaker = sub.add_parser("test-speaker", help="play test sounds")
    speaker.add_argument("--say", help="also speak this text through the voice pipeline")
    speaker.set_defaults(func=cmd_test_speaker)

    mic = sub.add_parser("test-mic", help="show microphone levels")
    mic.add_argument("--seconds", type=float, default=5.0)
    mic.add_argument("--save", help="write the recording to this WAV file")
    mic.set_defaults(func=cmd_test_mic)

    say = sub.add_parser("say", help="speak text through the voice pipeline")
    say.add_argument("text", nargs="+")
    say.set_defaults(func=cmd_say)

    ask = sub.add_parser("ask", help="send a typed request to the assistant")
    ask.add_argument("text", nargs="+")
    ask.add_argument("-q", "--quiet", action="store_true", help="print the reply only")
    ask.set_defaults(func=cmd_ask)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", cmd_run)
    func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
