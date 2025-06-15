from machine import Pin, I2C, reset, WDT, ADC, PWM
from libraries import bme680
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
import gc
import os
import math

# Konfiguration für ESP32-S3 FireBeetle 2
CONFIG = {
    'I2C_SCL_PIN': 2,        # Hardware I2C SCL Pin
    'I2C_SDA_PIN': 1,        # Hardware I2C SDA Pin  
    'I2C_FREQ': 100000,
    'LED_PIN': 21,           # Onboard LED Pin (geändert von 12 auf 21)
    'SENSOR_READ_INTERVAL': 10,
    'WIFI_TIMEOUT': 30,
    'MAX_RETRIES': 3,
    'CSV_MAX_LINES': 500,
    'MEMORY_THRESHOLD': 50000,  # ESP32-S3 hat mehr RAM
    # Bodenfeuchtigkeitssensor Konfiguration
    'MOISTURE_SENSOR1_PIN': 4,   # A0/GPIO4
    'MOISTURE_SENSOR2_PIN': 5,   # A1/GPIO5
    'MOISTURE_AIR_RAW1': 3131,   # Sensor1 trocken (Luft)
    'MOISTURE_WATER_RAW1': 1500, # Sensor1 nass (Wasser)
    'MOISTURE_AIR_RAW2': 3131,   # Sensor2 trocken (Luft)
    'MOISTURE_WATER_RAW2': 1500, # Sensor2 nass (Wasser)
    # Ventilator Konfiguration
    'FAN_PIN_UMLUFT': 9,     # SIG am MOSFET für Umluft
    'FAN_PIN_ABLUFT': 12,    # SIG am MOSFET für Abluft
    'FAN_PWM_FREQ': 250,
}

# Vereinfachte Error-Klasse
def log_error(component, error):
    print(f"[{component}] {error}")

# Vereinfachte Memory-Checks
def check_memory():
    free = gc.mem_free()
    if free < CONFIG['MEMORY_THRESHOLD']:
        gc.collect()
        return gc.mem_free()
    return free

def cleanup_csv(filename, max_lines):
    try:
        # Lese nur die Anzahl der Zeilen
        line_count = 0
        with open(filename, 'r') as f:
            for _ in f:
                line_count += 1
        
        if line_count > max_lines:
            # Lese alle Zeilen und behalte nur die letzten
            lines = []
            with open(filename, 'r') as f:
                for line in f:
                    lines.append(line)
                    if len(lines) > max_lines:
                        lines.pop(0)
            
            # Schreibe zurück
            with open(filename, 'w') as f:
                for line in lines:
                    f.write(line)
            print(f"CSV auf {max_lines} Zeilen gekürzt")
    except Exception as e:
        log_error("CSV cleanup", str(e))

# VPD Berechnung
def calculate_vpd(temp_c, humidity_percent):
    """
    Berechnet den Vapor Pressure Deficit (VPD) in kPa
    
    Args:
        temp_c: Temperatur in Celsius
        humidity_percent: Relative Luftfeuchtigkeit in Prozent
    
    Returns:
        VPD in kPa
    """
    try:
        # Sättigungsdampfdruck bei gegebener Temperatur (kPa)
        # Magnus-Formel
        svp = 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
        
        # Aktueller Dampfdruck
        avp = svp * (humidity_percent / 100.0)
        
        # VPD = Sättigungsdampfdruck - Aktueller Dampfdruck
        vpd = svp - avp
        
        return round(vpd, 3)
    except:
        return 0

def get_vpd_status(vpd):
    """
    Bewertet den VPD-Wert
    
    Returns:
        Status string: "optimal", "warning", "critical"
    """
    if 0.8 <= vpd <= 1.2:
        return "optimal"
    elif 0.4 <= vpd <= 1.6:
        return "warning"
    else:
        return "critical"

def get_moisture_status(moisture_pct):
    """
    Bewertet den Bodenfeuchtigkeitswert
    
    Returns:
        Status string: "optimal", "warning", "critical"
    """
    if 40 <= moisture_pct <= 60:
        return "optimal"
    elif 20 <= moisture_pct <= 80:
        return "warning"
    else:
        return "critical"

