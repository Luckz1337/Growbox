from machine import Pin, I2C, reset
from libraries import bme280
from libraries import CCS811
from libraries import bh1750
from ota.ota import OTAUpdater
from wifi_config import SSID, PASSWORD
import network
import socket
import time
import utime
import _thread
import json
import ntptime

# Zeit-Sync mit Sommerzeit

def sync_time_with_dst():
    try:
        ntptime.settime()
        tm = utime.localtime()
        timezone_offset_hours = 2 if is_dst_europe(tm) else 1
        local_time = utime.localtime(utime.time() + timezone_offset_hours * 3600)
        print("Aktuelle lokale Uhrzeit:", format_datetime_custom(local_time))
    except Exception as e:
        print("Fehler bei der Zeit-Synchronisation:", e)

def is_dst_europe(dt):
    year, month, day, hour, minute, second, weekday, yearday = dt
    if month > 3 and month < 10:
        return True
    if month == 3:
        return (day + (6 - weekday)) > 31
    if month == 10:
        return not (day + (6 - weekday)) > 31
    return False

def format_datetime_custom(dt):
    year, month, day, hour, minute, second, _, _ = dt
    return "{:04d}/{:02d}/{:02d}-{:02d}:{:02d}:{:02d}".format(year, month, day, hour, minute, second)

sync_time_with_dst()

class I2CMultiplexer:
    def __init__(self, i2c, address=0x70):
        self.i2c = i2c
        self.address = address

    def select_channel(self, channel):
        if channel < 0 or channel > 7:
            raise ValueError('Kanal muss zwischen 0 und 7 liegen')
        self.i2c.writeto(self.address, bytearray([1 << channel]))
        time.sleep(0.1)

class SensorManager:
    def __init__(self, multiplexer):
        self.multiplexer = multiplexer
        self.ccs811 = None
        self.bme280 = None
        self.bh1750 = None

    def init_ccs811(self, channel):
        try:
            self.multiplexer.select_channel(channel)
            self.ccs811 = CCS811.CCS811(i2c=self.multiplexer.i2c, addr=0x5A)
            while not self.ccs811.data_ready():
                time.sleep(1)
        except Exception as e:
            print("Fehler beim Initialisieren von CCS811:", e)

    def init_bme280(self, channel):
        try:
            self.multiplexer.select_channel(channel)
            self.bme280 = bme280.BME280(i2c=self.multiplexer.i2c)
        except Exception as e:
            print("Fehler beim Initialisieren von BME280:", e)

    def init_bh1750(self, channel):
        try:
            self.multiplexer.select_channel(channel)
            self.bh1750 = bh1750.BH1750(self.multiplexer.i2c)
        except Exception as e:
            print("Fehler beim Initialisieren von BH1750:", e)

    def read_ccs811(self):
        try:
            self.multiplexer.select_channel(0)
            co2 = self.ccs811.eCO2 if self.ccs811 else 0
            tvoc = self.ccs811.tVOC if self.ccs811 else 0
            return co2, tvoc
        except Exception as e:
            print("Fehler beim Lesen von CCS811:", e)
            return 0, 0

    def read_bme280(self):
        try:
            self.multiplexer.select_channel(1)
            if self.bme280:
                temperature, pressure, humidity = self.bme280.read_compensated_data()
                return temperature / 100, pressure / 25600, humidity / 1024
        except Exception as e:
            print("Fehler beim Lesen von BME280:", e)
        return 0, 0, 0

    def read_bh1750(self):
        try:
            self.multiplexer.select_channel(2)
            return self.bh1750.luminance(bh1750.BH1750.CONT_HIRES_1) if self.bh1750 else 0.0
        except Exception as e:
            print("Fehler beim Lesen von BH1750:", e)
            return 0.0

# Setup

i2c = I2C(0, scl=Pin(9), sda=Pin(8), freq=100000)
multiplexer = I2CMultiplexer(i2c)
sensors = SensorManager(multiplexer)

sensors.init_ccs811(channel=0)
sensors.init_bme280(channel=1)
sensors.init_bh1750(channel=2)

latest_bme280_temp = None
latest_bme280_pressure = None
latest_bme280_humidity = None
latest_ccs811_co2 = None
latest_ccs811_tvoc = None
latest_bh1750_lux = None

