ManuCore display box app
========================

Files
  manucore_app.py   main app (window, layout, session + CSV logging)
  emg_sources.py    data sources: simulator and ESP32 Bluetooth
  emg_dsp.py        signal processing: mV conversion, RMS, FFT, median frequency, fatigue
  forearm_map.py    heat map widget
  config.py         all settings (gain, ADC range, channel names, BLE name, ...)
  assets/           arm drawing, electrode positions, Inter font

Run on a PC (Windows / Mac / Linux)
  1. Install Python 3.9+ from python.org (Windows: tick "Add Python to PATH")
  2. Open a terminal in this folder and run:
         pip install -r requirements.txt
  3. Start the app with simulated data:
         python manucore_app.py                 (8 s grip cycle)
         python manucore_app.py --demo hold     (sustained grip, shows fatigue)
  4. Tap/click a channel tile or an electrode on the arm for its detail view.
     Start session = record to sessions/session_YYYYMMDD_HHMMSS.csv

Run on the Raspberry Pi (Pi 4 + 7" 800x480 DSI screen)
  1. Install:
         sudo apt update
         sudo apt install -y python3-pyqt5 python3-pyqt5.qtsvg python3-numpy python3-pyqtgraph
         pip install bleak --break-system-packages
  2. Simulated data, full screen:   ./run_pi.sh
     (screens under 600 px tall, like 800x480, switch to the compact layout automatically;
      to preview it on a PC: python manucore_app.py --compact)
     Live ESP32 data, full screen:  ./run_pi.sh ble
     (Esc leaves full screen; close the window to quit)
  3. If the window is blank or touch is off, run with:
         QT_QPA_PLATFORM=xcb ./run_pi.sh

Before using real hardware, set in config.py:
  GAIN_TOTAL   total analog gain of the front end
  ADC_RANGE_V  input span set in the ADS8688A range register