class WiFiManager:
    def __init__(self, ssid, password):
        self.ssid = ssid
        self.password = password
        self.wlan = network.WLAN(network.STA_IF)
        
    def connect(self):
        self.wlan.active(True)
        self.wlan.connect(self.ssid, self.password)
        
        for _ in range(CONFIG['WIFI_TIMEOUT']):
            # ESP32-S3 verwendet Status 1010 für erfolgreiche Verbindung
            if self.wlan.status() == 1010:  # STAT_GOT_IP für ESP32-S3
                print(f'WiFi verbunden: {self.wlan.ifconfig()[0]}')
                return True
            time.sleep(1)
        return False
    
    def is_connected(self):
        return self.wlan.status() == 1010  # STAT_GOT_IP für ESP32-S3

# Zeit-Funktionen
def is_dst_europe(dt):
    month = dt[1]
    if month > 3 and month < 10:
        return True
    return month == 3 and (dt[2] + (6 - dt[6])) > 31

def localtime_with_offset():
    tz_offset = 2 * 3600 if is_dst_europe(utime.localtime()) else 1 * 3600
    return utime.localtime(utime.time() + tz_offset)

def format_datetime(dt):
    return "{:04d}/{:02d}/{:02d}-{:02d}:{:02d}:{:02d}".format(
        dt[0], dt[1], dt[2], dt[3], dt[4], dt[5])

def sync_time():
    try:
        ntptime.settime()
        print("Zeit synchronisiert:", format_datetime(localtime_with_offset()))
        return True
    except:
        return False

class I2CMultiplexer:
    def __init__(self, i2c):
        self.i2c = i2c
        self.current = None

    def select(self, ch):
        if self.current != ch:
            try:
                self.i2c.writeto(0x70, bytearray([1 << ch]))
                self.current = ch
                time.sleep(0.05)
            except Exception as e:
                log_error("I2C Mux", f"Kanal {ch}: {str(e)}")

class MoistureSensor:
    """Klasse für Bodenfeuchtigkeitssensoren"""
    def __init__(self, pin1, pin2, air_raw1, water_raw1, air_raw2, water_raw2):
        self.adc1 = ADC(Pin(pin1))
        self.adc2 = ADC(Pin(pin2))
        
        # ADC Konfiguration
        for adc in (self.adc1, self.adc2):
            adc.atten(ADC.ATTN_11DB)    # bis ~3,6 V
            adc.width(ADC.WIDTH_12BIT)  # 0–4095
        
        # Kalibrierwerte
        self.air_raw1 = air_raw1
        self.water_raw1 = water_raw1
        self.air_raw2 = air_raw2
        self.water_raw2 = water_raw2
    
    def calc_pct(self, raw, air, water):
        """Berechnet Prozent aus Rohwert"""
        pct = (air - raw) * 100 / (air - water)
        if pct < 0:
            return 0
        if pct > 100:
            return 100
        return pct
    
    def read(self):
        """Liest beide Sensoren und gibt Werte zurück"""
        raw1 = self.adc1.read()
        raw2 = self.adc2.read()
        
        pct1 = self.calc_pct(raw1, self.air_raw1, self.water_raw1)
        pct2 = self.calc_pct(raw2, self.air_raw2, self.water_raw2)
        
        return {
            'raw1': raw1,
            'raw2': raw2,
            'pct1': round(pct1, 1),
            'pct2': round(pct2, 1),
            'avg': round((pct1 + pct2) / 2, 1)
        }

