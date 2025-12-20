# Raspberry Pi Kiosk Setup

Scripts to configure a Raspberry Pi as a dedicated kiosk displaying the Centerville Air Quality dashboard on a 3.5" 480x320 display.

## Prerequisites

- Raspberry Pi (tested on Pi 3/4/Zero 2W)
- Raspberry Pi OS Lite or Desktop (Bookworm or newer)
- 3.5" SPI/HDMI display (480x320)
- Network connection (Ethernet or WiFi)

## Quick Setup

1. Flash Raspberry Pi OS to your SD card
2. Enable SSH and configure WiFi (if needed) using Raspberry Pi Imager
3. Boot the Pi and SSH into it
4. Clone the repository:
   ```bash
   git clone <your-repo-url> ~/centerville-coordinator
   cd ~/centerville-coordinator
   ```
5. Run the setup script:
   ```bash
   sudo ./scripts/setup-kiosk.sh
   ```
6. Reboot:
   ```bash
   sudo reboot
   ```

## What the Setup Script Does

1. **Installs dependencies**: Python, Chromium, X server, Openbox
2. **Creates Python venv**: Installs the coordinator in a virtual environment
3. **Installs systemd service**: `centerville-coordinator` runs on boot
4. **Configures auto-login**: Boots directly to the kiosk user
5. **Sets up kiosk browser**: Chromium in fullscreen mode
6. **Disables screen blanking**: Display stays on permanently
7. **Hides mouse cursor**: Cursor hides after 0.5s inactivity

## Managing the Coordinator

```bash
# Check status
sudo systemctl status centerville-coordinator

# View logs
sudo journalctl -u centerville-coordinator -f

# Restart service
sudo systemctl restart centerville-coordinator

# Stop service
sudo systemctl stop centerville-coordinator
```

## Display Configuration

### Common 3.5" SPI Displays (Waveshare, etc.)

If using an SPI display, you may need to add drivers. For example:

```bash
# For Waveshare 3.5" displays
git clone https://github.com/waveshare/LCD-show.git
cd LCD-show
sudo ./LCD35-show
```

### HDMI Displays

For small HDMI displays, you may need to adjust `/boot/config.txt`:

```ini
# For 480x320 HDMI display
hdmi_force_hotplug=1
hdmi_group=2
hdmi_mode=87
hdmi_cvt=480 320 60 1 0 0 0
```

### Display Rotation

To rotate the display, add to `/boot/config.txt`:

```ini
display_rotate=0  # Normal
display_rotate=1  # 90 degrees
display_rotate=2  # 180 degrees
display_rotate=3  # 270 degrees
```

## Kiosk Mode URL

The kiosk automatically loads: `http://localhost:8000/?kiosk=1`

The `kiosk=1` parameter triggers a compact layout optimized for small screens:
- Hides the chart section
- Compact sensor cards in a 4-column grid
- Smaller fonts and padding
- Hides settings buttons

## Exiting Kiosk Mode (for maintenance)

1. Connect via SSH
2. Stop the display manager or kill Chromium:
   ```bash
   pkill chromium
   ```
3. To return to kiosk mode, reboot or:
   ```bash
   sudo systemctl restart getty@tty1
   ```

## Troubleshooting

### Black screen after boot
- Check that the coordinator is running: `sudo systemctl status centerville-coordinator`
- Check X server logs: `cat ~/.local/share/xorg/Xorg.0.log`

### Display not working
- Verify display drivers are installed
- Check `/boot/config.txt` for correct display settings
- Try connecting via HDMI first to verify the setup

### Browser shows error
- Coordinator may not be ready yet (wait 30 seconds)
- Check coordinator logs: `sudo journalctl -u centerville-coordinator`