def write_csv(filename, date, bme280_temp, bme280_pressure, bme280_humidity, ccs811_co2, ccs811_tvoc, bh1750_lux):
    with open(filename, 'a') as csvfile:
        csvfile.write(f"{date},{bme280_temp},{bme280_pressure},{bme280_humidity},{ccs811_co2},{ccs811_tvoc},{bh1750_lux}\n")

# WLAN

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(SSID, PASSWORD)

max_wait = 10
while max_wait > 0:
    if wlan.status() == network.STAT_GOT_IP:
        break
    max_wait -= 1
    time.sleep(1)

if wlan.status() != network.STAT_GOT_IP:
    raise RuntimeError('Netzwerkverbindung fehlgeschlagen')
else:
    print('Verbunden mit IP:', wlan.ifconfig()[0])

def start_server():
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(1)
    print('Server gestartet. Warte auf Verbindung...')
    return s

def send_sensor_data(client):
    data = {
        "date": format_datetime_custom(utime.localtime()),
        "bme280_temp": latest_bme280_temp,
        "bme280_pressure": latest_bme280_pressure,
        "bme280_humidity": latest_bme280_humidity,
        "ccs811_co2": latest_ccs811_co2,
        "ccs811_tvoc": latest_ccs811_tvoc,
        "bh1750_lux": latest_bh1750_lux
    }
    response = json.dumps(data)
    client.send(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + response.encode('utf-8'))
    client.close()

def send_csv_data_as_json(client):
    result = []
    try:
        with open('sensor_data.csv') as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 7:
                    result.append({
                        "date": parts[0],
                        "bme280_temp": float(parts[1]),
                        "bme280_pressure": float(parts[2]),
                        "bme280_humidity": float(parts[3]),
                        "ccs811_co2": int(parts[4]),
                        "ccs811_tvoc": int(parts[5]),
                        "bh1750_lux": float(parts[6])
                    })
    except Exception as e:
        print("Fehler beim Lesen von CSV:", e)
    response = json.dumps(result)
    client.send(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + response.encode('utf-8'))
    client.close()

def reset_device(client):
    client.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Gerät wird neu gestartet...</h1>")
    client.close()
    time.sleep(1)
    reset()

def check_for_updates_endpoint(client):
    try:
        firmware_url = "https://raw.githubusercontent.com/Luckz1337/Growbox/"
        ota_updater = OTAUpdater(SSID, PASSWORD, firmware_url, "main.py")
        ota_updater.download_and_install_update_if_available()
        client.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Update abgeschlossen.</h1>")
    except Exception as e:
        print("Fehler beim OTA:", e)
        client.send(b"HTTP/1.1 500 Internal Server Error\r\n\r\n<h1>OTA fehlgeschlagen.</h1>")
    client.close()

def handle_requests(s):
    while True:
        cl, addr = s.accept()
        request = cl.recv(1024).decode()
        path = request.split(" ")[1] if len(request.split(" ")) > 1 else "/"
        if path == "/":
            path = "/index.html"
        if path == "/api/sensordata":
            send_sensor_data(cl)
        elif path == "/api/history":
            send_csv_data_as_json(cl)
        elif path == "/reset":
            reset_device(cl)
        elif path == "/update":
            check_for_updates_endpoint(cl)
        elif path == "/index.html":
            try:
                with open("index.html", "rb") as f:
                    cl.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + f.read())
            except:
                cl.send(b"HTTP/1.1 500 Internal Server Error\r\n\r\n<h1>index.html fehlt.</h1>")
        cl.close()

def sensor_loop():
    global latest_bme280_temp, latest_bme280_pressure, latest_bme280_humidity
    global latest_ccs811_co2, latest_ccs811_tvoc, latest_bh1750_lux
    while True:
        try:
            latest_bme280_temp, latest_bme280_pressure, latest_bme280_humidity = sensors.read_bme280()
            latest_ccs811_co2, latest_ccs811_tvoc = sensors.read_ccs811()
            latest_bh1750_lux = sensors.read_bh1750()
            date = format_datetime_custom(utime.localtime())
            write_csv('sensor_data.csv', date, latest_bme280_temp, latest_bme280_pressure, latest_bme280_humidity,
                      latest_ccs811_co2, latest_ccs811_tvoc, latest_bh1750_lux)
        except Exception as e:
            print("Fehler in sensor_loop:", e)
        time.sleep(10)

server = start_server()
_thread.start_new_thread(sensor_loop, ())
handle_requests(server)

