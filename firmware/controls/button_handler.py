#!/usr/bin/env python3
"""
Button Handler for Volume Control

Handles tactile button input with software debouncing and long-press detection.
Uses GPIO interrupts for responsive input without polling.

Hardware:
  - VOL_UP:   GPIO17 (Pin 11)
  - VOL_DOWN: GPIO27 (Pin 13)
  - MUTE:     GPIO22 (Pin 15)

Wiring: Buttons connect GPIO to GND when pressed.
        Internal pull-ups enabled in software.
"""

import time
import threading
from typing import Callable, Optional
from enum import Enum

try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    print("Warning: RPi.GPIO not available, using mock")
    HAS_GPIO = False

    class MockGPIO:
        BCM = 11
        OUT = 1
        IN = 0
        HIGH = 1
        LOW = 0
        PUD_UP = 22
        PUD_DOWN = 21
        FALLING = 32
        RISING = 31
        BOTH = 33

        _callbacks = {}

        @classmethod
        def setmode(cls, mode):
            pass

        @classmethod
        def setwarnings(cls, flag):
            pass

        @classmethod
        def setup(cls, pin, mode, pull_up_down=None):
            pass

        @classmethod
        def input(cls, pin):
            return cls.HIGH  # Not pressed (pull-up)

        @classmethod
        def add_event_detect(cls, pin, edge, callback=None, bouncetime=None):
            cls._callbacks[pin] = callback

        @classmethod
        def remove_event_detect(cls, pin):
            cls._callbacks.pop(pin, None)

        @classmethod
        def cleanup(cls, pins=None):
            pass

        @classmethod
        def simulate_press(cls, pin):
            """Simulate a button press (for testing)."""
            if pin in cls._callbacks:
                cls._callbacks[pin](pin)

    GPIO = MockGPIO()


class Button(Enum):
    """Button identifiers."""
    VOL_UP = "vol_up"
    VOL_DOWN = "vol_down"
    MUTE = "mute"


class ButtonEvent(Enum):
    """Button event types."""
    PRESS = "press"
    RELEASE = "release"
    LONG_PRESS = "long_press"
    REPEAT = "repeat"


