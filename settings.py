DEFAULTS = {
    'I2C_SCL_PIN': 2,
    'I2C_SDA_PIN': 1,
    'I2C_FREQ': 100000,
    'MUX_ADDR': 0x70,
    'LED_PIN': 21,
    'SENSOR_POLL_INTERVAL': 15,  # Sensoren lesen, fuer Live-Anzeige
    'CSV_LOG_INTERVAL': 60,      # CSV-Zeile schreiben (verdichtet gegenueber dem Poll-Intervall)
    'WIFI_TIMEOUT': 30,
    'CSV_MAX_LINES': 50000,
    'MEMORY_THRESHOLD': 50000,
    'WDT_TIMEOUT': 300000,  # 5 Minuten
}

# Optionale Overrides aus settings_local.py (gitignored, pro Geraet).
# Ersetzt den alten Bug: CONFIG wurde bisher IMMER von den Defaults ueberschrieben,
# egal ob eine Nutzer-Config existierte - hier gewinnt settings_local wirklich.
CONFIG = dict(DEFAULTS)
try:
    from settings_local import OVERRIDES
    CONFIG.update(OVERRIDES)
    print("settings_local.py geladen")
except ImportError:
    pass

SENSORS = [
    {"id": "bme680_indoor", "label": "BME680 Indoor", "type": "bme68x",
     "bus": "i2c_mux", "mux_channel": 1, "address": 0x77,
     "stale_after_ms": 90_000},
    {"id": "ccs811", "label": "CCS811 eCO2/TVOC", "type": "ccs811",
     "bus": "i2c_mux", "mux_channel": 0, "address": 0x5A,
     "stale_after_ms": 90_000},
    {"id": "bh1750", "label": "BH1750 Lux", "type": "bh1750",
     "bus": "i2c_mux", "mux_channel": 2, "address": 0x23,
     "stale_after_ms": 90_000},
    {"id": "moisture1", "label": "Bodenfeuchte 1", "type": "capacitive_moisture",
     "bus": "adc", "pin": 4, "calib_air": 3131, "calib_water": 1500,
     "stale_after_ms": 90_000},
    {"id": "moisture2", "label": "Bodenfeuchte 2", "type": "capacitive_moisture",
     "bus": "adc", "pin": 5, "calib_air": 3131, "calib_water": 1500,
     "stale_after_ms": 90_000},
    # Zukuenftig, ohne Code-Aenderung ergaenzbar, z.B.:
    # {"id": "bme280_outdoor", "label": "BME280 Aussen", "type": "bme28x",
    #  "bus": "i2c_mux", "mux_channel": 3, "address": 0x76, "stale_after_ms": 120_000},
]

ACTUATORS = [
    {"id": "umluft", "label": "Umluft", "type": "pwm_fan",
     "pin": 9, "pwm_freq": 250, "min_value": 0, "max_value": 100, "floor": 0, "max_runtime_ms": None},
    {"id": "abluft", "label": "Abluft", "type": "pwm_fan",
     "pin": 18, "pwm_freq": 250, "min_value": 0, "max_value": 100, "floor": 0, "max_runtime_ms": None},
]

# Reihenfolge bestimmt die CSV-Spalten. Neue Sensor-Felder werden hier angehaengt,
# core/csv_log.py muss dafuer nicht angefasst werden. Aktor-Spalten werden aus
# ACTUATORS generiert, damit ein neuer Aktor automatisch eine Spalte bekommt
# (fuer die spaetere Auswertung "wie liefen die Luefter bei welcher Temperatur").
CSV_FIELDS = [
    "date",
    "bme680_indoor.temp", "bme680_indoor.pressure", "bme680_indoor.humidity", "bme680_indoor.gas",
    "ccs811.co2", "ccs811.tvoc",
    "bh1750.lux",
    "vpd",
    "moisture1.pct", "moisture2.pct", "moisture_avg",
] + [f"actuator.{a['id']}" for a in ACTUATORS]