class FanController:
    """Klasse zur Steuerung der Ventilatoren"""
    def __init__(self, pin_umluft, pin_abluft, pwm_freq):
        self.fan_umluft = PWM(Pin(pin_umluft))
        self.fan_abluft = PWM(Pin(pin_abluft))
        self.fan_umluft.freq(pwm_freq)
        self.fan_abluft.freq(pwm_freq)
        
        # Speichere aktuelle Geschwindigkeiten
        self.umluft_speed = 0.0
        self.abluft_speed = 0.0
        
        # Starte mit ausgeschalteten Ventilatoren
        self.set_umluft_speed(0)
        self.set_abluft_speed(0)
    
    def set_umluft_speed(self, percent):
        """Setzt die Umluft-Drehzahl auf 'percent' Prozent (0.0 .. 100.0)"""
        if not 0 <= percent <= 100:
            raise ValueError("percent muss zwischen 0 und 100 liegen")
        self.umluft_speed = percent
        duty = int(percent / 100 * 65535)
        self.fan_umluft.duty_u16(duty)
        print(f"Umluft-Ventilator auf {percent}% gesetzt")
    
    def set_abluft_speed(self, percent):
        """Setzt die Abluft-Drehzahl auf 'percent' Prozent (0.0 .. 100.0)"""
        if not 0 <= percent <= 100:
            raise ValueError("percent muss zwischen 0 und 100 liegen")
        self.abluft_speed = percent
        duty = int(percent / 100 * 65535)
        self.fan_abluft.duty_u16(duty)
        print(f"Abluft-Ventilator auf {percent}% gesetzt")
    
    def get_speeds(self):
        """Gibt die aktuellen Geschwindigkeiten zurück"""
        return {
            'umluft': self.umluft_speed,
            'abluft': self.abluft_speed
        }
    
    def auto_control(self, temp, humidity, co2):
        """Automatische Ventilatorsteuerung basierend auf Sensordaten"""
        # Beispiel für automatische Steuerung (kann angepasst werden)
        if temp > 28 or humidity > 70 or co2 > 1000:
            # Hohe Werte - mehr Belüftung
            self.set_umluft_speed(80)
            self.set_abluft_speed(80)
        elif temp > 25 or humidity > 60 or co2 > 800:
            # Mittlere Werte
            self.set_umluft_speed(50)
            self.set_abluft_speed(50)
        elif temp > 22 or humidity > 50 or co2 > 600:
            # Normale Werte
            self.set_umluft_speed(30)
            self.set_abluft_speed(30)
        else:
            # Niedrige Werte - minimale Belüftung
            self.set_umluft_speed(20)
            self.set_abluft_speed(20)

