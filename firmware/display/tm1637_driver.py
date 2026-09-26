#!/usr/bin/env python3
"""
TM1637 4-Digit 7-Segment Display Driver

Controls a TM1637-based display for showing time, temperature, and volume.
Uses a bit-banged protocol on GPIO pins.

Hardware: TM1637 4-digit 7-segment display module
Pinout:
  - CLK: GPIO23 (Pin 16)
  - DIO: GPIO24 (Pin 18)
  - VCC: 3.3V or 5V
  - GND: Ground
"""

import time

try:
    import RPi.GPIO as GPIO
except ImportError:
    # Mock for development on non-Pi systems
    print("Warning: RPi.GPIO not available, using mock")

    class MockGPIO:
        BCM = 11
        OUT = 1
        IN = 0
        HIGH = 1
        LOW = 0

        @staticmethod
        def setmode(mode):
            pass

        @staticmethod
        def setwarnings(flag):
            pass

        @staticmethod
        def setup(pin, mode):
            pass

        @staticmethod
        def output(pin, value):
            pass

        @staticmethod
        def input(pin):
            return 1

        @staticmethod
        def cleanup():
            pass

    GPIO = MockGPIO()


class TM1637:
    """
    TM1637 4-digit 7-segment display driver.

    Protocol: Custom serial interface (not I2C/SPI)
    - Start: DIO goes LOW while CLK is HIGH
    - Data: Bits shifted on CLK falling edge, LSB first
    - ACK: After 8 bits, device pulls DIO LOW
    - Stop: DIO goes HIGH while CLK is HIGH
    """

    # Segment bit positions
    #      A
    #     ---
    #  F |   | B
    #     -G-
    #  E |   | C
    #     ---
    #      D   .DP

    # Segment encoding: 0bDPGFEDCBA
    DIGITS = {
        0: 0b00111111,  # 0
        1: 0b00000110,  # 1
        2: 0b01011011,  # 2
        3: 0b01001111,  # 3
        4: 0b01100110,  # 4
        5: 0b01101101,  # 5
        6: 0b01111101,  # 6
        7: 0b00000111,  # 7
        8: 0b01111111,  # 8
        9: 0b01101111,  # 9
    }

    CHARS = {
        ' ': 0b00000000,
        '-': 0b01000000,
        '_': 0b00001000,
        '°': 0b01100011,  # Degree symbol
        'A': 0b01110111,
        'b': 0b01111100,
        'C': 0b00111001,
        'c': 0b01011000,
        'd': 0b01011110,
        'E': 0b01111001,
        'F': 0b01110001,
        'H': 0b01110110,
        'h': 0b01110100,
        'I': 0b00000110,
        'J': 0b00011110,
        'L': 0b00111000,
        'n': 0b01010100,
        'o': 0b01011100,
        'P': 0b01110011,
        'r': 0b01010000,
        'S': 0b01101101,
        't': 0b01111000,
        'U': 0b00111110,
        'u': 0b00011100,
        'V': 0b00111110,  # Same as U
        'Y': 0b01101110,
    }

    # Commands
    CMD_DATA = 0x40      # Data command setting
    CMD_ADDR = 0xC0      # Address command setting
    CMD_DISPLAY = 0x80   # Display control command

    def __init__(self, clk_pin: int = 23, dio_pin: int = 24):
        """
        Initialize TM1637 display.

        Args:
            clk_pin: GPIO pin for CLK (BCM numbering)
            dio_pin: GPIO pin for DIO (BCM numbering)
        """
        self.clk_pin = clk_pin
        self.dio_pin = dio_pin
        self._brightness = 7  # 0-7
        self._on = True
        self._colon = False

        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(self.clk_pin, GPIO.OUT)
        GPIO.setup(self.dio_pin, GPIO.OUT)

        # Start with display on
        self.clear()

    def _delay(self):
        """Bit timing delay (~10µs)."""
        time.sleep(0.00001)

    def _start(self):
        """Send start condition: DIO LOW while CLK HIGH."""
        GPIO.output(self.dio_pin, GPIO.HIGH)
        GPIO.output(self.clk_pin, GPIO.HIGH)
        self._delay()
        GPIO.output(self.dio_pin, GPIO.LOW)
        self._delay()

    def _stop(self):
        """Send stop condition: DIO HIGH while CLK HIGH."""
        GPIO.output(self.clk_pin, GPIO.LOW)
        self._delay()
        GPIO.output(self.dio_pin, GPIO.LOW)
        self._delay()
        GPIO.output(self.clk_pin, GPIO.HIGH)
        self._delay()
        GPIO.output(self.dio_pin, GPIO.HIGH)
        self._delay()

    def _write_byte(self, data: int):
        """
        Write a byte to the display, LSB first.

        Args:
            data: Byte to write (0-255)
        """
        for _ in range(8):
            GPIO.output(self.clk_pin, GPIO.LOW)
            self._delay()
            GPIO.output(self.dio_pin, GPIO.HIGH if (data & 0x01) else GPIO.LOW)
            self._delay()
            GPIO.output(self.clk_pin, GPIO.HIGH)
            self._delay()
            data >>= 1

        # Wait for ACK
        GPIO.output(self.clk_pin, GPIO.LOW)
        GPIO.setup(self.dio_pin, GPIO.IN)
        self._delay()
        GPIO.output(self.clk_pin, GPIO.HIGH)
        self._delay()
        # ACK bit is read here (ignored)
        GPIO.output(self.clk_pin, GPIO.LOW)
        GPIO.setup(self.dio_pin, GPIO.OUT)
        self._delay()

    def _encode_char(self, char) -> int:
        """
        Encode a character to segment data.

        Args:
            char: Character to encode (digit, letter, or symbol)

        Returns:
            Segment byte (0bDPGFEDCBA)
        """
        if isinstance(char, int) and 0 <= char <= 9:
            return self.DIGITS[char]
        if isinstance(char, str) and len(char) == 1:
            if char.isdigit():
                return self.DIGITS[int(char)]
            return self.CHARS.get(char, 0)
        return 0

    def brightness(self, level: int):
        """
        Set display brightness.

        Args:
            level: Brightness level (0-7)
        """
        self._brightness = max(0, min(7, level))
        self._update_display_control()

    def on(self):
        """Turn display on."""
        self._on = True
        self._update_display_control()

    def off(self):
        """Turn display off."""
        self._on = False
        self._update_display_control()

    def _update_display_control(self):
        """Send display control command."""
        self._start()
        if self._on:
            self._write_byte(self.CMD_DISPLAY | 0x08 | self._brightness)
        else:
            self._write_byte(self.CMD_DISPLAY)
        self._stop()

    def show(self, data: str):
        """
        Show a string on the display (up to 4 characters).

        Args:
            data: String to display (max 4 chars)
        """
        # Pad or truncate to 4 characters
        data = str(data)[:4].ljust(4)

        # Encode characters
        segments = [self._encode_char(c) for c in data]

        # Add colon to digit 1 (second digit) if enabled
        if self._colon:
            segments[1] |= 0x80  # DP bit acts as colon

        # Send data command
        self._start()
        self._write_byte(self.CMD_DATA)
        self._stop()

        # Send address and data
        self._start()
        self._write_byte(self.CMD_ADDR)  # Start at address 0
        for seg in segments:
            self._write_byte(seg)
        self._stop()

        # Update display control
        self._update_display_control()

    def clear(self):
        """Clear the display."""
        self.show("    ")

    def colon(self, on: bool):
        """
        Enable/disable the colon between digit 2 and 3.

        Args:
            on: True to enable colon
        """
        self._colon = on

    def numbers(self, num1: int, num2: int, colon: bool = True):
        """
        Display two 2-digit numbers (e.g., for time).

        Args:
            num1: First number (0-99)
            num2: Second number (0-99)
            colon: Show colon between numbers
        """
        self._colon = colon
        text = f"{num1:02d}{num2:02d}"
        self.show(text)

    def show_time(self, hour: int, minute: int, colon: bool = True):
        """
        Display time in HH:MM format.

        Args:
            hour: Hour (0-23)
            minute: Minute (0-59)
            colon: Show colon (usually blinked)
        """
        self.numbers(hour, minute, colon)

    def show_temperature(self, temp: float, unit: str = 'C'):
        """
        Display temperature with unit.

        Args:
            temp: Temperature value
            unit: 'C' or 'F'
        """
        self._colon = False
        if -9 <= temp <= 99:
            text = f"{int(temp):2d}°{unit}"
        else:
            text = f"{int(temp):3d}{unit}"
        self.show(text)

    def show_volume(self, level: int):
        """
        Display volume level.

        Args:
            level: Volume level (0-100)
        """
        self._colon = False
        self.show(f"V{level:3d}"[:4])

    def scroll(self, text: str, delay: float = 0.3):
        """
        Scroll text across the display.

        Args:
            text: Text to scroll
            delay: Delay between scroll steps (seconds)
        """
        padded = "    " + text + "    "
        for i in range(len(padded) - 3):
            self.show(padded[i:i + 4])
            time.sleep(delay)

    def cleanup(self):
        """Clean up GPIO resources."""
        self.clear()
        self.off()
        GPIO.cleanup([self.clk_pin, self.dio_pin])


