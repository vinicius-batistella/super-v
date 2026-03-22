#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/super-v"
APP_DESKTOP="/usr/share/applications/super-v.desktop"

echo "=== Super-V Uninstaller ==="
echo ""

if [[ $EUID -ne 0 ]]; then
    echo "Please run:  sudo ./uninstall.sh"
    exit 1
fi

REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(eval echo "~$REAL_USER")
AUTOSTART_FILE="$REAL_HOME/.config/autostart/super-v.desktop"

# --- Kill running instance ---
echo "[1/4] Stopping running Super-V instances..."
pkill -f "super-v.py" 2>/dev/null && echo "       Stopped." || echo "       Not running."

# --- Remove installed files ---
echo "[2/4] Removing $INSTALL_DIR..."
if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    echo "       Done."
else
    echo "       Not found, skipping."
fi

# --- Remove desktop entry ---
echo "[3/4] Removing application menu entry..."
rm -f "$APP_DESKTOP"
echo "       Done."

# --- Remove autostart ---
echo "[4/4] Removing autostart entry..."
rm -f "$AUTOSTART_FILE"
echo "       Done."

echo ""
echo "=== Uninstall complete! ==="
echo ""
echo "  Note: Your clipboard history data is still in:"
echo "    $REAL_HOME/.local/share/super-v/"
echo ""
echo "  To delete it too:  rm -rf ~/.local/share/super-v/"
