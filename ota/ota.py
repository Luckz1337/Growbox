import network
import urequests
import os
import json
import machine
from time import sleep

class OTAUpdater:
    """ This class handles OTA updates. It connects to the Wi-Fi, checks for updates, downloads, and installs them."""
    
    def __init__(self, ssid, password, repo_url, filename):
        self.filename = filename
        self.ssid = ssid
        self.password = password
        self.repo_url = repo_url
        
        if "www.github.com" in self.repo_url:
            print(f"Updating {repo_url} to raw.githubusercontent")
            self.repo_url = self.repo_url.replace("www.github", "raw.githubusercontent")
        elif "github.com" in self.repo_url:
            print(f"Updating {repo_url} to raw.githubusercontent'")
            self.repo_url = self.repo_url.replace("github", "raw.githubusercontent")
        
        self.version_url = self.repo_url + 'main/version.json'
        print(f"version url is: {self.version_url}")
        self.firmware_url = self.repo_url + 'main/' + filename

        # Get the current version (stored in version.json)
        if 'version.json' in os.listdir():
            with open('version.json') as f:
                self.current_version = int(json.load(f)['version'])
            print(f"Current device firmware version is '{self.current_version}'")
        else:
            self.current_version = 0
            # Save the current version
            with open('version.json', 'w') as f:
                json.dump({'version': self.current_version}, f)

    def connect_wifi(self):
        """ Connect to Wi-Fi."""
        sta_if = network.WLAN(network.STA_IF)
        sta_if.active(True)
        sta_if.connect(self.ssid, self.password)
        while not sta_if.isconnected():
            print('.', end="")
            sleep(0.25)
        print(f'Connected to WiFi, IP is: {sta_if.ifconfig()[0]}')

    def fetch_latest_code(self) -> bool:
        """ Fetch the latest code from the repo, returns False if not found."""
        response = urequests.get(self.firmware_url)
        if response.status_code == 200:
            print(f'Fetched latest firmware code, status: {response.status_code}, -  {response.text}')
            self.latest_code = response.text
            return True
        elif response.status_code == 404:
            print(f'Firmware not found - {self.firmware_url}.')
            return False

    def backup_current_code(self):
        """ Backup the current main.py file. """
        if 'main.py' in os.listdir():
            if 'main_backup.py' in os.listdir():
                os.remove('main_backup.py')  # Remove old backup if exists
            os.rename('main.py', 'main_backup.py')
            print("Backup of current main.py created as main_backup.py")

    def restore_backup(self):
        """ Restore the backup if the update fails. """
        if 'main_backup.py' in os.listdir():
            if 'main.py' in os.listdir():
                os.remove('main.py')  # Remove the faulty update
            os.rename('main_backup.py', 'main.py')
            print("Backup restored as main.py")

    def validate_new_code(self) -> bool:
        """ Validate the new code to ensure it is correct. """
        try:
            compile(self.latest_code, 'latest_code.py', 'exec')
            print("New code validation successful")
            return True
        except Exception as e:
            print(f"Error validating new code: {e}")
            return False

    def update_no_reset(self):
        """ Update the code without resetting the device."""
        with open('latest_code.py', 'w') as f:
            f.write(self.latest_code)
        self.current_version = self.latest_version
        with open('version.json', 'w') as f:
            json.dump({'version': self.current_version}, f)
        self.latest_code = None

    def update_and_reset(self):
        """ Update the code and reset the device."""
        print(f"Updating device... (Renaming latest_code.py to {self.filename})", end="")
        os.rename('latest_code.py', self.filename)
        print('Restarting device...')
        machine.reset()  # Reset the device to run the new code

    def check_for_updates(self):
        """ Check if updates are available."""
        self.connect_wifi()
        print(f'Checking for latest version... on {self.version_url}')
        response = urequests.get(self.version_url)
        print(f"Response Text: {response.text}")
        data = json.loads(response.text)
        print(f"data is: {data}, url is: {self.version_url}")
        print(f"data version is: {data['version']}")
        self.latest_version = int(data['version'])
        print(f'latest version is: {self.latest_version}')
        newer_version_available = self.current_version < self.latest_version
        print(f'Newer version available: {newer_version_available}')
        return newer_version_available

    def download_and_install_update_if_available(self):
        """ Check for updates, download, validate, and install them."""
        if self.check_for_updates():
            self.backup_current_code()  # Backup the current code
            if self.fetch_latest_code():
                if self.validate_new_code():
                    self.update_no_reset()
                    self.update_and_reset()
                else:
                    print("Validation failed, restoring backup...")
                    self.restore_backup()
            else:
                self.restore_backup()
        else:
            print('No new updates available.')

