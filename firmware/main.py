#!/usr/bin/env python3
"""
Open Hardware Smart Speaker - Main Application

Coordinates display, status LEDs, and button controls for a Raspberry Pi-based
smart speaker that replaces the proprietary NS-CSPGASP internals.

Features:
- Time display on TM1637 7-segment display
- RGB status LED for visual feedback
- Volume control via tactile buttons
- Temperature display (optional, requires sensor)

Hardware:
- Raspberry Pi Zero 2 W
- TM1637 4-digit display (GPIO23/24)
- WS2812B RGB LEDs (GPIO10)
- Tactile buttons (GPIO17/27/22)
- MAX98357A I2S amplifiers (GPIO18/19/21)

Usage:
    python3 main.py

Or install as a systemd service for auto-start.
"""

import sys
import time
import signal
import argparse
import logging
from datetime import datetime
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, '/home/pi/open-speaker/firmware')

try:
    from display.tm1637_driver import TM1637, ClockDisplay
    from display.ws2812_status import StatusLED, Status
    from controls.button_handler import VolumeController, Button, ButtonEvent
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running from the firmware directory")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        # Uncomment to log to file:
        # logging.FileHandler('/var/log/open-speaker.log')
    ]
)
logger = logging.getLogger(__name__)


class OpenSpeaker:
    """
    Main application controller for the Open Hardware Smart Speaker.

    Manages:
    - Clock display with blinking colon
    - Status LED for system state
    - Volume control via buttons
    - Optional temperature display
    """

    # Display modes
    MODE_TIME = "time"
    MODE_TEMP = "temp"

    def __init__(
        self,
        initial_volume: int = 50,
        display_brightness: int = 3,
        led_brightness: float = 0.3,
    ):
        """
        Initialize the speaker system.

        Args:
            initial_volume: Starting volume level (0-100)
            display_brightness: 7-segment brightness (0-7)
            led_brightness: RGB LED brightness (0.0-1.0)
        """
        logger.info("Initializing Open Speaker...")

        # State
        self._running = False
        self._display_mode = self.MODE_TIME
        self._volume_display_timeout = 0
        self._colon_state = True

        # Initialize components
        logger.info("  Initializing display...")
        self.display = TM1637(clk_pin=23, dio_pin=24)
        self.display.brightness(display_brightness)

        logger.info("  Initializing status LED...")
        self.status_led = StatusLED(num_leds=3)
        self.status_led.brightness = led_brightness

        logger.info("  Initializing volume controller...")
        self.volume = VolumeController(initial_volume=initial_volume)
        self.volume.on_volume_change = self._on_volume_change
        self.volume.on_mute_change = self._on_mute_change

        # Temperature sensor (optional)
        self._temperature: Optional[float] = None

        logger.info("Initialization complete")

    def _on_volume_change(self, level: int):
        """Handle volume change event."""
        logger.debug(f"Volume: {level}%")

        # Show volume on display temporarily
        self.display.show_volume(level)
        self._volume_display_timeout = time.time() + 2.0

        # Flash status LED
        self.status_led.flash_volume(level)

    def _on_mute_change(self, muted: bool):
        """Handle mute state change."""
        logger.info(f"Mute: {'ON' if muted else 'OFF'}")

        if muted:
            self.display.show("MUTE")
            self._volume_display_timeout = time.time() + 2.0
        else:
            # Show current volume
            self._on_volume_change(self.volume.volume)

    def _update_display(self):
        """Update the main display."""
        # Skip if volume overlay is active
        if time.time() < self._volume_display_timeout:
            return

        if self._display_mode == self.MODE_TIME:
            # Show current time with blinking colon
            now = datetime.now()
            self._colon_state = not self._colon_state
            self.display.show_time(now.hour, now.minute, self._colon_state)

        elif self._display_mode == self.MODE_TEMP:
            # Show temperature if available
            if self._temperature is not None:
                self.display.show_temperature(self._temperature, 'C')
            else:
                self.display.show("----")

    def set_temperature(self, temp: float):
        """
        Update temperature reading.

        Args:
            temp: Temperature in Celsius
        """
        self._temperature = temp

    def set_status(self, status: Status):
        """
        Set the system status (updates LED).

        Args:
            status: Status enum value
        """
        self.status_led.set_status(status)

    def run(self):
        """Run the main application loop."""
        logger.info("Starting main loop...")
        self._running = True

        # Set initial status to idle
        self.status_led.idle()

        # Show startup animation
        self.display.scroll("HELO", 0.2)
        time.sleep(0.5)

        try:
            while self._running:
                self._update_display()
                time.sleep(0.5)  # Update every 500ms

        except KeyboardInterrupt:
            logger.info("Interrupted by user")

        finally:
            self.shutdown()

    def shutdown(self):
        """Clean shutdown of all components."""
        logger.info("Shutting down...")
        self._running = False

        # Show goodbye message
        self.display.show(" bYE")
        time.sleep(0.5)

        # Cleanup
        self.display.cleanup()
        self.status_led.cleanup()
        self.volume.cleanup()

        logger.info("Shutdown complete")


def signal_handler(sig, frame):
    """Handle termination signals."""
    logger.info(f"Received signal {sig}")
    sys.exit(0)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Open Hardware Smart Speaker Controller"
    )
    parser.add_argument(
        '-v', '--volume',
        type=int,
        default=50,
        help="Initial volume level (0-100, default: 50)"
    )
    parser.add_argument(
        '-b', '--brightness',
        type=int,
        default=3,
        help="Display brightness (0-7, default: 3)"
    )
    parser.add_argument(
        '-l', '--led-brightness',
        type=float,
        default=0.3,
        help="LED brightness (0.0-1.0, default: 0.3)"
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help="Enable debug logging"
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Create and run speaker
    speaker = OpenSpeaker(
        initial_volume=args.volume,
        display_brightness=args.brightness,
        led_brightness=args.led_brightness,
    )

    speaker.run()


if __name__ == "__main__":
    main()
