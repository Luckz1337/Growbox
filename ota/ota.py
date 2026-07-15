import os
import json
import urequests

# Dateien, die eine OTA-Aktualisierung NIE anfassen darf: Geheimnisse, geraetespezifische
# Konfiguration und Laufzeit-/Nutzerdaten.
EXCLUDED_FROM_OTA = {
    "secrets.py", "device_secrets.py", "wifi_config.py", "settings_local.py",
    "actuator_settings.json", "schedule.json", "sensor_data.csv", "version.json",
}


class OTAUpdater:
    def __init__(self, repo_url, manifest_file="manifest.json", version_file="version.json"):
        if "www.github.com" in repo_url:
            repo_url = repo_url.replace("www.github", "raw.githubusercontent")
        elif "github.com" in repo_url:
            repo_url = repo_url.replace("github", "raw.githubusercontent")
        self.repo_url = repo_url
        self.manifest_file = manifest_file
        self.version_file = version_file

    def _url(self, path):
        return self.repo_url + "main/" + path

    def _fetch_json(self, path):
        resp = urequests.get(self._url(path))
        try:
            if resp.status_code != 200:
                raise RuntimeError(f"{path}: HTTP {resp.status_code}")
            return json.loads(resp.text)
        finally:
            resp.close()

    def _fetch_text(self, path):
        resp = urequests.get(self._url(path))
        try:
            if resp.status_code != 200:
                raise RuntimeError(f"{path}: HTTP {resp.status_code}")
            return resp.text
        finally:
            resp.close()

    def _current_version(self):
        try:
            with open(self.version_file) as f:
                return int(json.load(f)["version"])
        except (OSError, ValueError, KeyError):
            return 0

    def check_for_update(self):
        """Returns {"available": bool, "current": int, "latest": int}."""
        current = self._current_version()
        latest = int(self._fetch_json(self.version_file)["version"])
        return {"available": latest > current, "current": current, "latest": latest}

    def apply_update(self):
        """Download every manifest file, validate ALL of them first (compile() for .py,
        non-empty check otherwise), and only then swap them in. If anything fails during
        download/validation, nothing live is touched. If a swap itself fails partway,
        already-swapped files are rolled back from their .bak copy."""
        manifest = self._fetch_json(self.manifest_file)
        files = [f for f in manifest["files"] if f not in EXCLUDED_FROM_OTA]

        downloaded = []
        try:
            for path in files:
                content = self._fetch_text(path)
                if path.endswith(".py"):
                    compile(content, path, "exec")
                elif not content:
                    raise RuntimeError(f"{path}: leer, abgelehnt")
                self._ensure_parent_dir(path)
                with open(path + ".new", "w") as f:
                    f.write(content)
                downloaded.append(path)
        except Exception:
            self._cleanup_new_files(downloaded)
            raise

        swapped = []
        try:
            for path in downloaded:
                self._swap_in(path)
                swapped.append(path)
        except Exception as e:
            self._rollback(swapped)
            raise RuntimeError(f"Swap fehlgeschlagen: {e}") from e

        remote_version = self._fetch_json(self.version_file)
        with open(self.version_file, "w") as f:
            json.dump(remote_version, f)

        return downloaded

    def _swap_in(self, path):
        try:
            os.remove(path + ".bak")
        except OSError:
            pass
        try:
            os.rename(path, path + ".bak")
        except OSError:
            pass  # Datei existierte vorher noch nicht (neu in diesem Release)
        os.rename(path + ".new", path)

    def _rollback(self, files):
        for path in files:
            try:
                os.remove(path)
            except OSError:
                pass
            try:
                os.rename(path + ".bak", path)
            except OSError:
                pass

    def _cleanup_new_files(self, files):
        for path in files:
            try:
                os.remove(path + ".new")
            except OSError:
                pass

    def _ensure_parent_dir(self, path):
        parts = path.split("/")[:-1]
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            try:
                os.mkdir(current)
            except OSError:
                pass