class ButtonHandler:
    """
    GPIO button handler with debouncing and long-press detection.

    Features:
    - Software debouncing (configurable)
    - Long-press detection
    - Auto-repeat for volume buttons
    - Callback-based event handling
    - Thread-safe operation
    """

    # Default GPIO pins (BCM numbering)
    DEFAULT_PINS = {
        Button.VOL_UP: 17,
        Button.VOL_DOWN: 27,
        Button.MUTE: 22,
    }

    # Timing constants (seconds)
    DEBOUNCE_TIME = 0.05        # 50ms debounce
    LONG_PRESS_TIME = 0.8       # 800ms for long press
    REPEAT_DELAY = 0.3          # Initial delay before repeat
    REPEAT_INTERVAL = 0.1       # Interval between repeats

    def __init__(self, pins: Optional[dict] = None):
        """
        Initialize button handler.

        Args:
            pins: Dict mapping Button enum to GPIO pin numbers.
                  Uses DEFAULT_PINS if not specified.
        """
        self.pins = pins or self.DEFAULT_PINS.copy()
        self._callbacks = {
            Button.VOL_UP: None,
            Button.VOL_DOWN: None,
            Button.MUTE: None,
        }

        # Timing state
        self._last_press_time = {btn: 0 for btn in Button}
        self._press_start_time = {btn: 0 for btn in Button}
        self._is_pressed = {btn: False for btn in Button}

        # Thread management
        self._repeat_threads = {btn: None for btn in Button}
        self._stop_repeat = {btn: threading.Event() for btn in Button}
        self._lock = threading.Lock()

        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        for button, pin in self.pins.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                pin,
                GPIO.FALLING,
                callback=lambda p, b=button: self._on_button_press(b),
                bouncetime=int(self.DEBOUNCE_TIME * 1000)
            )

    def _on_button_press(self, button: Button):
        """
        Handle button press interrupt.

        Args:
            button: Which button was pressed
        """
        current_time = time.time()

        with self._lock:
            # Debounce check
            if current_time - self._last_press_time[button] < self.DEBOUNCE_TIME:
                return

            self._last_press_time[button] = current_time
            self._press_start_time[button] = current_time
            self._is_pressed[button] = True

        # Fire press callback immediately
        self._fire_callback(button, ButtonEvent.PRESS)

        # Start monitoring for long press / release
        thread = threading.Thread(
            target=self._monitor_button,
            args=(button,),
            daemon=True
        )
        thread.start()

    def _monitor_button(self, button: Button):
        """
        Monitor button state for long press and release.

        Args:
            button: Button to monitor
        """
        pin = self.pins[button]
        start_time = self._press_start_time[button]
        long_press_fired = False
        repeat_started = False

        while True:
            time.sleep(0.01)  # 10ms polling

            # Check if button is still pressed (LOW = pressed with pull-up)
            is_pressed = GPIO.input(pin) == GPIO.LOW

            if not is_pressed:
                # Button released
                with self._lock:
                    self._is_pressed[button] = False

                # Stop any repeat
                self._stop_repeat[button].set()

                # Don't fire release if we were repeating
                if not repeat_started:
                    self._fire_callback(button, ButtonEvent.RELEASE)
                break

            elapsed = time.time() - start_time

            # Check for long press
            if not long_press_fired and elapsed >= self.LONG_PRESS_TIME:
                long_press_fired = True
                self._fire_callback(button, ButtonEvent.LONG_PRESS)

                # Start auto-repeat for volume buttons
                if button in (Button.VOL_UP, Button.VOL_DOWN):
                    repeat_started = True
                    self._start_repeat(button)

    def _start_repeat(self, button: Button):
        """
        Start auto-repeat for volume buttons.

        Args:
            button: Button to repeat
        """
        self._stop_repeat[button].clear()

        def repeat_func():
            time.sleep(self.REPEAT_DELAY)
            while not self._stop_repeat[button].is_set():
                self._fire_callback(button, ButtonEvent.REPEAT)
                time.sleep(self.REPEAT_INTERVAL)

        thread = threading.Thread(target=repeat_func, daemon=True)
        thread.start()
        self._repeat_threads[button] = thread

    def _fire_callback(self, button: Button, event: ButtonEvent):
        """
        Fire the registered callback for a button event.

        Args:
            button: Which button
            event: What type of event
        """
        callback = self._callbacks.get(button)
        if callback:
            try:
                callback(button, event)
            except Exception as e:
                print(f"Button callback error: {e}")

    def on_press(self, button: Button, callback: Callable[[Button, ButtonEvent], None]):
        """
        Register a callback for button events.

        Args:
            button: Which button to handle
            callback: Function called with (button, event) arguments
        """
        self._callbacks[button] = callback

    def on_volume_up(self, callback: Callable[[Button, ButtonEvent], None]):
        """Register callback for volume up button."""
        self.on_press(Button.VOL_UP, callback)

    def on_volume_down(self, callback: Callable[[Button, ButtonEvent], None]):
        """Register callback for volume down button."""
        self.on_press(Button.VOL_DOWN, callback)

    def on_mute(self, callback: Callable[[Button, ButtonEvent], None]):
        """Register callback for mute button."""
        self.on_press(Button.MUTE, callback)

    def is_pressed(self, button: Button) -> bool:
        """Check if a button is currently pressed."""
        return self._is_pressed.get(button, False)

    def cleanup(self):
        """Clean up GPIO resources."""
        # Stop all repeat threads
        for btn in Button:
            self._stop_repeat[btn].set()

        # Remove event detection and cleanup GPIO
        for pin in self.pins.values():
            try:
                GPIO.remove_event_detect(pin)
            except Exception:
                pass

        GPIO.cleanup(list(self.pins.values()))


