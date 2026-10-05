#!/usr/bin/env bash
# Removes swipepen. Leaves the dnf packages (python3-evdev, python3-tkinter) alone.
set -euo pipefail
DEST="${SWIPEPEN_HOME:-$HOME/.local/share/swipepen}"

rm -rf "$DEST"
rm -f "$HOME/.local/bin/swipepen" "$HOME/.local/share/applications/swipepen.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

if [ "${SKIP_SYSTEM:-0}" != 1 ]; then
  sudo rm -f /etc/udev/rules.d/60-swipepen-uinput.rules /etc/udev/rules.d/61-swipepen-tablet.rules
  sudo udevadm control --reload-rules || true
fi
echo "swipepen removed."
echo "(Your own words list in ~/.config/swipepen was left in place.)"
