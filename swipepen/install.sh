#!/usr/bin/env bash
# swipepen installer for Fedora (KDE or GNOME).
#
#   ./install.sh
#
# Asks for your password once (system packages + one permission rule).
# No log-out needed in the normal case. Undo everything with ./uninstall.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${SWIPEPEN_HOME:-$HOME/.local/share/swipepen}"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [ "${SKIP_SYSTEM:-0}" != 1 ]; then
  command -v dnf >/dev/null || { echo "This installer is for Fedora (it needs dnf)."; exit 1; }

  say "Installing system packages"
  sudo dnf install -y python3-evdev python3-tkinter wl-clipboard xclip
  # offline dictionary + thesaurus for the pen's Dictionary tool (optional: it falls back to the internet)
  sudo dnf install -y wordnet || echo "(could not install wordnet: the dictionary will use the internet instead)"

  say "Allowing your user to create a virtual keyboard (needed to type for you)"
  sudo tee /etc/udev/rules.d/60-swipepen-uinput.rules >/dev/null <<'EOF'
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF
  echo uinput | sudo tee /etc/modules-load.d/uinput.conf >/dev/null

  say "Allowing your user to read the pen tablet"
  sudo tee /etc/udev/rules.d/61-swipepen-tablet.rules >/dev/null <<'EOF'
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_TABLET}=="1", TAG+="uaccess"
EOF
  sudo modprobe uinput
  sudo udevadm control --reload-rules
  sudo udevadm trigger --name-match=uinput || true
  sudo udevadm trigger --subsystem-match=input || true
  sleep 2
fi

say "Installing swipepen"
mkdir -p "$DEST" "$BIN" "$APPS"
rm -rf "$DEST/app"
mkdir -p "$DEST/app"
cp -r "$HERE/swipepen" "$DEST/app/"
find "$DEST/app" -name __pycache__ -prune -exec rm -rf {} +
echo "$HERE" > "$DEST/source"      # remembered so `swipepen update` can refresh this folder too

# Private virtualenv that can still see the dnf-installed evdev and tkinter.
rm -rf "$DEST/venv"
python3 -m venv --system-site-packages "$DEST/venv"
say "Downloading the word-frequency list (makes suggestions much better)"
if "$DEST/venv/bin/pip" install --quiet wordfreq; then
  FREQ="yes"
else
  FREQ="no"
  echo "Could not install wordfreq (no internet?). swipepen will still work, with a weaker word list."
  echo "Retry later with:  $DEST/venv/bin/pip install wordfreq"
fi

# `swipepen` command
cat > "$BIN/swipepen" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$DEST/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$DEST/venv/bin/python" -m swipepen "\$@"
EOF
chmod +x "$BIN/swipepen"

# Entry in the application menu (KDE launcher / GNOME overview)
cat > "$APPS/swipepen.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Swipepen
GenericName=Pen swipe typing
Comment=Swipe-type with your pen tablet
Exec=$BIN/swipepen run
Icon=input-tablet
Terminal=false
Categories=Utility;Accessibility;
Actions=Settings;Toggle;Update;Doctor;

[Desktop Action Settings]
Name=Settings
Exec=$BIN/swipepen settings

[Desktop Action Toggle]
Name=Pause / resume pen
Exec=$BIN/swipepen toggle

[Desktop Action Update]
Name=Update from Downloads
Exec=$BIN/swipepen update --window

[Desktop Action Doctor]
Name=Check setup
Exec=$BIN/swipepen doctor --window
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true

NEED_RELOGIN=0
if [ "${SKIP_SYSTEM:-0}" != 1 ]; then
  # Did the permission rules take effect? If the tablet or /dev/uinput is still
  # off-limits, fall back to the classic method: the 'input' group (needs one re-login).
  rc=0
  "$BIN/swipepen" doctor --probe-access || rc=$?
  if [ ! -w /dev/uinput ] || [ "$rc" = 3 ]; then
    sudo usermod -aG input "$USER"
    NEED_RELOGIN=1
  fi
fi

say "Checking your setup"
"$BIN/swipepen" doctor || echo "(Something above needs fixing - see the [FAIL] lines.)"
if [ "$NEED_RELOGIN" = 1 ]; then
  echo "(Permission [FAIL] lines are expected right now - they clear after you log out and back in.)"
fi

say "Done."
echo "Word frequencies: $FREQ"
if [ "$NEED_RELOGIN" = 1 ]; then
  echo
  echo "One last thing: log out and back in once (this lets swipepen type for you)."
fi
echo
echo "To use it:"
echo "  1. Open \"Swipepen\" from your application menu (or run:  swipepen)"
echo "  2. Click your Google Docs tab once"
echo "  3. Swipe words with the pen"
echo
echo "Try it first without typing anything:  swipepen run --dry-run --no-pen --mouse"
