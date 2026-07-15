import json
import asyncio

from core.timeutil import localtime_with_offset


class ScheduleStore:
    """Rules use a generic actions=[{"actuator_id":..., "value":...}, ...] list instead of
    named umluft/abluft fields, so a 3rd actuator needs no schema/parser change.
    asyncio.Lock guards load-mutate-save sequences - defensive insurance now that the
    old _thread-vs-HTTP-handler race is structurally gone under uasyncio."""

    def __init__(self, controller, filename="schedule.json"):
        self.controller = controller
        self.filename = filename
        self.lock = asyncio.Lock()
        self.rules = self._load()

    def _load(self):
        try:
            with open(self.filename, "r") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _save(self):
        with open(self.filename, "w") as f:
            json.dump(self.rules, f)

    async def add(self, rule):
        async with self.lock:
            self.rules.append(rule)
            self._save()

    async def delete(self, index):
        async with self.lock:
            if not (0 <= index < len(self.rules)):
                return None
            rule = self.rules.pop(index)
            self._save()
            return rule

    async def toggle(self, index):
        async with self.lock:
            if not (0 <= index < len(self.rules)):
                return None
            rule = self.rules[index]
            rule["enabled"] = not rule.get("enabled", True)
            self._save()
            return rule

    async def clear(self):
        async with self.lock:
            self.rules = []
            self._save()

    async def check_and_apply(self):
        async with self.lock:
            if not self.rules:
                return False

            now = localtime_with_offset()
            current_minutes = now[3] * 60 + now[4]
            current_weekday = now[6]

            for rule in self.rules:
                if not rule.get("enabled", True):
                    continue
                if "weekdays" in rule and current_weekday not in rule["weekdays"]:
                    continue

                start_minutes = rule.get("start_hour", 0) * 60 + rule.get("start_minute", 0)
                end_minutes = rule.get("end_hour", 23) * 60 + rule.get("end_minute", 59)
                if start_minutes > end_minutes:
                    time_match = current_minutes >= start_minutes or current_minutes <= end_minutes
                else:
                    time_match = start_minutes <= current_minutes <= end_minutes
                if not time_match:
                    continue

                applied = False
                for action in rule.get("actions", []):
                    actuator = self.controller.actuators.get(action["actuator_id"])
                    if actuator is not None and actuator.value != action["value"]:
                        self.controller.apply(action["actuator_id"], action["value"], source="schedule")
                        applied = True
                if applied:
                    print(f"Zeitplan aktiv: '{rule.get('name', 'Unbenannt')}'")
                    return True
            return False