class SensorManager:
    def __init__(self, mux):
        self.mux = mux
        self.sensors = {}
        self.last = {}  # Letzte Werte

    def init_sensors(self):
        # LED für Status-Anzeige
        self.status_led = Pin(CONFIG['LED_PIN'], Pin.OUT)
        
        # CCS811
        try:
            self.mux.select(0)
            self.sensors['ccs811'] = CCS811.CCS811(i2c=self.mux.i2c, addr=0x5A)
            print("CCS811 initialisiert")
            self.status_led.on()
            time.sleep(0.1)
            self.status_led.off()
        except Exception as e:
            log_error("CCS811 init", str(e))
            
        # BME680
        try:
            self.mux.select(1)
            self.sensors['bme680'] = bme680.BME680_I2C(i2c=self.mux.i2c, address=0x77)
            print("BME680 initialisiert")
            self.status_led.on()
            time.sleep(0.1)
            self.status_led.off()
        except Exception as e:
            log_error("BME680 init", str(e))
            
        # BH1750
        try:
            self.mux.select(2)
            self.sensors['bh1750'] = bh1750.BH1750(self.mux.i2c)
            print("BH1750 initialisiert")
            self.status_led.on()
            time.sleep(0.1)
            self.status_led.off()
        except Exception as e:
            log_error("BH1750 init", str(e))
        
        # Bodenfeuchtigkeitssensor
        try:
            self.sensors['moisture'] = MoistureSensor(
                CONFIG['MOISTURE_SENSOR1_PIN'],
                CONFIG['MOISTURE_SENSOR2_PIN'],
                CONFIG['MOISTURE_AIR_RAW1'],
                CONFIG['MOISTURE_WATER_RAW1'],
                CONFIG['MOISTURE_AIR_RAW2'],
                CONFIG['MOISTURE_WATER_RAW2']
            )
            print("Bodenfeuchtigkeitssensoren initialisiert")
            self.status_led.on()
            time.sleep(0.1)
            self.status_led.off()
        except Exception as e:
            log_error("Moisture init", str(e))

    def read_all(self):
        data = {}
        
        # BME680
        if 'bme680' in self.sensors:
            try:
                self.mux.select(1)
                s = self.sensors['bme680']
                data['temp'] = s.temperature
                data['pres'] = s.pressure
                data['hum'] = s.humidity
                data['gas'] = s.gas
                # Berechne VPD
                data['vpd'] = calculate_vpd(data['temp'], data['hum'])
                data['vpd_status'] = get_vpd_status(data['vpd'])
                self.last['bme680'] = (data['temp'], data['pres'], data['hum'], data['gas'], data['vpd'])
            except Exception as e:
                log_error("BME680 read", str(e))
                if 'bme680' in self.last:
                    data['temp'], data['pres'], data['hum'], data['gas'], data['vpd'] = self.last['bme680']
                    data['vpd_status'] = get_vpd_status(data['vpd'])
                else:
                    data['temp'] = data['pres'] = data['hum'] = data['gas'] = 0
                    data['vpd'] = 0
                    data['vpd_status'] = "unknown"
        
        # CCS811
        if 'ccs811' in self.sensors:
            try:
                self.mux.select(0)
                s = self.sensors['ccs811']
                if s.data_ready():
                    data['co2'] = s.eCO2
                    data['tvoc'] = s.tVOC
                    self.last['ccs811'] = (data['co2'], data['tvoc'])
                elif 'ccs811' in self.last:
                    data['co2'], data['tvoc'] = self.last['ccs811']
                else:
                    data['co2'] = 400
                    data['tvoc'] = 0
            except Exception as e:
                log_error("CCS811 read", str(e))
                data['co2'] = 400
                data['tvoc'] = 0
        else:
            data['co2'] = 400
            data['tvoc'] = 0
        
        # BH1750
        if 'bh1750' in self.sensors:
            try:
                self.mux.select(2)
                data['lux'] = self.sensors['bh1750'].luminance(bh1750.BH1750.CONT_HIRES_1)
                self.last['bh1750'] = data['lux']
            except Exception as e:
                log_error("BH1750 read", str(e))
                data['lux'] = self.last.get('bh1750', 0)
        else:
            data['lux'] = 0
        
        # Bodenfeuchtigkeitssensor
        if 'moisture' in self.sensors:
            try:
                moisture_data = self.sensors['moisture'].read()
                data['moisture1'] = moisture_data['pct1']
                data['moisture2'] = moisture_data['pct2']
                data['moisture_avg'] = moisture_data['avg']
                data['moisture_status'] = get_moisture_status(moisture_data['avg'])
                self.last['moisture'] = (data['moisture1'], data['moisture2'], data['moisture_avg'])
            except Exception as e:
                log_error("Moisture read", str(e))
                if 'moisture' in self.last:
                    data['moisture1'], data['moisture2'], data['moisture_avg'] = self.last['moisture']
                    data['moisture_status'] = get_moisture_status(data['moisture_avg'])
                else:
                    data['moisture1'] = data['moisture2'] = data['moisture_avg'] = 0
                    data['moisture_status'] = "unknown"
        else:
            data['moisture1'] = data['moisture2'] = data['moisture_avg'] = 0
            data['moisture_status'] = "unknown"
            
        return data

def write_csv(date, data):
    try:
        with open('sensor_data.csv', 'a') as f:
            f.write(f"{date},{data['temp']},{data['pres']},{data['hum']},{data['gas']},{data['co2']},{data['tvoc']},{data['lux']},{data['vpd']},{data['moisture1']},{data['moisture2']},{data['moisture_avg']}\n")
    except Exception as e:
        log_error("CSV write", str(e))

