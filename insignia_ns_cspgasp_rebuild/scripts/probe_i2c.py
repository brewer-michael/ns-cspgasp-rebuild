import sys
try:
    from smbus2 import SMBus
except ImportError:
    print("Error: smbus2 not installed. Run 'pip install smbus2'")
    sys.exit(1)

def scan_i2c():
    print("Scanning I2C bus 1...")
    try:
        with SMBus(1) as bus:
            devices = []
            for address in range(0x03, 0x78):
                try:
                    bus.write_quick(address)
                    devices.append(address)
                except OSError:
                    pass

            if devices:
                print(f"Found I2C devices at addresses: {[hex(addr) for addr in devices]}")
                print("If you see an address, the Top Board is likely I2C based!")
            else:
                print("No I2C devices found. Check wiring or try 'i2cdetect -y 1'.")

    except FileNotFoundError:
        print("Error: I2C bus not found. Is I2C enabled on your Raspberry Pi? (raspi-config)")
    except PermissionError:
        print("Error: Permission denied. Try running with sudo.")

if __name__ == "__main__":
    scan_i2c()
