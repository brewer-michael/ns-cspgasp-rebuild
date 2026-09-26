"""Drivers for the speaker's hardware: buttons, display, status LEDs, volume LED.

All GPIO access goes through gpiozero (lgpio backend on Raspberry Pi OS), which also
provides mock pins for tests and development on a PC. The original firmware used
RPi.GPIO, whose edge detection no longer works on current Raspberry Pi OS kernels.
"""
