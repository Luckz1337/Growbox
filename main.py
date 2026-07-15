import gc
import asyncio
from machine import Pin, I2C, WDT

from settings import CONFIG, SENSORS, ACTUATORS, CSV_FIELDS
from core.registry import build_sensors, build_actuators
from core.csv_log import CsvLogger
from core.wifi import WiFiManager
from core.timeutil import sync_time, format_datetime, localtime_with_offset
from sensors import bme_sensor, ccs811_sensor, bh1750_sensor, moisture_sensor
from actuators import pwm_actuator
from actuators.control import ActuatorController
from actuators.schedule import ScheduleStore
from web.server import WebServer
from ota.ota import OTAUpdater
from wifi_config import SSID, PASSWORD
from device_secrets import WEB_USER, WEB_PASSWORD

SENSOR_FACTORIES = {
    "bme68x": bme_sensor.create_bme68x,
    "bme28x": bme_sensor.create_bme28x,
    "ccs811": ccs811_sensor.create,
    "bh1750": bh1750_sensor.create,
    "capacitive_moisture": moisture_sensor.create,
}
ACTUATOR_FACTORIES = {
    "pwm_fan": pwm_actuator.create,
}

OTA_REPO_URL = "https://raw.githubusercontent.com/Luckz1337/Growbox/"


def build_csv_row(sensors, controller):
    row = {"date": format_datetime(localtime_with_offset())}
    for sensor_id, sensor in sensors.items():
        for field, value in sensor.last_values.items():
            row[f"{sensor_id}.{field}"] = value

    bme = sensors.get("bme680_indoor")
    if bme:
        row["vpd"] = bme.last_values.get("vpd")

    m1, m2 = sensors.get("moisture1"), sensors.get("moisture2")
    if m1 and m2 and "pct" in m1.last_values and "pct" in m2.last_values:
        row["moisture_avg"] = round((m1.last_values["pct"] + m2.last_values["pct"]) / 2, 1)

    for actuator_id, actuator in controller.actuators.items():
        row[f"actuator.{actuator_id}"] = actuator.value
    return row


async def sensor_poll_loop(sensors):
    while True:
        for sensor in sensors.values():
            sensor.read()
            await asyncio.sleep_ms(0)
        await asyncio.sleep(CONFIG["SENSOR_POLL_INTERVAL"])


async def csv_log_loop(sensors, controller, csv_logger):
    while True:
        await asyncio.sleep(CONFIG["CSV_LOG_INTERVAL"])
        try:
            csv_logger.write_row(build_csv_row(sensors, controller))
        except Exception as e:
            print(f"[csv] write failed: {e}")


async def schedule_tick_task(schedule_store):
    while True:
        await asyncio.sleep(10)
        try:
            await schedule_store.check_and_apply()
        except Exception as e:
            print(f"[schedule] tick failed: {e}")


async def actuator_safety_task(controller):
    while True:
        await asyncio.sleep(10)
        for actuator in controller.actuators.values():
            actuator.check_runtime_limit()


async def wdt_feed_task(wdt):
    if wdt is None:
        return
    interval_s = max(1, CONFIG["WDT_TIMEOUT"] // 3000)
    while True:
        wdt.feed()
        await asyncio.sleep(interval_s)


async def wifi_watchdog_task(wifi):
    while True:
        await asyncio.sleep(15)
        if not wifi.is_connected():
            print("WLAN-Verbindung verloren - Neuverbindung...")
            if not wifi.connect():
                print("WLAN-Wiederverbindung fehlgeschlagen - Neustart...")
                import machine
                machine.reset()


async def memory_watchdog_task():
    while True:
        await asyncio.sleep(300)
        free_mem = gc.mem_free()
        if free_mem < CONFIG["MEMORY_THRESHOLD"]:
            print(f"Speicher knapp: {free_mem:,}B - Garbage Collection...")
            gc.collect()
            print(f"Nach GC: {gc.mem_free():,}B")


async def main():
    print("=" * 60)
    print("ESP32-S3 Growbox Station")
    print("=" * 60)

    try:
        wdt = WDT(timeout=CONFIG["WDT_TIMEOUT"])
        print(f"Watchdog aktiviert ({CONFIG['WDT_TIMEOUT'] // 60000}min)")
    except Exception as e:
        print(f"Watchdog konnte nicht aktiviert werden: {e}")
        wdt = None

    status_led = None
    try:
        status_led = Pin(CONFIG["LED_PIN"], Pin.OUT)
        status_led.on()
    except Exception as e:
        print(f"Status-LED Fehler: {e}")

    gc.collect()
    print(f"Verfuegbarer Speicher: {gc.mem_free():,} bytes")

    print("Stelle WLAN-Verbindung her...")
    wifi = WiFiManager(SSID, PASSWORD, timeout_s=CONFIG["WIFI_TIMEOUT"])
    if not wifi.connect():
        print("WLAN-Verbindung fehlgeschlagen - Neustart...")
        await asyncio.sleep(5)
        import machine
        machine.reset()

    print("Synchronisiere Zeit...")
    if sync_time():
        print("Zeit erfolgreich synchronisiert")
    else:
        print("Zeit-Synchronisation fehlgeschlagen - verwende lokale Zeit")

    print("Initialisiere I2C und Sensoren...")
    i2c = I2C(0, scl=Pin(CONFIG["I2C_SCL_PIN"]), sda=Pin(CONFIG["I2C_SDA_PIN"]), freq=CONFIG["I2C_FREQ"])
    devices = i2c.scan()
    print(f"I2C-Geraete gefunden: {[hex(d) for d in devices]}")
    sensors = build_sensors(SENSORS, i2c, SENSOR_FACTORIES, mux_addr=CONFIG["MUX_ADDR"])
    print(f"{len(sensors)}/{len(SENSORS)} Sensoren aktiv: {list(sensors.keys())}")

    print("Initialisiere Aktoren...")
    actuators = build_actuators(ACTUATORS, ACTUATOR_FACTORIES)
    controller = ActuatorController(actuators)
    print(f"{len(actuators)}/{len(ACTUATORS)} Aktoren aktiv: {list(actuators.keys())}")

    schedule_store = ScheduleStore(controller)
    csv_logger = CsvLogger("sensor_data.csv", CSV_FIELDS, CONFIG["CSV_MAX_LINES"])
    ota_updater = OTAUpdater(OTA_REPO_URL)

    if status_led:
        status_led.off()

    server = WebServer(sensors, controller, schedule_store, csv_logger, wifi, CONFIG,
                        WEB_USER, WEB_PASSWORD, ota_updater=ota_updater)
    await server.start()

    print("=" * 60)
    print("SYSTEM BEREIT")
    print(f"Dashboard: http://{wifi.wlan.ifconfig()[0]}")
    print(f"Freier Speicher: {gc.mem_free():,} bytes")
    print("=" * 60)

    await asyncio.gather(
        sensor_poll_loop(sensors),
        csv_log_loop(sensors, controller, csv_logger),
        schedule_tick_task(schedule_store),
        actuator_safety_task(controller),
        wdt_feed_task(wdt),
        wifi_watchdog_task(wifi),
        memory_watchdog_task(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"KRITISCHER STARTUP-FEHLER: {e}")
        import sys
        sys.print_exception(e)
        import time
        print("Neustart in 10 Sekunden...")
        time.sleep(10)
        import machine
        machine.reset()
