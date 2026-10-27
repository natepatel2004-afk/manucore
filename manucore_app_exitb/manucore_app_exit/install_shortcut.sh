#!/bin/bash
# Puts a ManuCore icon on the Pi desktop and in the app menu.
#   bash install_shortcut.sh
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$APP_DIR/run_pi.sh"
ENTRY="[Desktop Entry]
Type=Application
Name=ManuCore
Comment=EMG grip monitor display
Exec=$APP_DIR/run_pi.sh
Path=$APP_DIR
Icon=$APP_DIR/assets/icon.png
Terminal=false
Categories=Utility;"
mkdir -p "$HOME/Desktop" "$HOME/.local/share/applications"
echo "$ENTRY" > "$HOME/Desktop/manucore.desktop"
echo "$ENTRY" > "$HOME/.local/share/applications/manucore.desktop"
chmod +x "$HOME/Desktop/manucore.desktop" "$HOME/.local/share/applications/manucore.desktop"
# Let the file manager launch it without asking every time
mkdir -p "$HOME/.config/libfm"
CONF="$HOME/.config/libfm/libfm.conf"
if [ -f "$CONF" ] && grep -q '^quick_exec=' "$CONF"; then
  sed -i 's/^quick_exec=.*/quick_exec=1/' "$CONF"
elif [ -f "$CONF" ] && grep -q '^\[config\]' "$CONF"; then
  sed -i '/^\[config\]/a quick_exec=1' "$CONF"
else
  printf '[config]\nquick_exec=1\n' >> "$CONF"
fi
echo "Done: ManuCore icon added to the desktop and the app menu."
