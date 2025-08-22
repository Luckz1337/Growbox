# main.py - Korrigierte Version
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
import webrepl

# Lade Konfiguration aus separater Datei
try:
    from config import CONFIG
    print("✅ Konfiguration aus config.py geladen")
except ImportError:
    print("⚠️ config.py nicht gefunden, verwende Standard-Konfiguration")
CONFIG = {
    'I2C_SCL_PIN': 2,
    'I2C_SDA_PIN': 1,
    'I2C_FREQ': 100000,
    'LED_PIN': 21,
    'SENSOR_READ_INTERVAL': 30,
    'WIFI_TIMEOUT': 30,
    'MAX_RETRIES': 3,
    'CSV_MAX_LINES': 50000,
    'MEMORY_THRESHOLD': 50000,
    'MOISTURE_SENSOR1_PIN': 4,
    'MOISTURE_SENSOR2_PIN': 5,
    'MOISTURE_AIR_RAW1': 3131,
    'MOISTURE_WATER_RAW1': 1500,
    'MOISTURE_AIR_RAW2': 3131,
    'MOISTURE_WATER_RAW2': 1500,
    'FAN_PIN_UMLUFT': 9,
    'FAN_PIN_ABLUFT': 18,
    'FAN_PWM_FREQ': 250,
    'WDT_TIMEOUT': 180000,  # 3 Minuten für große Downloads
    'CHUNK_SIZE': 4096,  # Größere Chunks für Downloads
    'LOG_BUFFER_SIZE': 50,  # Anzahl der Log-Zeilen im Buffer
    }

def log_error(component, error):
    print(f"❌ [{component}] {error}")

def check_memory():
    free = gc.mem_free()
    if free < CONFIG['MEMORY_THRESHOLD']:
        gc.collect()
        return gc.mem_free()
    return free

def cleanup_csv(filename, max_lines):
    try:
        line_count = 0
        with open(filename, 'r') as f:
            for _ in f:
                line_count += 1
        
        if line_count > max_lines:
            lines = []
            with open(filename, 'r') as f:
                for line in f:
                    lines.append(line)
                    if len(lines) > max_lines:
                        lines.pop(0)
            
            with open(filename, 'w') as f:
                for line in lines:
                    f.write(line)
            print(f"📁 CSV auf {max_lines} Zeilen gekürzt")
    except Exception as e:
        log_error("CSV cleanup", str(e))

# URL-Dekodierung - bleibt gleich
def url_decode(encoded_str):
    if not encoded_str:
        return encoded_str
    
    replacements = {
        '%20': ' ', '+': ' ', '%2C': ',', '%3D': '=', '%26': '&',
        '%3F': '?', '%23': '#', '%2F': '/', '%3A': ':', '%3B': ';',
        '%40': '@', '%21': '!', '%24': '$', '%27': "'", '%28': '(',
        '%29': ')', '%2A': '*', '%2B': '+', '%2D': '-', '%2E': '.',
        '%5F': '_', '%7E': '~', '%C3%A4': 'ä', '%C3%B6': 'ö',
        '%C3%BC': 'ü', '%C3%84': 'Ä', '%C3%96': 'Ö', '%C3%9C': 'Ü',
        '%C3%9F': 'ß',
    }
    
    decoded = encoded_str
    for encoded, decoded_char in replacements.items():
        decoded = decoded.replace(encoded, decoded_char)
    
    return decoded

# VPD Berechnung - bleibt gleich
def calculate_vpd(temp_c, humidity_percent):
    try:
        svp = 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
        avp = svp * (humidity_percent / 100.0)
        vpd = svp - avp
        return round(vpd, 3)
    except:
        return 0

def get_vpd_status(vpd):
    if 0.8 <= vpd <= 1.2:
        return "optimal"
    elif 0.4 <= vpd <= 1.6:
        return "warning"
    else:
        return "critical"

def get_moisture_status(moisture_pct):
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
            if self.wlan.status() == 1010:  # STAT_GOT_IP für ESP32-S3
                print(f'📶 WiFi verbunden: {self.wlan.ifconfig()[0]}')
                return True
            time.sleep(1)
        return False
    
    def is_connected(self):
        return self.wlan.status() == 1010

# Zeit-Funktionen - bleiben gleich
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
        print("🕒 Zeit synchronisiert:", format_datetime(localtime_with_offset()))
        return True
    except:
        return False

# 🔧 KORRIGIERTER I2C MULTIPLEXER
class I2CMultiplexer:
    def __init__(self, i2c, address=0x70):
        self.i2c = i2c
        self.address = address
        self.current_channel = None
        
        # Teste ob Multiplexer verfügbar ist
        devices = i2c.scan()
        if address not in devices:
            print(f"⚠️ TCA9548A Multiplexer nicht gefunden bei 0x{address:02x}")
            print(f"Gefundene I2C-Geräte: {[hex(d) for d in devices]}")
            self.available = False
        else:
            print(f"✅ TCA9548A Multiplexer gefunden bei 0x{address:02x}")
            self.available = True

    def select(self, channel):
        if not self.available:
            print(f"⚠️ Multiplexer nicht verfügbar - verwende direkten I2C")
            return
            
        if self.current_channel != channel:
            try:
                # Kanal aktivieren: Bit-Maske senden
                self.i2c.writeto(self.address, bytearray([1 << channel]))
                self.current_channel = channel
                time.sleep(0.1)  # Längere Wartezeit für Stabilität
                print(f"🔄 I2C Kanal {channel} aktiviert")
            except Exception as e:
                log_error("I2C Mux", f"Kanal {channel}: {str(e)}")
                self.available = False

