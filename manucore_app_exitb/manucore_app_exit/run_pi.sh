#!/bin/bash
# ManuCore launcher for the Raspberry Pi
#   ./run_pi.sh         simulated data (no ESP32 needed)
#   ./run_pi.sh ble     live data from the ESP32
cd "$(dirname "$0")"
export PYQTGRAPH_QT_LIB=PyQt5
# When started over SSH, show the app on the Pi's own screen
if [ -z "$WAYLAND_DISPLAY" ] && [ -z "$DISPLAY" ]; then
  export XDG_RUNTIME_DIR=/run/user/$(id -u)
  export WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR" 2>/dev/null | grep -m1 '^wayland-[0-9]*$')
  export QT_QPA_PLATFORM=wayland
fi
SRC=${1:-sim}
python3 manucore_app.py --source "$SRC" --fullscreen
