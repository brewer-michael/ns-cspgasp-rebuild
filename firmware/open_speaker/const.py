"""Constants shared across the application."""

from typing import Final

# Every stage of the voice pipeline works on 16 kHz, 16-bit, mono PCM.
SAMPLE_RATE: Final = 16000
SAMPLE_WIDTH: Final = 2
SAMPLE_CHANNELS: Final = 1

DEFAULT_CONFIG_PATH: Final = "/etc/open-speaker/config.yaml"
DEFAULT_STATE_DIR: Final = "/var/lib/open-speaker"
DEFAULT_API_PORT: Final = 10800

# Raspberry Pi GPIO (BCM) pins that the audio path owns. With the
# googlevoicehat-soundcard overlay the kernel also drives GPIO16 (amp SD_MODE),
# so nothing else may use it.
I2S_PINS: Final = frozenset({18, 19, 20, 21})
I2S_RESERVED_PINS: Final = frozenset({16})
I2C_PINS: Final = frozenset({2, 3})
SPI0_PINS: Final = frozenset({8, 9, 10, 11})
