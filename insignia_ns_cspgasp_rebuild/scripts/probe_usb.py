import usb.core
import usb.util
import sys

def main():
    print("Scanning for USB devices...")
    # Find all devices
    devs = usb.core.find(find_all=True)

    found_candidates = False

    if devs is None:
        print("No USB devices found.")
        return

    for dev in devs:
        try:
            manufacturer = usb.util.get_string(dev, dev.iManufacturer)
            product = usb.util.get_string(dev, dev.iProduct)
            print(f"Device: ID {dev.idVendor:04x}:{dev.idProduct:04x} - {manufacturer} {product}")

            # Heuristic detection for Google Home Top Board
            # Often appears as STM32, Cypress, or generic HID
            # Note: The specific VID/PID for the H0A top board is not publicly documented widely,
            # so we look for anything that isn't a standard root hub.

            if dev.idVendor == 0x18d1: # Google VID
                 print("  -> POSSIBLE MATCH: Google Device found!")
                 found_candidates = True
                 print_descriptors(dev)

        except usb.core.USBError as e:
            print(f"Device: ID {dev.idVendor:04x}:{dev.idProduct:04x} - (Access Denied or Error: {e})")

    if not found_candidates:
        print("\nIf you have connected the Top Board, it might not be enumerating or requires sudo access.")

def print_descriptors(dev):
    print("  Configuration:")
    for cfg in dev:
        print(f"    Configuration {cfg.bConfigurationValue}")
        for intf in cfg:
            print(f"      Interface {intf.bInterfaceNumber}, Alt {intf.bAlternateSetting}")
            print(f"      Class: {intf.bInterfaceClass}, Subclass: {intf.bInterfaceSubClass}")
            for ep in intf:
                print(f"        Endpoint {ep.bEndpointAddress:02x}")

if __name__ == "__main__":
    main()
