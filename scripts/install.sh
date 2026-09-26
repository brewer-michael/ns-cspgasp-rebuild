#!/usr/bin/env bash
# Install Open Speaker on Raspberry Pi OS (Bookworm or newer; Lite is enough).
#
#   git clone -b v2 https://github.com/brewer-michael/ns-cspgasp-rebuild.git
#   sudo ns-cspgasp-rebuild/scripts/install.sh
#
# Run it again after a `git pull` to update: your configuration is left alone.
#
# Options:
#   --no-boot-config   leave config.txt alone (sound card, I2C and SPI overlays)
#   --no-asound        leave /etc/asound.conf alone
#   --no-wifi-tweak    leave Wi-Fi power saving on
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
prefix=/opt/open-speaker
etc=/etc/open-speaker
user=open-speaker
boot_config=true
asound=true
wifi=true
reboot_needed=false

for arg in "$@"; do
    case "$arg" in
        --no-boot-config) boot_config=false ;;
        --no-asound) asound=false ;;
        --no-wifi-tweak) wifi=false ;;
        -h | --help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this with sudo." >&2
    exit 1
fi

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

step "Installing system packages"
apt-get update
# numpy, gpiozero/lgpio, spidev, smbus2 and Pillow come from apt: no compiling on a Pi Zero
apt-get install -y --no-install-recommends \
    python3-venv python3-pip \
    alsa-utils libasound2-plugins mpg123 \
    python3-numpy python3-gpiozero python3-lgpio python3-spidev python3-smbus2 python3-pil \
    fonts-dejavu-core i2c-tools

step "Creating the '$user' service user"
if ! id "$user" >/dev/null 2>&1; then
    useradd --system --home-dir /var/lib/open-speaker --no-create-home \
        --shell /usr/sbin/nologin "$user"
fi
for group in audio gpio spi i2c; do
    if getent group "$group" >/dev/null; then
        usermod -a -G "$group" "$user"
    fi
done

step "Installing Open Speaker into $prefix"
python3 -m venv --system-site-packages "$prefix/venv"
"$prefix/venv/bin/pip" install --quiet --upgrade pip
"$prefix/venv/bin/pip" install --upgrade "$repo/firmware[pi]"
ln -sf "$prefix/venv/bin/open-speaker" /usr/local/bin/open-speaker

step "Configuration in $etc"
install -d -m 0755 "$etc"
new_config=false
if [ ! -f "$etc/config.yaml" ]; then
    "$prefix/venv/bin/open-speaker" example-config > "$etc/config.yaml"
    new_config=true
    echo "Wrote $etc/config.yaml"
else
    echo "Keeping your $etc/config.yaml"
fi
if [ ! -f "$etc/secrets.env" ]; then
    install -m 0600 /dev/null "$etc/secrets.env"
    cat > "$etc/secrets.env" <<'EOF'
# Secrets used as ${NAME} in config.yaml. Only root can read this file; the
# service gets these as environment variables.
HA_TOKEN=
API_TOKEN=
EOF
    echo "Wrote $etc/secrets.env"
fi

if $asound; then
    step "Sound devices (/etc/asound.conf)"
    if [ -f /etc/asound.conf ] && ! grep -q "Open Speaker" /etc/asound.conf; then
        cp /etc/asound.conf /etc/asound.conf.before-open-speaker
        echo "Saved the previous file as /etc/asound.conf.before-open-speaker"
    fi
    install -m 0644 "$repo/config/asound.conf" /etc/asound.conf
fi

if $boot_config; then
    step "Boot configuration (sound card, I2C, SPI)"
    cfg=/boot/firmware/config.txt
    [ -f "$cfg" ] || cfg=/boot/config.txt
    if [ -f "$cfg" ]; then
        [ -f "$cfg.before-open-speaker" ] || cp "$cfg" "$cfg.before-open-speaker"
        before="$(md5sum < "$cfg")"
        # the onboard audio would take the first sound card
        sed -i 's/^dtparam=audio=on/#dtparam=audio=on  # turned off by Open Speaker/' "$cfg"
        sed -i '/^# >>> open-speaker/,/^# <<< open-speaker/d' "$cfg"
        cat >> "$cfg" <<'EOF'
# >>> open-speaker (managed by scripts/install.sh; see config/config.txt.example)
[all]
dtparam=audio=off
dtoverlay=googlevoicehat-soundcard
dtparam=i2c_arm=on
dtparam=i2c_arm_baudrate=400000
dtparam=spi=on
core_freq=250
# <<< open-speaker
EOF
        if [ "$before" != "$(md5sum < "$cfg")" ]; then
            reboot_needed=true
            echo "Updated $cfg"
        else
            echo "$cfg is already set up"
        fi
    else
        echo "No config.txt found; add the lines from config/config.txt.example yourself." >&2
    fi
fi

if $wifi && [ -d /etc/NetworkManager/conf.d ]; then
    step "Turning off Wi-Fi power saving"
    cat > /etc/NetworkManager/conf.d/99-open-speaker.conf <<'EOF'
# Wi-Fi power saving adds delay to every voice request. 2 = off.
[connection]
wifi.powersave = 2
EOF
fi

step "Service"
install -m 0644 "$repo/config/systemd/open-speaker.service" /etc/systemd/system/open-speaker.service
systemctl daemon-reload
systemctl enable open-speaker.service >/dev/null
if systemctl is-active --quiet open-speaker.service; then
    systemctl restart open-speaker.service
    echo "Restarted open-speaker"
fi

step "Done"
if $new_config; then
    cat <<EOF
Next:
  1. Edit $etc/config.yaml: your Home Assistant URL (or your own speech and
     language model servers), the wake word and the display.
  2. Put your Home Assistant long-lived access token in $etc/secrets.env (HA_TOKEN=...).
  3. Check the setup:   sudo open-speaker doctor
  4. Start it:          sudo systemctl start open-speaker
     Logs:              journalctl -u open-speaker -f
EOF
fi
if $reboot_needed; then
    echo
    echo "Reboot to load the sound card, I2C and SPI:  sudo reboot"
fi
