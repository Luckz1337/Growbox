import time
import network

STAT_GOT_IP = 1010  # network.STAT_GOT_IP on ESP32-S3 ports


class WiFiManager:
    def __init__(self, ssid, password, timeout_s=30):
        self.ssid = ssid
        self.password = password
        self.timeout_s = timeout_s
        self.wlan = network.WLAN(network.STA_IF)

    def connect(self):
        self.wlan.active(True)
        self.wlan.connect(self.ssid, self.password)
        for _ in range(self.timeout_s):
            if self.wlan.status() == STAT_GOT_IP:
                print(f"WiFi verbunden: {self.wlan.ifconfig()[0]}")
                return True
            time.sleep(1)
        return False

    def is_connected(self):
        return self.wlan.status() == STAT_GOT_IP