class VolumeController:
    """
    High-level volume control using buttons.

    Integrates ButtonHandler with system volume control via amixer.
    """

    def __init__(self, initial_volume: int = 50, step: int = 5):
        """
        Initialize volume controller.

        Args:
            initial_volume: Starting volume (0-100)
            step: Volume change per button press
        """
        self._volume = initial_volume
        self._muted = False
        self._pre_mute_volume = initial_volume
        self._step = step
        self._lock = threading.Lock()

        # Callbacks for external notification
        self.on_volume_change: Optional[Callable[[int], None]] = None
        self.on_mute_change: Optional[Callable[[bool], None]] = None

        # Setup button handler
        self.buttons = ButtonHandler()
        self.buttons.on_volume_up(self._handle_vol_up)
        self.buttons.on_volume_down(self._handle_vol_down)
        self.buttons.on_mute(self._handle_mute)

    @property
    def volume(self) -> int:
        return self._volume

    @volume.setter
    def volume(self, value: int):
        with self._lock:
            self._volume = max(0, min(100, value))
            self._apply_volume()

    @property
    def muted(self) -> bool:
        return self._muted

    def _handle_vol_up(self, button: Button, event: ButtonEvent):
        """Handle volume up button events."""
        if event in (ButtonEvent.PRESS, ButtonEvent.REPEAT):
            if self._muted:
                # Unmute and restore volume
                self._muted = False
                self._volume = self._pre_mute_volume
                if self.on_mute_change:
                    self.on_mute_change(False)
            else:
                self.volume = self._volume + self._step

            if self.on_volume_change:
                self.on_volume_change(self._volume)

    def _handle_vol_down(self, button: Button, event: ButtonEvent):
        """Handle volume down button events."""
        if event in (ButtonEvent.PRESS, ButtonEvent.REPEAT):
            if self._muted:
                # Unmute and restore volume
                self._muted = False
                self._volume = self._pre_mute_volume
                if self.on_mute_change:
                    self.on_mute_change(False)
            else:
                self.volume = self._volume - self._step

            if self.on_volume_change:
                self.on_volume_change(self._volume)

    def _handle_mute(self, button: Button, event: ButtonEvent):
        """Handle mute button events."""
        if event == ButtonEvent.PRESS:
            with self._lock:
                self._muted = not self._muted
                if self._muted:
                    self._pre_mute_volume = self._volume
                    self._apply_mute()
                else:
                    self._apply_volume()

            if self.on_mute_change:
                self.on_mute_change(self._muted)

    def _apply_volume(self):
        """Apply volume setting to system."""
        try:
            import subprocess
            subprocess.run(
                ['amixer', 'sset', 'Master', f'{self._volume}%'],
                capture_output=True,
                check=True
            )
        except FileNotFoundError:
            print(f"[Mock] Volume set to {self._volume}%")
        except Exception as e:
            print(f"Error setting volume: {e}")

    def _apply_mute(self):
        """Apply mute setting to system."""
        try:
            import subprocess
            subprocess.run(
                ['amixer', 'sset', 'Master', 'mute'],
                capture_output=True,
                check=True
            )
        except FileNotFoundError:
            print("[Mock] Muted")
        except Exception as e:
            print(f"Error muting: {e}")

    def cleanup(self):
        """Clean up resources."""
        self.buttons.cleanup()


# =============================================================================
# Test / Demo
# =============================================================================

if __name__ == "__main__":
    print("Button Handler Test")
    print("===================")
    print("Pins: VOL_UP=GPIO17, VOL_DOWN=GPIO27, MUTE=GPIO22")
    print("Press Ctrl+C to exit\n")

    def on_button(button: Button, event: ButtonEvent):
        print(f"  {button.value}: {event.value}")

    buttons = ButtonHandler()
    buttons.on_press(Button.VOL_UP, on_button)
    buttons.on_press(Button.VOL_DOWN, on_button)
    buttons.on_press(Button.MUTE, on_button)

    print("Waiting for button presses...")

    try:
        # If not on actual hardware, simulate some presses
        if not HAS_GPIO:
            print("\n[Simulating button presses for testing]\n")
            time.sleep(1)

            print("Simulating VOL_UP press...")
            GPIO.simulate_press(17)
            time.sleep(0.5)

            print("Simulating VOL_DOWN press...")
            GPIO.simulate_press(27)
            time.sleep(0.5)

            print("Simulating MUTE press...")
            GPIO.simulate_press(22)
            time.sleep(0.5)
        else:
            # On real hardware, just wait
            while True:
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nInterrupted")

    finally:
        buttons.cleanup()
        print("Cleanup complete")
