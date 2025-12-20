#!/bin/bash
# Centerville Coordinator - 3.5" LCD Display Setup
# Run this BEFORE setup-kiosk.sh on Raspberry Pi OS Lite
# Usage: sudo ./setup-lcd.sh

set -e

echo "=== 3.5\" LCD Display Setup ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./setup-lcd.sh)"
    exit 1
fi

# Detect boot config location
BOOT_CONFIG="/boot/config.txt"
[ -f "/boot/firmware/config.txt" ] && BOOT_CONFIG="/boot/firmware/config.txt"

echo "Boot config: $BOOT_CONFIG"

# Install X server and dependencies
echo ">>> Installing X server and browser..."
apt-get update
apt-get install -y \
    xserver-xorg \
    xinit \
    x11-xserver-utils \
    chromium \
    unclutter \
    openbox

# Prompt for display type
echo ""
echo "Select your 3.5\" display type:"
echo "  1) Waveshare 3.5\" (A) - most common"
echo "  2) Waveshare 3.5\" (B)"
echo "  3) Waveshare 3.5\" (C)"
echo "  4) PiScreen / Adafruit-style"
echo "  5) Goodtft 3.5\""
echo "  6) Generic SPI (manual config)"
echo "  7) Skip - I'll configure manually"
echo ""
read -p "Enter choice [1-7]: " DISPLAY_CHOICE

case $DISPLAY_CHOICE in
    1)
        OVERLAY="dtoverlay=waveshare35a"
        ;;
    2)
        OVERLAY="dtoverlay=waveshare35b"
        ;;
    3)
        OVERLAY="dtoverlay=waveshare35c"
        ;;
    4)
        OVERLAY="dtoverlay=piscreen,speed=16000000,rotate=90"
        ;;
    5)
        OVERLAY="dtoverlay=tft35a:rotate=90"
        ;;
    6)
        echo ""
        echo "For generic SPI displays, add to $BOOT_CONFIG:"
        echo "  dtoverlay=<your-overlay>"
        echo "  hdmi_force_hotplug=1"
        echo "  hdmi_cvt=480 320 60 6 0 0 0"
        echo "  hdmi_group=2"
        echo "  hdmi_mode=87"
        echo ""
        OVERLAY=""
        ;;
    7)
        echo "Skipping display configuration."
        OVERLAY=""
        ;;
    *)
        echo "Invalid choice, defaulting to Waveshare 3.5\" (A)"
        OVERLAY="dtoverlay=waveshare35a"
        ;;
esac

if [ -n "$OVERLAY" ]; then
    echo ">>> Configuring display overlay..."

    # Backup config
    cp "$BOOT_CONFIG" "${BOOT_CONFIG}.backup"

    # Remove any existing waveshare/piscreen overlays
    sed -i '/dtoverlay=waveshare/d' "$BOOT_CONFIG"
    sed -i '/dtoverlay=piscreen/d' "$BOOT_CONFIG"
    sed -i '/dtoverlay=tft35/d' "$BOOT_CONFIG"

    # Add the overlay
    echo "" >> "$BOOT_CONFIG"
    echo "# 3.5\" LCD Display" >> "$BOOT_CONFIG"
    echo "$OVERLAY" >> "$BOOT_CONFIG"

    # Add framebuffer settings for SPI displays
    if ! grep -q "fbcon=map:10" "$BOOT_CONFIG"; then
        echo "fbcon=map:10" >> "$BOOT_CONFIG"
    fi

    echo "Added: $OVERLAY"
fi

# Disable screen blanking in boot config
if ! grep -q "consoleblank=0" "$BOOT_CONFIG"; then
    echo "consoleblank=0" >> "$BOOT_CONFIG"
fi

echo ""
echo "=== LCD Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Reboot to test the display: sudo reboot"
echo "  2. After display works, run: sudo ./scripts/setup-kiosk.sh"
echo ""
echo "If the display doesn't work after reboot:"
echo "  - Try a different overlay option"
echo "  - Check your display model number"
echo "  - The backup config is at: ${BOOT_CONFIG}.backup"
echo ""