class ClockDisplay:
    """
    High-level clock display controller with mode switching.

    Modes:
    - TIME: Show current time with blinking colon
    - TEMP: Show temperature
    - VOLUME: Show volume level (temporary overlay)
    """

    MODE_TIME = "time"
    MODE_TEMP = "temp"
    MODE_VOLUME = "volume"

    def __init__(self, clk_pin: int = 23, dio_pin: int = 24):
        self.display = TM1637(clk_pin, dio_pin)
        self.display.brightness(3)  # Medium brightness
        self._mode = self.MODE_TIME
        self._volume_timeout = 0
        self._colon_state = True

    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str):
        if value in (self.MODE_TIME, self.MODE_TEMP, self.MODE_VOLUME):
            self._mode = value

    def update_time(self, hour: int, minute: int):
        """Update time display with blinking colon."""
        if self._mode == self.MODE_TIME and time.time() > self._volume_timeout:
            self._colon_state = not self._colon_state
            self.display.show_time(hour, minute, self._colon_state)

    def update_temperature(self, temp: float, unit: str = 'C'):
        """Update temperature display."""
        if self._mode == self.MODE_TEMP and time.time() > self._volume_timeout:
            self.display.show_temperature(temp, unit)

    def flash_volume(self, level: int, duration: float = 2.0):
        """
        Temporarily show volume level, then return to normal mode.

        Args:
            level: Volume level (0-100)
            duration: How long to show volume (seconds)
        """
        self.display.show_volume(level)
        self._volume_timeout = time.time() + duration

    def cleanup(self):
        """Clean up resources."""
        self.display.cleanup()


