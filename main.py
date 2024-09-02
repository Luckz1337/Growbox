from machine import Pin, I2C
import bme280
import network
import socket
import CCS811  # Importiere die CCS811-Bibliothek
import bh1750  # BH1750-Bibliothek importieren
from time import sleep
import utime
import _thread
import json
import time

# Funktion zur Formatierung der aktuellen Uhrzeit
def format_datetime_custom(dt):
    year, month, day, hour, minute, second, _, _ = dt
    return "{:04d}/{:02d}/{:02d}-{:02d}:{:02d}:{:02d}".format(year, month, day, hour, minute, second)

# Klasse für den I2C-Multiplexer
class I2CMultiplexer:
    def __init__(self, i2c, address=0x70):
        self.i2c = i2c
        self.address = address

    def select_channel(self, channel):
        if channel < 0 or channel > 7:
            raise ValueError('Kanal muss zwischen 0 und 7 liegen')
        self.i2c.writeto(self.address, bytearray([1 << channel]))
        time.sleep(0.1)  # Kurze Verzögerung, um sicherzustellen, dass der Kanal aktiviert ist

# Klasse zur Verwaltung der Sensoren
class SensorManager:
    def __init__(self, multiplexer):
        self.multiplexer = multiplexer
        self.ccs811 = None
        self.bme280 = None
        self.bh1750 = None

    def init_ccs811(self, channel):
        self.multiplexer.select_channel(channel)
        self.ccs811 = CCS811.CCS811(i2c=self.multiplexer.i2c, addr=0x5A)
        while not self.ccs811.data_ready():
            time.sleep(1)

    def init_bme280(self, channel):
        self.multiplexer.select_channel(channel)
        self.bme280 = bme280.BME280(i2c=self.multiplexer.i2c)

    def init_bh1750(self, channel):
        self.multiplexer.select_channel(channel)
        self.bh1750 = bh1750.BH1750(self.multiplexer.i2c)

    def read_ccs811(self):
        self.multiplexer.select_channel(0)
        co2 = self.ccs811.eCO2
        tvoc = self.ccs811.tVOC
        print('CO2: {} ppm'.format(co2))
        print('TVOC: {} ppb'.format(tvoc))
        return co2, tvoc

    def read_bme280(self):
        self.multiplexer.select_channel(1)
        temperature, pressure, humidity = self.bme280.read_compensated_data()
        temp_celsius = temperature / 100
        pressure_hpa = pressure / 25600
        humidity_percent = humidity / 1024
        print('Temperatur: {:.2f}°C'.format(temp_celsius))
        print('Luftdruck: {:.2f} hPa'.format(pressure_hpa))
        print('Luftfeuchtigkeit: {:.2f}%'.format(humidity_percent))
        return temp_celsius, pressure_hpa, humidity_percent

    def read_bh1750(self):
        self.multiplexer.select_channel(2)
        light_intensity = self.bh1750.luminance(bh1750.BH1750.CONT_HIRES_1)
        print('Lichtintensität: {:.2f} Lux'.format(light_intensity))
        return light_intensity

# Initialisierung des I2C-Busses und des Multiplexers
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
multiplexer = I2CMultiplexer(i2c)
sensors = SensorManager(multiplexer)

# Initialisierung der Sensoren
sensors.init_ccs811(channel=0)
sensors.init_bme280(channel=1)
sensors.init_bh1750(channel=2)

# Globale Variablen für die letzten Sensorwerte
latest_bme280_temp = None
latest_bme280_pressure = None
latest_bme280_humidity = None
latest_ccs811_co2 = None
latest_ccs811_tvoc = None
latest_bh1750_lux = None

# Funktion zum Schreiben in eine CSV-Datei
def write_csv(filename, date, bme280_temp, bme280_pressure, bme280_humidity, ccs811_co2, ccs811_tvoc, bh1750_lux):
    with open(filename, 'a') as csvfile:
        csvfile.write(f"{date},{bme280_temp},{bme280_pressure},{bme280_humidity},{ccs811_co2},{ccs811_tvoc},{bh1750_lux}\n")

# WLAN-Verbindung herstellen
ssid = "FRITZ!Box 7530 OW"
password = "monkey-gin!"
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(ssid, password)

# Auf die Verbindung warten
max_wait = 10
while max_wait > 0:
    status = wlan.status()
    if status == network.STAT_GOT_IP:
        break
    max_wait -= 1
    print('Warten auf Verbindung...')
    sleep(1)

# Verbindung überprüfen
if wlan.status() != network.STAT_GOT_IP:
    raise RuntimeError('Netzwerkverbindung fehlgeschlagen')
else:
    print('Verbunden mit IP:', wlan.ifconfig()[0])



# Funktion zum Starten des Servers
def start_server():
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.bind(addr)
    s.listen(1)
    print('Server gestartet. Warte auf Verbindung...')
    return s

# Funktion zum Empfangen und Verarbeiten von Anfragen
def handle_requests(s):
    while True:
        cl, addr = s.accept()
        print('Client verbunden von', addr)
        request = cl.recv(1024)
        request = str(request)
        request = request.split("\\r\\n")[0].split(' ')
        if len(request) > 0 and request[0] == "b'GET":
            if request[1] == "/":
                request[1] = "/index.html"
            elif request[1] == "/api/sensordata":  # API-Endpunkt für Ajax
                send_sensor_data(cl)
            print('Angeforderte Datei:', request[1])
            if request[1] == "/index.html":
                send_html_page(cl)
        cl.close()

# Funktion zum Senden der HTML-Seite
def send_html_page(client):
    try:
        with open('index.html', 'rb') as f:
            response = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n" + f.read()
            client.send(response)
    except Exception as e:
        print(f"Error sending index.html: {e}")
        response = b"HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/html\r\n\r\n<h1>500 Internal Server Error</h1>"
        client.send(response)
    client.close()


# Funktion zum Senden der Sensordaten als JSON
def send_sensor_data(client):
    data = {
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

# Schleife, um die Sensoren alle 10 Sekunden auszulesen und die Daten in eine CSV-Datei zu schreiben
def sensor_loop():
    global latest_bme280_temp, latest_bme280_pressure, latest_bme280_humidity
    global latest_ccs811_co2, latest_ccs811_tvoc, latest_bh1750_lux

    while True:
        # Sensoren auslesen
        latest_bme280_temp, latest_bme280_pressure, latest_bme280_humidity = sensors.read_bme280()
        latest_ccs811_co2, latest_ccs811_tvoc = sensors.read_ccs811()
        latest_bh1750_lux = sensors.read_bh1750()

        # CSV-Schreiben
        date = format_datetime_custom(utime.localtime())
        write_csv('sensor_data.csv', date, latest_bme280_temp, latest_bme280_pressure, latest_bme280_humidity, latest_ccs811_co2, latest_ccs811_tvoc, latest_bh1750_lux)

        sleep(10)  # 10 Sekunden Wartezeit zwischen den Messungen

# Starten des Webservers und paralleles Starten des Sensor-Lesezyklus
server = start_server()
_thread.start_new_thread(sensor_loop, ())

handle_requests(server)

