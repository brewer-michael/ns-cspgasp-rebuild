#!/usr/bin/env python3
"""
WS2812B RGB LED Status Indicator Driver

Controls addressable RGB LEDs for visual status feedback.
Uses hardware PWM via the rpi_ws281x library for reliable timing.

Hardware: WS2812B / NeoPixel LEDs
Pinout:
  - DATA: GPIO10 (Pin 19) - SPI MOSI for hardware PWM
  - VCC: 5V
  - GND: Ground

Status States:
  - IDLE: Dim blue (standby)
  - LISTENING: Solid green (wake word detected)
  - THINKING: Pulsing cyan (processing)
  - SPEAKING: Pulsing blue (TTS active)
  - ERROR: Solid red (error state)
  - VOLUME: Flash white (volume change feedback)
"""

import time
import threading
from enum import Enum
from typing import Tuple, Optional

try:
    import board
    import neopixel
    HAS_NEOPIXEL = True
except ImportError:
    print("Warning: neopixel library not available, using mock")
    HAS_NEOPIXEL = False


class Status(Enum):
    """LED status states."""
    OFF = "off"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    VOLUME = "volume"
    CUSTOM = "custom"


# Color definitions (RGB tuples, 0-255)
COLORS = {
    'off': (0, 0, 0),
    'white': (255, 255, 255),
    'red': (255, 0, 0),
    'green': (0, 255, 0),
    'blue': (0, 0, 255),
    'cyan': (0, 255, 255),
    'yellow': (255, 255, 0),
    'magenta': (255, 0, 255),
    'orange': (255, 128, 0),
    'purple': (128, 0, 255),
}


class MockPixels:
    """Mock NeoPixel class for development without hardware."""

    def __init__(self, pin, num_pixels, auto_write=True):
        self.n = num_pixels
        self._pixels = [(0, 0, 0)] * num_pixels
        self.auto_write = auto_write
        self._brightness = 1.0

    def __setitem__(self, key, value):
        self._pixels[key] = value
        if self.auto_write:
            self.show()

    def __getitem__(self, key):
        return self._pixels[key]

    def fill(self, color):
        self._pixels = [color] * self.n
        if self.auto_write:
            self.show()

    def show(self):
        pass  # No-op in mock

    @property
    def brightness(self):
        return self._brightness

    @brightness.setter
    def brightness(self, value):
        self._brightness = max(0, min(1, value))

    def deinit(self):
        pass


