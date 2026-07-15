import json

from core.timeutil import format_datetime, localtime_with_offset


class ActuatorController:
    """apply() is the single path every caller (manual API, schedule, later a rule engine)
    uses to change an actuator - Actuator.set() itself enforces clamp/floor either way."""

    def __init__(self, actuators, settings_file="actuator_settings.json"):
        self.actuators = actuators  # dict: id -> Actuator
        self.settings_file = settings_file
        self._load_settings()

    def _load_settings(self):
        try:
            with open(self.settings_file, "r") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        for actuator_id, actuator in self.actuators.items():
            if actuator_id in saved:
                actuator.set(saved[actuator_id], source="startup")

    def _save_settings(self):
        data = {actuator_id: a.value for actuator_id, a in self.actuators.items()}
        data["last_updated"] = format_datetime(localtime_with_offset())
        try:
            with open(self.settings_file, "w") as f:
                json.dump(data, f)
        except OSError as e:
            print(f"[actuators] save_settings failed: {e}")

    def apply(self, actuator_id, value, source="manual", persist=True):
        actuator = self.actuators.get(actuator_id)
        if actuator is None:
            raise KeyError(f"unknown actuator: {actuator_id}")
        result = actuator.set(value, source=source)
        if persist:
            self._save_settings()
        return result

    def get_values(self):
        return {actuator_id: a.value for actuator_id, a in self.actuators.items()}