class WebServer:
    def __init__(self):
        self.server = None
        
    def start(self):
        addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(addr)
        self.server.listen(1)
        print('Webserver gestartet auf Port 80')
        return self.server

    def send_file_chunked(self, client, filename, content_type):
        """Sendet Datei in kleinen Chunks"""
        try:
            # Sende Header
            headers = f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nTransfer-Encoding: chunked\r\n\r\n"
            client.send(headers.encode())
            
            # Sende Datei in 1024-Byte Chunks (ESP32-S3 hat mehr RAM)
            with open(filename, 'rb') as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    
                    # Chunk-Format: Größe in Hex + CRLF + Daten + CRLF
                    size = hex(len(chunk))[2:]
                    client.send(f"{size}\r\n".encode())
                    client.send(chunk)
                    client.send(b"\r\n")
                    
                    # Kurze Pause für Speicher
                    time.sleep(0.01)
                    gc.collect()
                
                # Ende-Marker
                client.send(b"0\r\n\r\n")
                
        except Exception as e:
            log_error("send_file", str(e))

    def send_json(self, client, data):
        try:
            response = json.dumps(data)
            print(f"JSON Response length: {len(response)}")  # Debug
            headers = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(response)}\r\n\r\n"
            client.send(headers.encode() + response.encode())
        except Exception as e:
            log_error("send_json", str(e))
            # Sende Fehler-Response
            error_response = '{"error": "Internal server error"}'
            headers = f"HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\nContent-Length: {len(error_response)}\r\n\r\n"
            client.send(headers.encode() + error_response.encode())

    def send_history(self, client):
        """Sendet CSV-Historie als JSON-Stream"""
        try:
            headers = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
            client.send(headers.encode())
            
            # Start Array
            client.send(b"2\r\n[\r\n")
            
            first = True
            line_count = 0
            
            with open('sensor_data.csv', 'r') as f:
                # Skip header
                f.readline()
                
                # Zähle Zeilen
                lines = []
                for line in f:
                    lines.append(line)
                
                # Nur die letzten 50 (ESP32-S3 kann mehr)
                for line in lines[-50:]:
                    parts = line.strip().split(",")
                    if len(parts) >= 8:  # Mindestens 8 Felder (kompatibel mit alten Daten)
                        try:
                            entry = {
                                "date": parts[0],
                                "bme680_temp": float(parts[1]),
                                "bme680_pressure": float(parts[2]),
                                "bme680_humidity": float(parts[3]),
                                "bme680_gas": float(parts[4]),
                                "ccs811_co2": int(parts[5]),
                                "ccs811_tvoc": int(parts[6]),
                                "bh1750_lux": float(parts[7])
                            }
                            
                            # VPD hinzufügen wenn vorhanden
                            if len(parts) > 8:
                                entry["vpd"] = float(parts[8])
                            else:
                                # Berechne VPD für alte Daten
                                entry["vpd"] = calculate_vpd(entry["bme680_temp"], entry["bme680_humidity"])
                            
                            # Bodenfeuchtigkeit hinzufügen wenn vorhanden
                            if len(parts) > 11:
                                entry["moisture1"] = float(parts[9])
                                entry["moisture2"] = float(parts[10])
                                entry["moisture_avg"] = float(parts[11])
                            else:
                                entry["moisture1"] = 0
                                entry["moisture2"] = 0
                                entry["moisture_avg"] = 0
                            
                            if not first:
                                client.send(b"1\r\n,\r\n")
                            else:
                                first = False
                                
                            chunk = json.dumps(entry)
                            size = hex(len(chunk))[2:]
                            client.send(f"{size}\r\n{chunk}\r\n".encode())
                            
                        except:
                            continue
            
            # Ende Array
            client.send(b"2\r\n]\r\n")
            client.send(b"0\r\n\r\n")
            
        except Exception as e:
            log_error("send_history", str(e))

    def handle(self, client, path, sensor_data):
        try:
            print(f"Request: {path}")  # Debug-Ausgabe
            
            if path == "/" or path == "/index.html":
                self.send_file_chunked(client, "index.html", "text/html")
            elif path == "/api/sensordata":
                print(f"Sending sensor data: {sensor_data}")  # Debug
                self.send_json(client, sensor_data)
            elif path == "/api/history":
                self.send_history(client)
            elif path == "/api/status":
                # Erweiterte System-Metriken für API
                free_mem = gc.mem_free()
                alloc_mem = gc.mem_alloc()
                total_mem = free_mem + alloc_mem
                mem_usage = (alloc_mem / total_mem) * 100
                
                # WiFi-Metriken
                rssi = wifi.wlan.status('rssi')
                ip_config = wifi.wlan.ifconfig()
                mac = ':'.join(['{:02x}'.format(b) for b in wifi.wlan.config('mac')])
                
                # System-Info
                import machine
                freq = machine.freq()
                uptime_sec = time.ticks_ms() // 1000
                
                # CSV-Datei Info
                csv_size = 0
                csv_lines = 0
                try:
                    stat = os.stat('sensor_data.csv')
                    csv_size = stat[6]
                    with open('sensor_data.csv', 'r') as f:
                        csv_lines = sum(1 for _ in f) - 1  # Header nicht mitzählen
                except:
                    pass
                
                status = {
                    # Speicher
                    "memory": {
                        "total": total_mem,
                        "free": free_mem,
                        "allocated": alloc_mem,
                        "usage_percent": round(mem_usage, 1)
                    },
                    # WiFi
                    "wifi": {
                        "rssi": rssi,
                        "signal_quality": "Exzellent" if rssi > -50 else "Sehr gut" if rssi > -60 else "Gut" if rssi > -70 else "Schwach",
                        "ip_address": ip_config[0],
                        "subnet": ip_config[1],
                        "gateway": ip_config[2],
                        "dns": ip_config[3],
                        "mac_address": mac
                    },
                    # System
                    "system": {
                        "chip": "ESP32-S3",
                        "cpu_freq": freq,
                        "uptime_seconds": uptime_sec,
                        "uptime_formatted": f"{uptime_sec//3600}h {(uptime_sec%3600)//60}m {uptime_sec%60}s"
                    },
                    # Daten
                    "data": {
                        "csv_size_bytes": csv_size,
                        "csv_lines": csv_lines,
                        "sensor_interval": CONFIG['SENSOR_READ_INTERVAL']
                    },
                    "timestamp": format_datetime(localtime_with_offset())
                }
                self.send_json(client, status)
            elif path == "/test":
                # Test-Endpoint
                test_data = {
                    "test": "OK",
                    "timestamp": format_datetime(localtime_with_offset()),
                    "message": "ESP32-S3 Test Response"
                }
                self.send_json(client, test_data)
            elif path == "/api/fans":
                # Ventilator-Status
                fan_status = fans.get_speeds()
                self.send_json(client, fan_status)
            elif path.startswith("/api/fans/set"):
                # Ventilator-Steuerung
                try:
                    # Parse Parameter aus URL
                    if "?" in path:
                        params = path.split("?")[1]
                        param_dict = {}
                        for param in params.split("&"):
                            key, value = param.split("=")
                            param_dict[key] = float(value)
                        
                        if "umluft" in param_dict:
                            fans.set_umluft_speed(param_dict["umluft"])
                        if "abluft" in param_dict:
                            fans.set_abluft_speed(param_dict["abluft"])
                        
                        response = {
                            "status": "success",
                            "speeds": fans.get_speeds()
                        }
                        self.send_json(client, response)
                    else:
                        self.send_json(client, {"error": "No parameters"})
                except Exception as e:
                    self.send_json(client, {"error": str(e)})
            elif path == "/api/ota/check":
                # OTA Update Check
                try:
                    from ota.ota import OTAUpdater
                    firmware_url = "https://raw.githubusercontent.com/DEIN_USERNAME/DEIN_REPO/"
                    ota = OTAUpdater(SSID, PASSWORD, firmware_url, "main.py")
                    
                    if ota.check_for_updates():
                        response = {
                            "update_available": True,
                            "current_version": ota.current_version,
                            "latest_version": ota.latest_version
                        }
                    else:
                        response = {
                            "update_available": False,
                            "current_version": ota.current_version,
                            "latest_version": ota.latest_version
                        }
                    self.send_json(client, response)
                except Exception as e:
                    self.send_json(client, {"error": str(e)})
            elif path == "/api/ota/update":
                # OTA Update durchführen
                try:
                    from ota.ota import OTAUpdater
                    firmware_url = "https://raw.githubusercontent.com/DEIN_USERNAME/DEIN_REPO/"
                    ota = OTAUpdater(SSID, PASSWORD, firmware_url, "main.py")
                    
                    client.send(b"HTTP/1.1 200 OK\r\n\r\nStarting OTA update...")
                    client.close()
                    time.sleep(1)
                    
                    # Update durchführen (führt zum Neustart)
                    ota.download_and_install_update_if_available()
                except Exception as e:
                    self.send_json(client, {"error": str(e)})
            elif path == "/reset":
                client.send(b"HTTP/1.1 200 OK\r\n\r\nReset...")
                client.close()
                time.sleep(1)
                reset()
            else:
                client.send(b"HTTP/1.1 404 Not Found\r\n\r\n404")
        except Exception as e:
            log_error("handle", str(e))
        finally:
            try:
                client.close()
            except:
                pass

