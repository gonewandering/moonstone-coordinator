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

# Detect if running Desktop or Lite
IS_DESKTOP=false
if systemctl is-active --quiet lightdm || systemctl is-enabled --quiet lightdm 2>/dev/null; then
    IS_DESKTOP=true
    echo "Detected: Raspberry Pi OS Desktop"
else
    echo "Detected: Raspberry Pi OS Lite"
fi

# Update system
echo ">>> Updating system packages..."
apt-get update
apt-get upgrade -y

# Install required packages
echo ">>> Installing required packages..."
if [ "$IS_DESKTOP" = true ]; then
    apt-get install -y \
        python3-pip \
        python3-venv \
        unclutter \
        bluez \
        bluetooth
else
    apt-get install -y \
        python3-pip \
        python3-venv \
        chromium \
        xserver-xorg \
        x11-xserver-utils \
        xinit \
        openbox \
        unclutter \
        bluez \
        bluetooth
fi

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

if [ "$IS_DESKTOP" = true ]; then
    # ============================================
    # DESKTOP VERSION - Use LXDE autostart
    # ============================================
    echo ">>> Configuring Desktop kiosk mode..."

    # Create kiosk startup script
    cat > /home/$KIOSK_USER/start-kiosk.sh << 'KIOSKEOF'
#!/bin/bash
# Centerville Kiosk Startup Script (Desktop version)

# Wait for coordinator to be ready
echo "Waiting for coordinator service..."
for i in {1..30}; do
    if curl -s http://localhost:8000/api/status > /dev/null 2>&1; then
        echo "Coordinator is ready!"
        break
    fi
    sleep 1
done

# Disable screen blanking
xset s off
xset -dpms
xset s noblank

# Hide mouse cursor
unclutter -idle 0.5 -root &

# Start Chromium in kiosk mode
chromium \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --no-first-run \
    --start-fullscreen \
    --check-for-update-interval=31536000 \
    --disable-translate \
    --disable-features=TranslateUI \
    --overscroll-history-navigation=0 \
    "http://localhost:8000/kiosk"
KIOSKEOF

    chmod +x /home/$KIOSK_USER/start-kiosk.sh
    chown $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/start-kiosk.sh

    # Create LXDE autostart directory
    mkdir -p /home/$KIOSK_USER/.config/lxsession/LXDE-pi
    chown -R $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.config

    # Create autostart file - NO panel or desktop, just the kiosk
    cat > /home/$KIOSK_USER/.config/lxsession/LXDE-pi/autostart << EOF
@xset s off
@xset -dpms
@xset s noblank
@unclutter -idle 0.5 -root
@/home/$KIOSK_USER/start-kiosk.sh
EOF
    chown $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.config/lxsession/LXDE-pi/autostart

    # Configure auto-login for desktop
    echo ">>> Configuring desktop auto-login..."
    mkdir -p /etc/lightdm/lightdm.conf.d
    cat > /etc/lightdm/lightdm.conf.d/autologin.conf << EOF
[Seat:*]
autologin-user=$KIOSK_USER
autologin-session=LXDE-pi
EOF

else
    # ============================================
    # LITE VERSION - Use console + openbox
    # ============================================
    echo ">>> Configuring Lite kiosk mode..."

    # Configure auto-login to console
    mkdir -p /etc/systemd/system/getty@tty1.service.d
    cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $KIOSK_USER --noclear %I \$TERM
EOF

    # Create kiosk startup script
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
exec chromium \
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
    "http://localhost:8000/kiosk"
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
fi

# Configure for 3.5" display (if using common SPI displays)
echo ">>> Configuring display settings..."

# Disable overscan for cleaner display
BOOT_CONFIG="/boot/config.txt"
[ -f "/boot/firmware/config.txt" ] && BOOT_CONFIG="/boot/firmware/config.txt"

if ! grep -q "disable_overscan=1" "$BOOT_CONFIG"; then
    echo "disable_overscan=1" >> "$BOOT_CONFIG"
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
if [ "$IS_DESKTOP" = true ]; then
    echo "Mode: Desktop (LXDE)"
else
    echo "Mode: Lite (Openbox)"
fi
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
