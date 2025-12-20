#!/bin/bash
# Centerville Coordinator - Raspberry Pi Kiosk Setup
# Run this script on a fresh Raspberry Pi OS Lite or Desktop installation
# Usage: sudo ./setup-kiosk.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
KIOSK_USER="${SUDO_USER:-pi}"
KIOSK_URL="http://localhost:8000/?kiosk=1"

echo "=== Centerville Coordinator Kiosk Setup ==="
echo "Project directory: $PROJECT_DIR"
echo "Kiosk user: $KIOSK_USER"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./setup-kiosk.sh)"
    exit 1
fi

# Update system
echo ">>> Updating system packages..."
apt-get update
apt-get upgrade -y

# Install required packages
echo ">>> Installing required packages..."
apt-get install -y \
    python3-pip \
    python3-venv \
    chromium-browser \
    xserver-xorg \
    x11-xserver-utils \
    xinit \
    openbox \
    unclutter \
    libatlas-base-dev \
    bluez \
    bluetooth

# Create Python virtual environment and install coordinator
echo ">>> Setting up Python environment..."
cd "$PROJECT_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -e .
deactivate

# Create data directory
mkdir -p "$PROJECT_DIR/data"
chown -R "$KIOSK_USER:$KIOSK_USER" "$PROJECT_DIR"

# Install systemd service for the coordinator
echo ">>> Installing coordinator systemd service..."
cat > /etc/systemd/system/centerville-coordinator.service << EOF
[Unit]
Description=Centerville Air Quality Coordinator
After=network.target bluetooth.target

[Service]
Type=simple
User=$KIOSK_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$PROJECT_DIR/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable centerville-coordinator
systemctl start centerville-coordinator

# Configure auto-login to console
echo ">>> Configuring auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $KIOSK_USER --noclear %I \$TERM
EOF

# Create kiosk startup script
echo ">>> Creating kiosk startup script..."
cat > /home/$KIOSK_USER/start-kiosk.sh << 'KIOSKEOF'
#!/bin/bash
# Centerville Kiosk Startup Script

# Wait for coordinator to be ready
echo "Waiting for coordinator service..."
for i in {1..30}; do
    if curl -s http://localhost:8000/api/status > /dev/null 2>&1; then
        echo "Coordinator is ready!"
        break
    fi
    sleep 1
done

# Disable screen blanking and power management
xset s off
xset -dpms
xset s noblank

# Hide mouse cursor after 0.5 seconds of inactivity
unclutter -idle 0.5 -root &

# Start Chromium in kiosk mode
exec chromium-browser \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --no-first-run \
    --start-fullscreen \
    --window-position=0,0 \
    --window-size=480,320 \
    --check-for-update-interval=31536000 \
    --disable-translate \
    --disable-features=TranslateUI \
    --overscroll-history-navigation=0 \
    "http://localhost:8000/?kiosk=1"
KIOSKEOF

chmod +x /home/$KIOSK_USER/start-kiosk.sh
chown $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/start-kiosk.sh

# Create openbox autostart
mkdir -p /home/$KIOSK_USER/.config/openbox
cat > /home/$KIOSK_USER/.config/openbox/autostart << EOF
/home/$KIOSK_USER/start-kiosk.sh &
EOF
chown -R $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.config

# Create .bash_profile to auto-start X on login
cat > /home/$KIOSK_USER/.bash_profile << 'EOF'
# Auto-start X server on tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor
fi
EOF
chown $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.bash_profile

# Create .xinitrc
cat > /home/$KIOSK_USER/.xinitrc << EOF
exec openbox-session
EOF
chown $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.xinitrc

# Configure for 3.5" display (if using common SPI displays)
echo ">>> Configuring display settings..."
# Add display rotation if needed (uncomment and modify as needed)
# echo "display_rotate=0" >> /boot/config.txt

# Disable overscan for cleaner display
if ! grep -q "disable_overscan=1" /boot/config.txt; then
    echo "disable_overscan=1" >> /boot/config.txt
fi

# Enable Bluetooth
echo ">>> Enabling Bluetooth..."
systemctl enable bluetooth
systemctl start bluetooth

echo ""
echo "=== Setup Complete ==="
echo ""
echo "The Raspberry Pi is now configured as a kiosk."
echo ""
echo "Services installed:"
echo "  - centerville-coordinator (FastAPI server on port 8000)"
echo "  - Chromium kiosk browser (auto-starts on boot)"
echo ""
echo "To manage the coordinator service:"
echo "  sudo systemctl status centerville-coordinator"
echo "  sudo systemctl restart centerville-coordinator"
echo "  sudo journalctl -u centerville-coordinator -f"
echo ""
echo "Reboot to start kiosk mode:"
echo "  sudo reboot"
echo ""