# Globale Variablen
wifi = None
sensors = None
sensor_data = {}
fans = None

def sensor_loop():
    global sensor_data
    counter = 0
    
    while True:
        try:
            # Sensoren lesen
            data = sensors.read_all()
            date = format_datetime(localtime_with_offset())
            
            # Update global data
            sensor_data = {
                "date": date,
                "bme680_temp": data['temp'],
                "bme680_pressure": data['pres'],
                "bme680_humidity": data['hum'],
                "bme680_gas": data['gas'],
                "ccs811_co2": data['co2'],
                "ccs811_tvoc": data['tvoc'],
                "bh1750_lux": data['lux'],
                "vpd": data['vpd'],
                "vpd_status": data['vpd_status'],
                "moisture_sensor1": data['moisture1'],
                "moisture_sensor2": data['moisture2'],
                "moisture_average": data['moisture_avg'],
                "moisture_status": data['moisture_status']
            }
            
            # CSV schreiben
            write_csv(date, data)
            
            # Alle Messwerte ausgeben
            print("=" * 60)
            print(f"📊 SENSOR DATEN - {date}")
            print("=" * 60)
            print(f"🌡️  BME680 Temperatur:    {data['temp']:.1f} °C")
            print(f"🌊 BME680 Luftdruck:     {data['pres']:.1f} hPa")
            print(f"💧 BME680 Luftfeuchte:   {data['hum']:.1f} %")
            print(f"🔥 BME680 Gas-Widerstand: {data['gas']:.0f} Ω")
            print(f"💨 VPD (Dampfdruckdefizit): {data['vpd']:.3f} kPa ({data['vpd_status']})")
            print(f"🏭 CCS811 CO2:           {data['co2']} ppm")
            print(f"🌫️  CCS811 TVOC:          {data['tvoc']} ppb")
            print(f"💡 BH1750 Helligkeit:    {data['lux']:.1f} lux")
            print(f"🌱 Bodenfeuchtigkeit S1:  {data['moisture1']:.1f} %")
            print(f"🌱 Bodenfeuchtigkeit S2:  {data['moisture2']:.1f} %")
            print(f"🌱 Bodenfeuchtigkeit Ø:   {data['moisture_avg']:.1f} % ({data['moisture_status']})")
            
            # Ventilator-Status
            fan_speeds = fans.get_speeds()
            print(f"🌀 Umluft-Ventilator:     {fan_speeds['umluft']:.0f} %")
            print(f"💨 Abluft-Ventilator:     {fan_speeds['abluft']:.0f} %")
            
            # System-Metriken alle 5 Zyklen
            counter += 1
            if counter % 5 == 0:
                print("-" * 60)
                print("🖥️  SYSTEM METRIKEN")
                print("-" * 60)
                
                # Speicher-Info
                free_mem = gc.mem_free()
                alloc_mem = gc.mem_alloc()
                total_mem = free_mem + alloc_mem
                mem_usage = (alloc_mem / total_mem) * 100
                
                print(f"🧠 RAM Gesamt:           {total_mem:,} Bytes")
                print(f"💾 RAM Belegt:           {alloc_mem:,} Bytes ({mem_usage:.1f}%)")
                print(f"🆓 RAM Frei:             {free_mem:,} Bytes")
                
                # WiFi-Info
                rssi = wifi.wlan.status('rssi')
                ip = wifi.wlan.ifconfig()[0]
                mac = ':'.join(['{:02x}'.format(b) for b in wifi.wlan.config('mac')])
                
                print(f"📶 WiFi Signal:          {rssi} dBm")
                print(f"🌐 IP-Adresse:           {ip}")
                print(f"🔗 MAC-Adresse:          {mac}")
                
                # System-Info
                import machine
                freq = machine.freq()
                temp = machine.temperature() if hasattr(machine, 'temperature') else "N/A"
                
                print(f"⚡ CPU Frequenz:          {freq:,} Hz")
                if temp != "N/A":
                    print(f"🌡️  CPU Temperatur:        {temp:.1f} °C")
                
                # Uptime
                uptime_sec = time.ticks_ms() // 1000
                uptime_min = uptime_sec // 60
                uptime_hours = uptime_min // 60
                print(f"⏱️  Uptime:               {uptime_hours}h {uptime_min % 60}m {uptime_sec % 60}s")
                
                # Datei-Info
                try:
                    stat = os.stat('sensor_data.csv')
                    file_size = stat[6]  # Dateigröße
                    print(f"📁 CSV Dateigröße:        {file_size:,} Bytes")
                except:
                    print("📁 CSV Dateigröße:        Unbekannt")
                
                print(f"📈 Messung #{counter}")
            
            # Gelegentlich aufräumen
            if counter % 30 == 0:  # Öfter aufräumen
                print("\n🧹 System-Wartung...")
                cleanup_csv('sensor_data.csv', CONFIG['CSV_MAX_LINES'])
                gc.collect()
                print(f"✅ Garbage Collection durchgeführt - Free RAM: {gc.mem_free():,}")
                
        except Exception as e:
            log_error("sensor_loop", str(e))
            
        time.sleep(CONFIG['SENSOR_READ_INTERVAL'])

