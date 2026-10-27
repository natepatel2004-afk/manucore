"""
ManuCore display box - settings
Change values here; nothing else in the app needs editing.
"""
import os

# ---- data source --------------------------------------------------------
# "sim" = built-in EMG simulator (use on a PC before hardware exists)
# "ble" = live data from the ESP32 over Bluetooth Low Energy
SOURCE = "sim"
SIM_DEMO = "grip"        # "grip" = 8 s grip cycle, "hold" = sustained grip (shows fatigue)

# ---- acquisition (must match the ESP32 firmware) ------------------------
FS = 1000                # samples per second, per channel
NCH = 8
SAMPLES_PER_PACKET = 20  # 20 ms of data per BLE packet

# ---- ADC: TI ADS8688A, 16-bit ------------------------------------------
ADC_RANGE_V = 5.12       # input span in volts (+/-2.56 V range). Set to match the ADS8688A range register.
ADC_MID_CODE = 32768     # code for 0 V (straight binary output)
GAIN_TOTAL = 500.0       # TOTAL analog gain, in-amp x filter stage.  ** CONFIRM WITH HARDWARE **

# ---- display scaling ----------------------------------------------------
FULL_SCALE_RMS_MV = 1.5  # electrode RMS (mV) shown as 100% activation (fixed scale)
WAVE_RANGE_MV = 5.0      # waveform plots show +/- this many mV
ACTIVE_PCT = 15          # activation % above which a channel counts as contracting

# ---- channels (order = ADC input order) ---------------------------------
CHANNELS = [
    ("FCR",   "Flexor carpi radialis"),
    ("PL",    "Palmaris longus"),
    ("FCU",   "Flexor carpi ulnaris"),
    ("FDS-R", "Flexor dig. superficialis (radial)"),
    ("FDS-U", "Flexor dig. superficialis (ulnar)"),
    ("FDP",   "Flexor dig. profundus"),
    ("FPL",   "Flexor pollicis longus"),
    ("THN",   "Thenar (thumb loop)"),
]

# ---- Bluetooth (must match the ESP32 firmware) --------------------------
BLE_NAME = "ESP32-ManuCore"
BLE_DATA_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# ---- files --------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ASSET_DIR = os.path.join(APP_DIR, "assets")
SESSION_DIR = os.path.join(APP_DIR, "sessions")
