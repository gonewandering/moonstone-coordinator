#!/bin/bash
# Centerville Coordinator - Splash Screen Setup
# Displays splash.png on the LCD during boot
# Usage: sudo ./setup-splash.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SPLASH_SOURCE="$PROJECT_DIR/splash.png"

echo "=== Splash Screen Setup ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./setup-splash.sh)"
    exit 1
fi

# Check if splash.png exists
if [ ! -f "$SPLASH_SOURCE" ]; then
    echo "Error: splash.png not found at $SPLASH_SOURCE"
    echo "Please add a 480x320 PNG image named 'splash.png' to the coordinator directory."
    exit 1
fi

# Install fbi if not present
if ! command -v fbi &> /dev/null; then
    echo ">>> Installing fbi..."
    apt-get update
    apt-get install -y fbi
fi

# Create splash directory and copy image
echo ">>> Setting up splash image..."
mkdir -p /opt/splash
cp "$SPLASH_SOURCE" /opt/splash/boot.png

# Determine framebuffer device (use fb1 for SPI LCD, fb0 as fallback)
FB_DEVICE="/dev/fb1"
if [ ! -e "$FB_DEVICE" ]; then
    FB_DEVICE="/dev/fb0"
fi
echo "Using framebuffer: $FB_DEVICE"

# Create systemd service
echo ">>> Creating splash service..."
cat > /etc/systemd/system/splash.service << EOF
[Unit]
Description=Boot Splash Screen
DefaultDependencies=no
After=local-fs.target
Before=basic.target

[Service]
Type=oneshot
ExecStart=/usr/bin/fbi -d $FB_DEVICE -T 1 -noverbose -a /opt/splash/boot.png
StandardInput=tty
StandardOutput=tty

[Install]
WantedBy=sysinit.target
EOF

# Enable the service
systemctl daemon-reload
systemctl enable splash.service

echo ""
echo "=== Splash Setup Complete ==="
echo ""
echo "Splash image installed: /opt/splash/boot.png"
echo "Framebuffer device: $FB_DEVICE"
echo ""
echo "The splash screen will display on next boot."
echo "To test now: sudo fbi -d $FB_DEVICE -T 1 -noverbose -a /opt/splash/boot.png"
echo ""
