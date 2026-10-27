#!/bin/bash
# ManuCore launcher for the Raspberry Pi
#   ./run_pi.sh         simulated data (no ESP32 needed)
#   ./run_pi.sh ble     live data from the ESP32
cd "$(dirname "$0")"
SRC=${1:-sim}
python3 manucore_app.py --source "$SRC" --fullscreen