class StatusLED:
    """
    WS2812B RGB LED controller for status indication.

    Features:
    - Multiple status states with predefined colors
    - Smooth pulsing animations
    - Thread-safe state changes
    - Brightness control
    """

    # Animation parameters
    PULSE_SPEED = 0.02      # Seconds per animation step
    PULSE_MIN = 0.1         # Minimum brightness during pulse
    PULSE_MAX = 1.0         # Maximum brightness during pulse
    FLASH_DURATION = 0.1    # Duration of flash effect

    def __init__(self, pin=board.D10 if HAS_NEOPIXEL else 10, num_leds: int = 3):
        """
        Initialize LED controller.

        Args:
            pin: GPIO pin for data (default: GPIO10 / board.D10)
            num_leds: Number of LEDs in strip/ring
        """
        self.num_leds = num_leds
        self._brightness = 0.3  # Default to 30% to avoid blinding

        if HAS_NEOPIXEL:
            self.pixels = neopixel.NeoPixel(
                pin,
                num_leds,
                brightness=self._brightness,
                auto_write=False,
                pixel_order=neopixel.GRB  # Most WS2812B are GRB
            )
        else:
            self.pixels = MockPixels(pin, num_leds, auto_write=False)

        # State management
        self._status = Status.OFF
        self._custom_color = COLORS['off']
        self._running = False
        self._animation_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Start with LEDs off
        self._set_color(COLORS['off'])

    @property
    def brightness(self) -> float:
        return self._brightness

    @brightness.setter
    def brightness(self, value: float):
        """Set overall brightness (0.0 - 1.0)."""
        self._brightness = max(0, min(1, value))
        self.pixels.brightness = self._brightness
        self.pixels.show()

    @property
    def status(self) -> Status:
        return self._status

    def _set_color(self, color: Tuple[int, int, int]):
        """Set all LEDs to a solid color."""
        self.pixels.fill(color)
        self.pixels.show()

    def _scale_color(self, color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
        """Scale a color's intensity by a factor."""
        return tuple(int(c * factor) for c in color)

    def _pulse_animation(self, color: Tuple[int, int, int]):
        """
        Run a pulsing animation in a loop.

        Args:
            color: Base color to pulse
        """
        phase = 0
        direction = 1

        while self._running:
            # Calculate brightness using sine-like curve
            intensity = self.PULSE_MIN + (self.PULSE_MAX - self.PULSE_MIN) * phase

            scaled_color = self._scale_color(color, intensity)
            self._set_color(scaled_color)

            # Update phase
            phase += 0.05 * direction
            if phase >= 1:
                direction = -1
            elif phase <= 0:
                direction = 1

            time.sleep(self.PULSE_SPEED)

    def _start_animation(self, color: Tuple[int, int, int]):
        """Start pulsing animation in background thread."""
        self._stop_animation()
        self._running = True
        self._animation_thread = threading.Thread(
            target=self._pulse_animation,
            args=(color,),
            daemon=True
        )
        self._animation_thread.start()

    def _stop_animation(self):
        """Stop any running animation."""
        self._running = False
        if self._animation_thread and self._animation_thread.is_alive():
            self._animation_thread.join(timeout=0.5)
        self._animation_thread = None

    def set_status(self, status: Status):
        """
        Set LED status state.

        Args:
            status: Status enum value
        """
        with self._lock:
            if status == self._status:
                return

            self._stop_animation()
            self._status = status

            if status == Status.OFF:
                self._set_color(COLORS['off'])

            elif status == Status.IDLE:
                # Dim blue - standby
                self._set_color(self._scale_color(COLORS['blue'], 0.1))

            elif status == Status.LISTENING:
                # Solid green - wake word detected
                self._set_color(COLORS['green'])

            elif status == Status.THINKING:
                # Pulsing cyan - processing
                self._start_animation(COLORS['cyan'])

            elif status == Status.SPEAKING:
                # Pulsing blue - TTS active
                self._start_animation(COLORS['blue'])

            elif status == Status.ERROR:
                # Solid red - error
                self._set_color(COLORS['red'])

            elif status == Status.VOLUME:
                # Handled by flash_volume()
                pass

            elif status == Status.CUSTOM:
                self._set_color(self._custom_color)

    def off(self):
        """Turn off LEDs."""
        self.set_status(Status.OFF)

    def idle(self):
        """Set idle (standby) state."""
        self.set_status(Status.IDLE)

    def listening(self):
        """Set listening state (wake word detected)."""
        self.set_status(Status.LISTENING)

    def thinking(self):
        """Set thinking state (processing)."""
        self.set_status(Status.THINKING)

    def speaking(self):
        """Set speaking state (TTS active)."""
        self.set_status(Status.SPEAKING)

    def error(self):
        """Set error state."""
        self.set_status(Status.ERROR)

    def custom(self, color: Tuple[int, int, int]):
        """
        Set custom color.

        Args:
            color: RGB tuple (0-255 each)
        """
        self._custom_color = color
        self.set_status(Status.CUSTOM)

    def flash(self, color: Tuple[int, int, int], times: int = 1, duration: float = 0.1):
        """
        Flash a color.

        Args:
            color: RGB tuple to flash
            times: Number of flashes
            duration: Duration of each flash
        """
        previous_status = self._status

        for _ in range(times):
            self._set_color(color)
            time.sleep(duration)
            self._set_color(COLORS['off'])
            time.sleep(duration)

        # Restore previous state
        self.set_status(previous_status)

    def flash_volume(self, level: int):
        """
        Flash white to indicate volume change.

        Args:
            level: Volume level (used for brightness scaling)
        """
        intensity = max(0.2, level / 100)
        flash_color = self._scale_color(COLORS['white'], intensity)
        self._set_color(flash_color)
        time.sleep(0.15)

        # Return to previous state
        self.set_status(self._status)

    def rainbow_cycle(self, duration: float = 3.0):
        """
        Run a rainbow color cycle (for testing/celebration).

        Args:
            duration: Total duration in seconds
        """
        start_time = time.time()

        while time.time() - start_time < duration:
            # Calculate hue based on time
            hue = ((time.time() - start_time) / duration) * 360

            # Convert HSV to RGB (simplified)
            h = hue / 60
            i = int(h)
            f = h - i
            p, q, t = 0, int(255 * (1 - f)), int(255 * f)

            if i == 0:
                color = (255, t, p)
            elif i == 1:
                color = (q, 255, p)
            elif i == 2:
                color = (p, 255, t)
            elif i == 3:
                color = (p, q, 255)
            elif i == 4:
                color = (t, p, 255)
            else:
                color = (255, p, q)

            self._set_color(color)
            time.sleep(0.02)

    def cleanup(self):
        """Clean up resources."""
        self._stop_animation()
        self._set_color(COLORS['off'])
        if HAS_NEOPIXEL:
            self.pixels.deinit()


# =============================================================================
# Test / Demo
# =============================================================================

if __name__ == "__main__":
    print("WS2812B Status LED Test")
    print("=======================")

    # Initialize with 3 LEDs
    leds = StatusLED(num_leds=3)
    leds.brightness = 0.3  # 30% brightness

    try:
        print("Testing status states...")

        print("  IDLE (dim blue)...")
        leds.idle()
        time.sleep(2)

        print("  LISTENING (solid green)...")
        leds.listening()
        time.sleep(2)

        print("  THINKING (pulsing cyan)...")
        leds.thinking()
        time.sleep(4)

        print("  SPEAKING (pulsing blue)...")
        leds.speaking()
        time.sleep(4)

        print("  ERROR (solid red)...")
        leds.error()
        time.sleep(2)

        print("Testing flash effects...")
        leds.idle()

        print("  Flash white (volume)...")
        for v in [25, 50, 75, 100]:
            print(f"    Volume: {v}")
            leds.flash_volume(v)
            time.sleep(0.5)

        print("  Flash colors...")
        leds.flash(COLORS['green'], times=3)
        leds.flash(COLORS['red'], times=3)

        print("Testing rainbow cycle...")
        leds.rainbow_cycle(duration=3.0)

        print("Test complete!")

    except KeyboardInterrupt:
        print("\nInterrupted")

    finally:
        leds.cleanup()
        print("Cleanup complete")
