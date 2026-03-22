#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/super-v"
DESKTOP_FILE="$HOME/.config/autostart/super-v.desktop"
APP_DESKTOP="/usr/share/applications/super-v.desktop"

echo "=== Super-V Installer ==="
echo ""

# --- Check for root (needed to install to /opt and apt packages) ---
if [[ $EUID -ne 0 ]]; then
    echo "This script needs root privileges to install system packages and copy files."
    echo "Please run:  sudo ./install.sh"
    exit 1
fi

REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(eval echo "~$REAL_USER")

# --- Install system dependencies ---
echo "[1/4] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 python3-xlib xdotool xclip > /dev/null
echo "       Done."

# --- Copy application files ---
echo "[2/4] Installing Super-V to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp cliphistory_v4.py "$INSTALL_DIR/super-v.py"
chmod +x "$INSTALL_DIR/super-v.py"
echo "       Done."

# --- Create .desktop file for app menu ---
echo "[3/4] Creating application menu entry..."
cat > "$APP_DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Super-V Clipboard History
Comment=Clipboard history manager for Linux (Win+V style)
Exec=/usr/bin/python3 $INSTALL_DIR/super-v.py
Icon=edit-paste
Terminal=false
Categories=Utility;
StartupNotify=false
EOF
echo "       Done."

# --- Set up autostart ---
echo "[4/4] Setting up autostart for user '$REAL_USER'..."
AUTOSTART_DIR="$REAL_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cp "$APP_DESKTOP" "$AUTOSTART_DIR/super-v.desktop"
chown "$REAL_USER":"$REAL_USER" "$AUTOSTART_DIR/super-v.desktop"
echo "       Done."

echo ""
echo "=== Installation complete! ==="
echo ""
echo "  Start now:    python3 $INSTALL_DIR/super-v.py"
echo "  Then press:   Super+V to open clipboard history"
echo ""
echo "  Super-V will start automatically on your next login."
echo "  To uninstall:  sudo ./uninstall.sh"