# 🌱 KORRIGIERTER MOISTURE SENSOR
class MoistureSensor:
    def __init__(self, pin1, pin2, air_raw1, water_raw1, air_raw2, water_raw2):
        try:
            self.adc1 = ADC(Pin(pin1))
            self.adc2 = ADC(Pin(pin2))
            
            # Konfiguration wie in funktionierenden Tests
            for adc in (self.adc1, self.adc2):
                adc.atten(ADC.ATTN_11DB)    # bis ~3,6 V
                adc.width(ADC.WIDTH_12BIT)  # 0–4095
            
            self.air_raw1 = air_raw1
            self.water_raw1 = water_raw1
            self.air_raw2 = air_raw2
            self.water_raw2 = water_raw2
            
            print(f"🌱 Bodenfeuchtigkeitssensoren initialisiert (Pins {pin1}, {pin2})")
            
        except Exception as e:
            log_error("MoistureSensor", str(e))
            raise
    
    def calc_pct(self, raw, air, water):
        pct = (air - raw) * 100 / (air - water)
        return max(0, min(100, pct))
    
    def read(self):
        try:
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
        except Exception as e:
            log_error("MoistureSensor read", str(e))
            return {'raw1': 0, 'raw2': 0, 'pct1': 0, 'pct2': 0, 'avg': 0}