def check_for_ota_updates():
    """Prüft auf OTA-Updates beim Start"""
    try:
        print("Prüfe auf OTA-Updates...")
        firmware_url = "https://raw.githubusercontent.com/DEIN_USERNAME/DEIN_REPO/"
        ota_updater = OTAUpdater(SSID, PASSWORD, firmware_url, "main.py")
        ota_updater.download_and_install_update_if_available()
    except Exception as e:
        print(f"OTA-Update-Check fehlgeschlagen: {e}")
        # Fahre normal fort wenn Update fehlschlägt

def main():
    global wifi, sensors, sensor_data, fans
    
    print("ESP32-S3 FireBeetle 2 Sensor Station")
    print("=====================================")
    
    # Optional: OTA-Update Check beim Start
    # check_for_ota_updates()
    
    # Watchdog
    wdt = WDT(timeout=30000)
    
    # Status LED
    status_led = Pin(CONFIG['LED_PIN'], Pin.OUT)
    status_led.on()
    
    # WiFi
    wifi = WiFiManager(SSID, PASSWORD)
    if not wifi.connect():
        print("WiFi fehlgeschlagen - Neustart...")
        time.sleep(5)
        reset()
    
    status_led.off()
    time.sleep(0.5)
    status_led.on()
    
    # Zeit
    sync_time()
    
    # Ventilatoren initialisieren
    fans = FanController(
        CONFIG['FAN_PIN_UMLUFT'],
        CONFIG['FAN_PIN_ABLUFT'],
        CONFIG['FAN_PWM_FREQ']
    )
    print("Ventilatoren initialisiert")
    
    # I2C und Sensoren initialisieren
    try:
        i2c = I2C(0, scl=Pin(CONFIG['I2C_SCL_PIN']), sda=Pin(CONFIG['I2C_SDA_PIN']), 
                  freq=CONFIG['I2C_FREQ'])
        print(f"I2C initialisiert: SCL={CONFIG['I2C_SCL_PIN']}, SDA={CONFIG['I2C_SDA_PIN']}")
        
        # Teste I2C-Scan
        devices = i2c.scan()
        print(f"I2C Geräte gefunden: {[hex(d) for d in devices]}")
        
        mux = I2CMultiplexer(i2c)
        sensors = SensorManager(mux)
        sensors.init_sensors()
        
    except Exception as e:
        log_error("I2C Setup", str(e))
        reset()
    
    status_led.off()
    
    # CSV Header mit VPD und Bodenfeuchtigkeit
    try:
        with open('sensor_data.csv', 'r') as f:
            pass
    except:
        with open('sensor_data.csv', 'w') as f:
            f.write("date,temp,pressure,humidity,gas,co2,tvoc,lux,vpd,moisture1,moisture2,moisture_avg\n")
    
    # Sensor-Thread
    _thread.start_new_thread(sensor_loop, ())
    
    # Webserver
    server = WebServer()
    s = server.start()
    
    print("System bereit!")
    
    # Hauptschleife
    while True:
        try:
            wdt.feed()
            
            # WiFi-Überwachung
            if not wifi.is_connected():
                print("WiFi-Verbindung verloren - Neuverbindung...")
                wifi.connect()
            
            client, addr = s.accept()
            client.settimeout(3.0)  # Timeout für langsame Clients
            
            request = client.recv(1024).decode()
            
            if request:
                path = request.split(" ")[1] if len(request.split(" ")) > 1 else "/"
                server.handle(client, path, sensor_data)
            else:
                client.close()
                
        except OSError as e:
            # Socket-Timeout ist normal
            pass
        except Exception as e:
            log_error("main", str(e))
            try:
                client.close()
            except:
                pass

if __name__ == "__main__":
    main()
