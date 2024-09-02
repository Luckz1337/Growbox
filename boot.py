# This file is executed on every boot (including wake-boot from deepsleep)
#import esp
#esp.osdebug(None)
#import webrepl
#webrepl.start()
# boot.py
#
from ota import OTAUpdater
from wifi_config import SSID, PASSWORD

def check_for_updates():
    firmware_url = "https://raw.githubusercontent.com/Luckz1337/Growbox/"
    ota_updater = OTAUpdater(SSID, PASSWORD, firmware_url, "main.py")
    ota_updater.download_and_install_update_if_available()

check_for_updates()