# FanController - bleibt größtenteils gleich, nur kleine Fixes
class FanController:
    def __init__(self, pin_umluft, pin_abluft, pwm_freq):
        try:
            # PWM mit korrekter Methode initialisieren
            self.fan_umluft = PWM(Pin(pin_umluft))
            self.fan_abluft = PWM(Pin(pin_abluft))
            self.fan_umluft.freq(pwm_freq)
            self.fan_abluft.freq(pwm_freq)
            
            self.umluft_speed = 0.0
            self.abluft_speed = 0.0
            
            self.settings_file = 'fan_settings.json'
            self.schedule_file = 'fan_schedule.json'
            
            self.load_settings()
            self.schedule = self.load_schedule()
            
            # Setze auf gespeicherte Werte
            self.set_umluft_speed(self.umluft_speed, save=False)
            self.set_abluft_speed(self.abluft_speed, save=False)
            
            print(f"💨 Ventilatoren initialisiert: Umluft {self.umluft_speed}%, Abluft {self.abluft_speed}%")
            
        except Exception as e:
            log_error("FanController", str(e))
            raise
    
    def save_settings(self):
        try:
            settings = {
                'umluft_speed': self.umluft_speed,
                'abluft_speed': self.abluft_speed,
                'last_updated': format_datetime(localtime_with_offset())
            }
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            log_error("save_settings", str(e))
    
    def load_settings(self):
        try:
            with open(self.settings_file, 'r') as f:
                settings = json.load(f)
                self.umluft_speed = settings.get('umluft_speed', 0.0)
                self.abluft_speed = settings.get('abluft_speed', 0.0)
        except Exception as e:
            self.umluft_speed = 0.0
            self.abluft_speed = 0.0
    
    def load_schedule(self):
        try:
            with open(self.schedule_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            return []
    
    def save_schedule(self, schedule):
        try:
            with open(self.schedule_file, 'w') as f:
                json.dump(schedule, f)
            self.schedule = schedule
            return True
        except Exception as e:
            log_error("save_schedule", str(e))
            return False
    
    def set_umluft_speed(self, percent, save=True):
        if not 0 <= percent <= 100:
            raise ValueError("percent muss zwischen 0 und 100 liegen")
        self.umluft_speed = percent
        # ESP32-S3 verwendet duty_u16 (0-65535)
        duty = int(percent / 100 * 65535)
        self.fan_umluft.duty_u16(duty)
        if save:
            self.save_settings()
    
    def set_abluft_speed(self, percent, save=True):
        if not 0 <= percent <= 100:
            raise ValueError("percent muss zwischen 0 und 100 liegen")
        self.abluft_speed = percent
        duty = int(percent / 100 * 65535)
        self.fan_abluft.duty_u16(duty)
        if save:
            self.save_settings()
    
    def get_speeds(self):
        return {
            'umluft': self.umluft_speed,
            'abluft': self.abluft_speed
        }
    
    # Zeitplan-Methoden bleiben gleich...
    def check_schedule(self):
        if not self.schedule:
            return False
        
        try:
            current_time = localtime_with_offset()
            current_hour = current_time[3]
            current_minute = current_time[4]
            current_weekday = current_time[6]
            
            for rule in self.schedule:
                if not rule.get('enabled', True):
                    continue
                
                if 'weekdays' in rule and current_weekday not in rule['weekdays']:
                    continue
                
                start_hour = rule.get('start_hour', 0)
                start_minute = rule.get('start_minute', 0)
                end_hour = rule.get('end_hour', 23)
                end_minute = rule.get('end_minute', 59)
                
                current_minutes = current_hour * 60 + current_minute
                start_minutes = start_hour * 60 + start_minute
                end_minutes = end_hour * 60 + end_minute
                
                if start_minutes > end_minutes:
                    time_match = current_minutes >= start_minutes or current_minutes <= end_minutes
                else:
                    time_match = start_minutes <= current_minutes <= end_minutes
                
                if time_match:
                    umluft_speed = rule.get('umluft_speed', self.umluft_speed)
                    abluft_speed = rule.get('abluft_speed', self.abluft_speed)
                    
                    if umluft_speed != self.umluft_speed or abluft_speed != self.abluft_speed:
                        print(f"🕒 Zeitplan aktiv: '{rule.get('name', 'Unbenannt')}' - Umluft: {umluft_speed}%, Abluft: {abluft_speed}%")
                        self.set_umluft_speed(umluft_speed)
                        self.set_abluft_speed(abluft_speed)
                        return True
                    
            return False
        except Exception as e:
            log_error("check_schedule", str(e))
            return False

# 🔧 KORRIGIERTER SENSOR MANAGER
class SensorManager:
    def __init__(self, mux):
        self.mux = mux
        self.sensors = {}
        self.last = {}
        self.status_led = None

    def init_sensors(self):
        print("🔧 Initialisiere Sensoren...")
        
        # Status LED
        try:
            self.status_led = Pin(CONFIG['LED_PIN'], Pin.OUT)
            self.status_led.on()
            time.sleep(0.1)
            self.status_led.off()
        except Exception as e:
            log_error("Status LED", str(e))
        
        # 📊 CCS811 (Kanal 0)
        try:
            print("Initialisiere CCS811 auf Kanal 0...")
            self.mux.select(0)
            time.sleep(0.2)  # Längere Wartezeit
            
            # Prüfe ob CCS811 verfügbar ist
            devices = self.mux.i2c.scan()
            if 0x5A in devices:
                self.sensors['ccs811'] = CCS811.CCS811(i2c=self.mux.i2c, addr=0x5A)
                print("✅ CCS811 initialisiert")
            else:
                print(f"⚠️ CCS811 nicht gefunden. Verfügbare Geräte: {[hex(d) for d in devices]}")
                
        except Exception as e:
            log_error("CCS811 init", str(e))
            
        # 🌡️ BME680 (Kanal 1)
        try:
            print("Initialisiere BME680 auf Kanal 1...")
            self.mux.select(1)
            time.sleep(0.2)
            
            devices = self.mux.i2c.scan()
            if 0x77 in devices:
                self.sensors['bme680'] = bme680.BME680_I2C(i2c=self.mux.i2c, address=0x77)
                print("✅ BME680 initialisiert")
            else:
                print(f"⚠️ BME680 nicht gefunden. Verfügbare Geräte: {[hex(d) for d in devices]}")
                
        except Exception as e:
            log_error("BME680 init", str(e))
            
        # 💡 BH1750 (Kanal 2)
        try:
            print("Initialisiere BH1750 auf Kanal 2...")
            self.mux.select(2)
            time.sleep(0.2)
            
            devices = self.mux.i2c.scan()
            if 0x23 in devices:
                self.sensors['bh1750'] = bh1750.BH1750(self.mux.i2c)
                print("✅ BH1750 initialisiert")
            else:
                print(f"⚠️ BH1750 nicht gefunden. Verfügbare Geräte: {[hex(d) for d in devices]}")
                
        except Exception as e:
            log_error("BH1750 init", str(e))
        
        # 🌱 Bodenfeuchtigkeitssensor
        try:
            self.sensors['moisture'] = MoistureSensor(
                CONFIG['MOISTURE_SENSOR1_PIN'],
                CONFIG['MOISTURE_SENSOR2_PIN'],
                CONFIG['MOISTURE_AIR_RAW1'],
                CONFIG['MOISTURE_WATER_RAW1'],
                CONFIG['MOISTURE_AIR_RAW2'],
                CONFIG['MOISTURE_WATER_RAW2']
            )
        except Exception as e:
            log_error("Moisture init", str(e))
        
        print(f"📊 Sensor-Initialisierung abgeschlossen. Aktive Sensoren: {list(self.sensors.keys())}")

    def read_all(self):
        data = {}
        
        # 🌡️ BME680 lesen
        if 'bme680' in self.sensors:
            try:
                self.mux.select(1)
                time.sleep(0.1)  # Kurze Wartezeit
                s = self.sensors['bme680']
                data['temp'] = s.temperature
                data['pres'] = s.pressure
                data['hum'] = s.humidity
                data['gas'] = s.gas
                data['vpd'] = calculate_vpd(data['temp'], data['hum'])
                data['vpd_status'] = get_vpd_status(data['vpd'])
                self.last['bme680'] = (data['temp'], data['pres'], data['hum'], data['gas'], data['vpd'])
            except Exception as e:
                log_error("BME680 read", str(e))
                if 'bme680' in self.last:
                    data['temp'], data['pres'], data['hum'], data['gas'], data['vpd'] = self.last['bme680']
                    data['vpd_status'] = get_vpd_status(data['vpd'])
                else:
                    data['temp'] = data['pres'] = data['hum'] = data['gas'] = data['vpd'] = 0
                    data['vpd_status'] = "unknown"
        else:
            data['temp'] = data['pres'] = data['hum'] = data['gas'] = data['vpd'] = 0
            data['vpd_status'] = "unknown"
        
        # 📊 CCS811 lesen
        if 'ccs811' in self.sensors:
            try:
                self.mux.select(0)
                time.sleep(0.1)
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
        
        # 💡 BH1750 lesen
        if 'bh1750' in self.sensors:
            try:
                self.mux.select(2)
                time.sleep(0.1)
                data['lux'] = self.sensors['bh1750'].luminance(bh1750.BH1750.CONT_HIRES_1)
                self.last['bh1750'] = data['lux']
            except Exception as e:
                log_error("BH1750 read", str(e))
                data['lux'] = self.last.get('bh1750', 0)
        else:
            data['lux'] = 0
        
        # 🌱 Bodenfeuchtigkeit lesen
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

# CSV-Schreibfunktion bleibt gleich
def write_csv(date, data):
    try:
        with open('sensor_data.csv', 'a') as f:
            f.write(f"{date},{data['temp']},{data['pres']},{data['hum']},{data['gas']},{data['co2']},{data['tvoc']},{data['lux']},{data['vpd']},{data['moisture1']},{data['moisture2']},{data['moisture_avg']}\n")
    except Exception as e:
        log_error("CSV write", str(e))

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
        print('🌐 Webserver gestartet auf Port 80')
        return self.server

    def send_file_chunked(self, client, filename, content_type):
        try:
            headers = f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nTransfer-Encoding: chunked\r\n\r\n"
            client.send(headers.encode())
            
            with open(filename, 'rb') as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    
                    size = hex(len(chunk))[2:]
                    client.send(f"{size}\r\n".encode())
                    client.send(chunk)
                    client.send(b"\r\n")
                    
                    time.sleep(0.01)
                    gc.collect()
                
                client.send(b"0\r\n\r\n")
                
        except Exception as e:
            log_error("send_file", str(e))

    def send_json(self, client, data):
        try:
            response = json.dumps(data)
            headers = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: {len(response)}\r\n\r\n"
            client.send(headers.encode() + response.encode())
        except Exception as e:
            log_error("send_json", str(e))
            error_response = '{"error": "Internal server error"}'
            headers = f"HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\nContent-Length: {len(error_response)}\r\n\r\n"
            client.send(headers.encode() + error_response.encode())

    def send_history(self, client):
        try:
            headers = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
            client.send(headers.encode())
            
            client.send(b"2\r\n[\r\n")
            
            first = True
            
            with open('sensor_data.csv', 'r') as f:
                f.readline()  # Skip header
                
                lines = []
                for line in f:
                    lines.append(line)
                
                for line in lines[-50:]:
                    parts = line.strip().split(",")
                    if len(parts) >= 8:
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
                            
                            if len(parts) > 8:
                                entry["vpd"] = float(parts[8])
                            else:
                                entry["vpd"] = calculate_vpd(entry["bme680_temp"], entry["bme680_humidity"])
                            
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
            
            client.send(b"2\r\n]\r\n")
            client.send(b"0\r\n\r\n")
            
        except Exception as e:
            log_error("send_history", str(e))

    def parse_schedule_params(self, params):
        try:
            param_dict = {}
            
            for param in params.split("&"):
                if "=" in param:
                    key, value = param.split("=", 1)
                    decoded_value = url_decode(value)
                    param_dict[key] = decoded_value
            
            required = ['name', 'start_hour', 'start_minute', 'end_hour', 'end_minute', 'umluft_speed', 'abluft_speed']
            for req in required:
                if req not in param_dict:
                    return None
            
            try:
                rule = {
                    'name': str(param_dict['name']),
                    'start_hour': int(param_dict['start_hour']),
                    'start_minute': int(param_dict['start_minute']),
                    'end_hour': int(param_dict['end_hour']),
                    'end_minute': int(param_dict['end_minute']),
                    'umluft_speed': float(param_dict['umluft_speed']),
                    'abluft_speed': float(param_dict['abluft_speed']),
                    'enabled': param_dict.get('enabled', 'true').lower() == 'true',
                    'created': format_datetime(localtime_with_offset())
                }
                
            except ValueError as e:
                return None
            
            if 'weekdays' in param_dict and param_dict['weekdays']:
                weekdays = []
                weekday_str = param_dict['weekdays']
                
                for day_str in weekday_str.split(','):
                    day_str = day_str.strip()
                    if day_str:
                        try:
                            day = int(day_str)
                            if 0 <= day <= 6:
                                weekdays.append(day)
                            else:
                                return None
                        except ValueError:
                            return None
                
                if weekdays:
                    rule['weekdays'] = weekdays
                else:
                    return None
            else:
                rule['weekdays'] = [0, 1, 2, 3, 4, 5, 6]
            
            return rule
            
        except Exception as e:
            log_error("parse_schedule_params", str(e))
            return None

    def handle(self, client, path, sensor_data):
        try:
            if path == "/" or path == "/index.html":
                self.send_file_chunked(client, "index.html", "text/html")
            elif path == "/api/sensordata":
                self.send_json(client, sensor_data)
            elif path == "/api/history":
                self.send_history(client)
            elif path == "/api/status":
                free_mem = gc.mem_free()
                alloc_mem = gc.mem_alloc()
                total_mem = free_mem + alloc_mem
                mem_usage = (alloc_mem / total_mem) * 100
                
                rssi = wifi.wlan.status('rssi')
                ip_config = wifi.wlan.ifconfig()
                mac = ':'.join(['{:02x}'.format(b) for b in wifi.wlan.config('mac')])
                
                import machine
                freq = machine.freq()
                uptime_sec = time.ticks_ms() // 1000
                
                csv_size = 0
                csv_lines = 0
                try:
                    stat = os.stat('sensor_data.csv')
                    csv_size = stat[6]
                    with open('sensor_data.csv', 'r') as f:
                        csv_lines = sum(1 for _ in f) - 1
                except:
                    pass
                
                status = {
                    "memory": {
                        "total": total_mem,
                        "free": free_mem,
                        "allocated": alloc_mem,
                        "usage_percent": round(mem_usage, 1)
                    },
                    "wifi": {
                        "rssi": rssi,
                        "signal_quality": "Exzellent" if rssi > -50 else "Sehr gut" if rssi > -60 else "Gut" if rssi > -70 else "Schwach",
                        "ip_address": ip_config[0],
                        "subnet": ip_config[1],
                        "gateway": ip_config[2],
                        "dns": ip_config[3],
                        "mac_address": mac
                    },
                    "system": {
                        "chip": "ESP32-S3",
                        "cpu_freq": freq,
                        "uptime_seconds": uptime_sec,
                        "uptime_formatted": f"{uptime_sec//3600}h {(uptime_sec%3600)//60}m {uptime_sec%60}s"
                    },
                    "data": {
                        "csv_size_bytes": csv_size,
                        "csv_lines": csv_lines,
                        "sensor_interval": CONFIG['SENSOR_READ_INTERVAL']
                    },
                    "timestamp": format_datetime(localtime_with_offset())
                }
                self.send_json(client, status)
            elif path == "/api/fans":
                fan_status = fans.get_speeds()
                self.send_json(client, fan_status)
            elif path.startswith("/api/fans/set"):
                try:
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
            
            # Zeitplan-Endpunkte
            elif path == "/api/schedule":
                schedule_data = {
                    "schedule": fans.schedule,
                    "current_settings": fans.get_speeds(),
                    "current_time": format_datetime(localtime_with_offset())
                }
                self.send_json(client, schedule_data)
                
            elif path.startswith("/api/schedule/add"):
                try:
                    if "?" in path:
                        params = path.split("?")[1]
                        rule = self.parse_schedule_params(params)
                        
                        if rule:
                            fans.schedule.append(rule)
                            if fans.save_schedule(fans.schedule):
                                response = {
                                    "status": "success",
                                    "message": "Zeitplan-Regel hinzugefügt",
                                    "schedule": fans.schedule
                                }
                            else:
                                response = {"status": "error", "message": "Fehler beim Speichern"}
                        else:
                            response = {"status": "error", "message": "Ungültige Parameter"}
                    else:
                        response = {"status": "error", "message": "Keine Parameter"}
                    
                    self.send_json(client, response)
                except Exception as e:
                    self.send_json(client, {"status": "error", "message": str(e)})
                    
            elif path.startswith("/api/schedule/delete"):
                try:
                    if "?" in path:
                        params = path.split("?")[1]
                        param_dict = {}
                        for param in params.split("&"):
                            if "=" in param:
                                key, value = param.split("=", 1)
                                param_dict[key] = value
                        
                        rule_id = int(param_dict.get("id", -1))
                        if 0 <= rule_id < len(fans.schedule):
                            deleted_rule = fans.schedule.pop(rule_id)
                            fans.save_schedule(fans.schedule)
                            response = {
                                "status": "success",
                                "message": f"Regel '{deleted_rule.get('name', 'Unbenannt')}' gelöscht",
                                "schedule": fans.schedule
                            }
                        else:
                            response = {"status": "error", "message": "Ungültige Regel-ID"}
                    else:
                        response = {"status": "error", "message": "Keine Parameter"}
                    
                    self.send_json(client, response)
                except Exception as e:
                    self.send_json(client, {"status": "error", "message": str(e)})
                    
            elif path.startswith("/api/schedule/toggle"):
                try:
                    if "?" in path:
                        params = path.split("?")[1]
                        param_dict = {}
                        for param in params.split("&"):
                            if "=" in param:
                                key, value = param.split("=", 1)
                                param_dict[key] = value
                        
                        rule_id = int(param_dict.get("id", -1))
                        if 0 <= rule_id < len(fans.schedule):
                            rule = fans.schedule[rule_id]
                            rule['enabled'] = not rule.get('enabled', True)
                            fans.save_schedule(fans.schedule)
                            status = "aktiviert" if rule['enabled'] else "deaktiviert"
                            response = {
                                "status": "success",
                                "message": f"Regel '{rule.get('name', 'Unbenannt')}' {status}",
                                "schedule": fans.schedule
                            }
                        else:
                            response = {"status": "error", "message": "Ungültige Regel-ID"}
                    else:
                        response = {"status": "error", "message": "Keine Parameter"}
                    
                    self.send_json(client, response)
                except Exception as e:
                    self.send_json(client, {"status": "error", "message": str(e)})
                    
            elif path == "/api/schedule/clear":
                fans.schedule = []
                fans.save_schedule(fans.schedule)
                response = {
                    "status": "success",
                    "message": "Alle Zeitplan-Regeln gelöscht",
                    "schedule": fans.schedule
                }
                self.send_json(client, response)
            
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
            print(f"📊 Sensor-Lesung #{counter + 1}")
            
            # Sensoren lesen mit Fehlerbehandlung
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
            
            # Zeitplan überprüfen (alle 60 Sekunden)
            if counter % 6 == 0:
                try:
                    schedule_applied = fans.check_schedule()
                    if schedule_applied:
                        print("🕒 Zeitplan-Regel angewendet")
                except Exception as e:
                    log_error("schedule_check", str(e))
            
            # Kompakte Ausgabe der wichtigsten Werte
            if counter % 3 == 0:  # Alle 30 Sekunden ausführlich
                print("=" * 60)
                print(f"📊 SENSOR DATEN - {date}")
                print("=" * 60)
                print(f"🌡️  Temperatur: {data['temp']:.1f}°C | 💧 Luftfeuchte: {data['hum']:.1f}%")
                print(f"🌊 Luftdruck: {data['pres']:.1f}hPa | 💨 VPD: {data['vpd']:.3f}kPa ({data['vpd_status']})")
                print(f"🏭 CO2: {data['co2']}ppm | 🌫️  TVOC: {data['tvoc']}ppb")
                print(f"💡 Licht: {data['lux']:.1f}lux | 🌱 Bodenfeuchtigkeit: {data['moisture_avg']:.1f}% ({data['moisture_status']})")
                
                fan_speeds = fans.get_speeds()
                print(f"🌀 Umluft: {fan_speeds['umluft']:.0f}% | 💨 Abluft: {fan_speeds['abluft']:.0f}%")
            else:
                # Kurze Ausgabe
                print(f"📊 T:{data['temp']:.1f}°C H:{data['hum']:.1f}% CO2:{data['co2']}ppm VPD:{data['vpd']:.2f}kPa Soil:{data['moisture_avg']:.1f}%")
            
            # Memory-Check alle 10 Zyklen
            counter += 1
            if counter % 10 == 0:
                free_mem = gc.mem_free()
                total_mem = free_mem + gc.mem_alloc()
                mem_usage = (gc.mem_alloc() / total_mem) * 100
                
                print(f"💾 Speicher: {free_mem:,}B frei ({100-mem_usage:.1f}% verfügbar)")
                
                if free_mem < CONFIG['MEMORY_THRESHOLD']:
                    print("⚠️ Speicher knapp - führe Garbage Collection durch")
                    gc.collect()
                    print(f"✅ Nach GC: {gc.mem_free():,}B frei")
            
            # CSV aufräumen alle 30 Zyklen
            if counter % 30 == 0:
                print("🧹 CSV-Wartung...")
                cleanup_csv('sensor_data.csv', CONFIG['CSV_MAX_LINES'])
                gc.collect()
                
        except Exception as e:
            log_error("sensor_loop", str(e))
            print(f"❌ Sensor-Loop Fehler: {e}")
            
        time.sleep(CONFIG['SENSOR_READ_INTERVAL'])

def main():
    global wifi, sensors, sensor_data, fans
    
    print("🚀 ESP32-S3 FireBeetle 2 Sensor Station")
    print("=" * 60)
    
    # Watchdog
    try:
        wdt = WDT(timeout=300000)
        print("✅ Watchdog aktiviert (5min)")
    except:
        print("⚠️ Watchdog konnte nicht aktiviert werden")
        wdt = None
    
    # Status LED
    try:
        status_led = Pin(CONFIG['LED_PIN'], Pin.OUT)
        status_led.on()
        print("✅ Status LED aktiviert")
    except Exception as e:
        print(f"⚠️ Status LED Fehler: {e}")
        status_led = None
    
    # Memory Check vor WiFi
    gc.collect()
    initial_free_mem = gc.mem_free()
    print(f"💾 Verfügbarer Speicher: {initial_free_mem:,} bytes")
    
    if initial_free_mem < 100000:  # Weniger als 100KB
        print("⚠️ WARNUNG: Wenig Speicher verfügbar!")
    
    # WiFi-Verbindung
    print("📶 Stelle WiFi-Verbindung her...")
    wifi = WiFiManager(SSID, PASSWORD)
    if not wifi.connect():
        print("❌ WiFi-Verbindung fehlgeschlagen - Neustart...")
        time.sleep(5)
        reset()
    
    if status_led:
        status_led.off()
        time.sleep(0.5)
        status_led.on()
    
    # Zeit synchronisieren
    print("🕒 Synchronisiere Zeit...")
    if sync_time():
        print("✅ Zeit erfolgreich synchronisiert")
    else:
        print("⚠️ Zeit-Synchronisation fehlgeschlagen - verwende lokale Zeit")
    
    # WebREPL aktivieren
    print("🌐 Aktiviere WebREPL...")
    try:
        try:
            with open('webrepl_cfg.py', 'w') as f:
                f.write("PASS = ''\n")
        except:
            pass
        
        import webrepl
        webrepl.start()
        print("✅ WebREPL aktiviert")
        print(f"🔗 WebREPL URL: ws://{wifi.wlan.ifconfig()[0]}:8266")
        print("⚠️ KEIN PASSWORT gesetzt!")
    except Exception as e:
        print(f"❌ WebREPL Fehler: {e}")
    
    time.sleep(2)  # WebREPL stabilisieren
    
    # Ventilatoren initialisieren
    print("💨 Initialisiere Ventilatoren...")
    try:
        fans = FanController(
            CONFIG['FAN_PIN_UMLUFT'],
            CONFIG['FAN_PIN_ABLUFT'],
            CONFIG['FAN_PWM_FREQ']
        )
        print("✅ Ventilatoren initialisiert")
    except Exception as e:
        log_error("FanController", str(e))
        print("❌ Ventilator-Initialisierung fehlgeschlagen - Neustart...")
        reset()
    
    # I2C und Sensoren initialisieren
    print("🔧 Initialisiere I2C und Sensoren...")
    try:
        # I2C mit erweiterten Parametern
        i2c = I2C(0, 
                  scl=Pin(CONFIG['I2C_SCL_PIN']), 
                  sda=Pin(CONFIG['I2C_SDA_PIN']), 
                  freq=CONFIG['I2C_FREQ'])
        print(f"✅ I2C initialisiert: SCL={CONFIG['I2C_SCL_PIN']}, SDA={CONFIG['I2C_SDA_PIN']}")
        
        # I2C-Scan durchführen
        print("🔍 Scanne I2C-Bus...")
        devices = i2c.scan()
        print(f"📡 Gefundene I2C-Geräte: {[hex(d) for d in devices]}")
        
        if not devices:
            print("❌ Keine I2C-Geräte gefunden!")
            print("🔧 Überprüfe:")
            print("   - I2C Verkabelung (SDA/SCL)")
            print("   - Stromversorgung der Sensoren")
            print("   - Pull-up Widerstände")
            # Trotzdem fortfahren für Demo-Zwecke
        
        # Multiplexer initialisieren
        mux = I2CMultiplexer(i2c)
        
        # Sensor Manager
        sensors = SensorManager(mux)
        sensors.init_sensors()
        
        print(f"✅ Sensor-System initialisiert")
        
    except Exception as e:
        log_error("I2C/Sensor Setup", str(e))
        print("❌ Sensor-Initialisierung fehlgeschlagen!")
        print("🔄 Versuche mit minimaler Konfiguration...")
        
        # Fallback: Nur Bodenfeuchtigkeitssensoren
        try:
            class MinimalSensorManager:
                def __init__(self):
                    self.sensors = {}
                    self.last = {}
                    try:
                        self.sensors['moisture'] = MoistureSensor(
                            CONFIG['MOISTURE_SENSOR1_PIN'],
                            CONFIG['MOISTURE_SENSOR2_PIN'],
                            CONFIG['MOISTURE_AIR_RAW1'],
                            CONFIG['MOISTURE_WATER_RAW1'],
                            CONFIG['MOISTURE_AIR_RAW2'],
                            CONFIG['MOISTURE_WATER_RAW2']
                        )
                        print("✅ Minimal-Setup: Nur Bodenfeuchtigkeit")
                    except:
                        print("❌ Auch Minimal-Setup fehlgeschlagen")
                
                def read_all(self):
                    data = {
                        'temp': 20.0, 'pres': 1013.25, 'hum': 50.0, 'gas': 50000,
                        'co2': 400, 'tvoc': 0, 'lux': 100.0,
                        'vpd': 0.8, 'vpd_status': 'simulated',
                        'moisture1': 0, 'moisture2': 0, 'moisture_avg': 0,
                        'moisture_status': 'unknown'
                    }
                    
                    if 'moisture' in self.sensors:
                        try:
                            moisture_data = self.sensors['moisture'].read()
                            data['moisture1'] = moisture_data['pct1']
                            data['moisture2'] = moisture_data['pct2']
                            data['moisture_avg'] = moisture_data['avg']
                            data['moisture_status'] = get_moisture_status(moisture_data['avg'])
                        except:
                            pass
                    
                    return data
            
            sensors = MinimalSensorManager()
            print("⚠️ Verwende Minimal-Sensor-Setup (hauptsächlich simulierte Daten)")
            
        except Exception as e2:
            log_error("Minimal Setup", str(e2))
            print("❌ Kritischer Fehler - Neustart...")
            reset()
    
    if status_led:
        status_led.off()
    
    # CSV-Header erstellen
    print("📁 Initialisiere Datenlogging...")
    try:
        with open('sensor_data.csv', 'r') as f:
            print("✅ CSV-Datei existiert bereits")
    except:
        print("📝 Erstelle neue CSV-Datei...")
        with open('sensor_data.csv', 'w') as f:
            f.write("date,temp,pressure,humidity,gas,co2,tvoc,lux,vpd,moisture1,moisture2,moisture_avg\n")
        print("✅ CSV-Header erstellt")
    
    # Sensor-Thread starten
    print("🧵 Starte Sensor-Thread...")
    try:
        _thread.start_new_thread(sensor_loop, ())
        print("✅ Sensor-Thread gestartet")
    except Exception as e:
        log_error("Sensor Thread", str(e))
        print("❌ Sensor-Thread konnte nicht gestartet werden")
    
    # Webserver starten
    print("🌐 Starte Webserver...")
    try:
        server = WebServer()
        s = server.start()
        print("✅ Webserver erfolgreich gestartet")
    except Exception as e:
        log_error("Webserver", str(e))
        print("❌ Webserver konnte nicht gestartet werden - Neustart...")
        reset()
    
    # Startup abgeschlossen
    print("\n" + "🎉" * 20)
    print("✅ SYSTEM BEREIT!")
    print("🎉" * 20)
    print(f"🌐 Dashboard: http://{wifi.wlan.ifconfig()[0]}")
    print(f"🔗 WebREPL: ws://{wifi.wlan.ifconfig()[0]}:8266")
    print(f"💾 Freier Speicher: {gc.mem_free():,} bytes")
    print("=" * 60)
    
    # Hauptschleife
    request_count = 0
    last_memory_check = time.ticks_ms()
    
    while True:
        try:
            # Watchdog füttern
            if wdt:
                wdt.feed()
            
            # WiFi-Status prüfen (alle 30 Sekunden)
            if request_count % 30 == 0:
                if not wifi.is_connected():
                    print("📶 WiFi-Verbindung verloren - Neuverbindung...")
                    if not wifi.connect():
                        print("❌ WiFi-Wiederverbindung fehlgeschlagen - Neustart...")
                        reset()
            
            # Memory-Check alle 5 Minuten
            current_time = time.ticks_ms()
            if time.ticks_diff(current_time, last_memory_check) > 300000:  # 5 Minuten
                free_mem = gc.mem_free()
                if free_mem < CONFIG['MEMORY_THRESHOLD']:
                    print(f"⚠️ Speicher knapp: {free_mem:,}B - Garbage Collection...")
                    gc.collect()
                    print(f"✅ Nach GC: {gc.mem_free():,}B")
                last_memory_check = current_time
            
            # Warte auf HTTP-Request
            try:
                client, addr = s.accept()
                client.settimeout(5.0)  # 5 Sekunden Timeout
                
                request_count += 1
                
                # Request lesen
                request = client.recv(1024).decode()
                
                if request:
                    # HTTP-Methode und Pfad extrahieren
                    lines = request.split('\n')
                    if lines:
                        first_line = lines[0]
                        parts = first_line.split(' ')
                        if len(parts) >= 2:
                            method = parts[0]
                            path = parts[1]
                            
                            # Nur GET-Requests verarbeiten
                            if method == 'GET':
                                if request_count % 50 == 0:  # Nur jeden 50. Request loggen
                                    print(f"🌐 Request #{request_count}: {path}")
                                server.handle(client, path, sensor_data)
                            else:
                                client.send(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                                client.close()
                        else:
                            client.close()
                    else:
                        client.close()
                else:
                    client.close()
                    
            except OSError as e:
                # Socket-Timeout ist normal
                if e.args[0] != 110:  # ETIMEDOUT
                    pass
            except Exception as e:
                log_error("Main Loop Request", str(e))
                try:
                    client.close()
                except:
                    pass
                
        except KeyboardInterrupt:
            print("\n🛑 Programm durch Benutzer beendet")
            break
        except Exception as e:
            log_error("Main Loop", str(e))
            print(f"❌ Kritischer Fehler in Hauptschleife: {e}")
            time.sleep(5)  # Kurze Pause vor Neustart
            reset()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ KRITISCHER STARTUP-FEHLER: {e}")
        import sys
        sys.print_exception(e)
        print("🔄 Neustart in 10 Sekunden...")
        time.sleep(10)
        reset()