# =============================================================================
# Test / Demo
# =============================================================================

if __name__ == "__main__":
    print("TM1637 Display Test")
    print("==================")

    display = TM1637(clk_pin=23, dio_pin=24)

    try:
        # Test brightness levels
        print("Testing brightness levels...")
        for b in range(8):
            display.brightness(b)
            display.show("8888")
            time.sleep(0.3)

        # Test digits
        print("Testing digits 0-9...")
        for d in range(10):
            display.show(f"{d}{d}{d}{d}")
            time.sleep(0.2)

        # Test time display
        print("Testing time display...")
        for m in range(60):
            display.show_time(12, m, m % 2 == 0)
            time.sleep(0.05)

        # Test temperature
        print("Testing temperature display...")
        for t in range(15, 35):
            display.show_temperature(t, 'C')
            time.sleep(0.1)

        # Test volume
        print("Testing volume display...")
        for v in range(0, 101, 5):
            display.show_volume(v)
            time.sleep(0.1)

        # Test scroll
        print("Testing scroll...")
        display.scroll("HELLO WORLD", 0.2)

        # Test characters
        print("Testing characters...")
        display.show("AbCd")
        time.sleep(1)
        display.show("HELP")
        time.sleep(1)

        print("Test complete!")

    except KeyboardInterrupt:
        print("\nInterrupted")

    finally:
        display.cleanup()
        print("Cleanup complete")
