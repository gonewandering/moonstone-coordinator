#!/bin/bash
# Centerville Coordinator - WiFi Manager Setup
# Installs the wifi-manager script and systemd service
# Usage: sudo ./setup-wifi-manager.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="/opt/centerville"
DB_PATH="$PROJECT_DIR/data/centerville.db"

echo "=== WiFi Manager Setup ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./setup-wifi-manager.sh)"
    exit 1
fi

# Install required packages
echo ">>> Installing dependencies..."
apt-get update
apt-get install -y network-manager sqlite3

# Create install directory
mkdir -p "$INSTALL_DIR"

# Create the wifi-manager script
echo ">>> Creating wifi-manager script..."
cat > "$INSTALL_DIR/wifi-manager.sh" << 'SCRIPT'
#!/bin/bash
# Centerville WiFi Manager
# Manages WiFi connections and AP fallback

DB_PATH="${CENTERVILLE_DB:-/opt/centerville/data/centerville.db}"
AP_SSID="${CENTERVILLE_AP_SSID:-Centerville-Setup}"
AP_PASSWORD="${CENTERVILLE_AP_PASSWORD:-centerville123}"
WIFI_INTERFACE="${WIFI_INTERFACE:-wlan0}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

get_networks() {
    if [ -f "$DB_PATH" ]; then
        sqlite3 "$DB_PATH" "SELECT ssid, password, priority FROM wifi_networks ORDER BY priority DESC;"
    fi
}

try_connect() {
    local ssid="$1"
    local password="$2"

    log "Attempting to connect to '$ssid'..."

    # Check if network is in range
    if ! nmcli -t -f SSID device wifi list | grep -q "^${ssid}$"; then
        log "Network '$ssid' not in range"
        return 1
    fi

    # Delete existing connection if present
    nmcli connection delete "$ssid" 2>/dev/null || true

    # Try to connect
    if [ -n "$password" ]; then
        if nmcli device wifi connect "$ssid" password "$password" ifname "$WIFI_INTERFACE" 2>/dev/null; then
            log "Connected to '$ssid'"
            return 0
        fi
    else
        if nmcli device wifi connect "$ssid" ifname "$WIFI_INTERFACE" 2>/dev/null; then
            log "Connected to '$ssid'"
            return 0
        fi
    fi

    log "Failed to connect to '$ssid'"
    return 1
}

start_ap() {
    log "Starting Access Point mode..."

    # Stop any existing AP
    nmcli connection delete "$AP_SSID" 2>/dev/null || true

    # Create hotspot
    nmcli device wifi hotspot ifname "$WIFI_INTERFACE" ssid "$AP_SSID" password "$AP_PASSWORD"

    log "Access Point started: SSID='$AP_SSID', Password='$AP_PASSWORD'"
}

stop_ap() {
    log "Stopping Access Point mode..."
    nmcli connection delete "$AP_SSID" 2>/dev/null || true
}

check_connection() {
    # Check if we have an active WiFi connection (not AP)
    local active=$(nmcli -t -f TYPE,STATE connection show --active | grep "wifi:activated" | head -1)
    if [ -n "$active" ]; then
        # Make sure it's not our AP
        local ssid=$(nmcli -t -f NAME,TYPE connection show --active | grep ":wifi$" | cut -d: -f1)
        if [ "$ssid" != "$AP_SSID" ]; then
            return 0
        fi
    fi
    return 1
}

do_connect() {
    log "Starting WiFi connection process..."

    # Scan for networks
    nmcli device wifi rescan 2>/dev/null || true
    sleep 2

    # Get configured networks from database
    local networks=$(get_networks)

    if [ -z "$networks" ]; then
        log "No networks configured in database"
        start_ap
        return
    fi

    # Try each network in priority order
    while IFS='|' read -r ssid password priority; do
        if [ -n "$ssid" ]; then
            if try_connect "$ssid" "$password"; then
                return 0
            fi
        fi
    done <<< "$networks"

    # All networks failed, start AP
    log "All configured networks failed, starting AP mode"
    start_ap
}

status() {
    echo "=== WiFi Status ==="
    nmcli device status
    echo ""
    echo "=== Active Connections ==="
    nmcli connection show --active
    echo ""
    echo "=== Available Networks ==="
    nmcli device wifi list
}

case "${1:-connect}" in
    connect)
        do_connect
        ;;
    ap)
        start_ap
        ;;
    stop-ap)
        stop_ap
        ;;
    status)
        status
        ;;
    check)
        if check_connection; then
            echo "Connected"
            exit 0
        else
            echo "Not connected"
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 {connect|ap|stop-ap|status|check}"
        exit 1
        ;;
esac
SCRIPT

chmod +x "$INSTALL_DIR/wifi-manager.sh"

# Create data directory symlink
ln -sf "$PROJECT_DIR/data" "$INSTALL_DIR/data" 2>/dev/null || true

# Create systemd service for boot-time WiFi management
echo ">>> Creating systemd service..."
cat > /etc/systemd/system/centerville-wifi.service << EOF
[Unit]
Description=Centerville WiFi Manager
After=network.target NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
Environment=CENTERVILLE_DB=$INSTALL_DIR/data/centerville.db
ExecStart=$INSTALL_DIR/wifi-manager.sh connect
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Create timer for periodic connection checks
cat > /etc/systemd/system/centerville-wifi-check.service << EOF
[Unit]
Description=Centerville WiFi Connection Check
After=centerville-wifi.service

[Service]
Type=oneshot
Environment=CENTERVILLE_DB=$INSTALL_DIR/data/centerville.db
ExecStart=/bin/bash -c 'if ! $INSTALL_DIR/wifi-manager.sh check; then $INSTALL_DIR/wifi-manager.sh connect; fi'
EOF

cat > /etc/systemd/system/centerville-wifi-check.timer << EOF
[Unit]
Description=Periodic WiFi connection check

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

# Enable services
systemctl daemon-reload
systemctl enable centerville-wifi.service
systemctl enable centerville-wifi-check.timer

echo ""
echo "=== WiFi Manager Setup Complete ==="
echo ""
echo "Installed: $INSTALL_DIR/wifi-manager.sh"
echo "Database: $INSTALL_DIR/data/centerville.db"
echo ""
echo "Commands:"
echo "  $INSTALL_DIR/wifi-manager.sh connect  - Try configured networks, fallback to AP"
echo "  $INSTALL_DIR/wifi-manager.sh ap       - Start Access Point mode"
echo "  $INSTALL_DIR/wifi-manager.sh status   - Show WiFi status"
echo ""
echo "The service will run at boot and check connection every 5 minutes."
echo "Configure networks via the web UI at /api/device/wifi/networks"
echo ""
