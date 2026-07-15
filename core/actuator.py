import time

from core.device import Device


class Actuator(Device):
    """Base for all actuators. set() is the ONLY way to change hardware state -
    manual API, schedule, and any future rule engine all call this same method,
    so clamp()/floor/max_runtime are enforced no matter who's calling."""

    def __init__(self, id, label, driver, min_value=0.0, max_value=100.0,
                 floor=0.0, max_runtime_ms=None):
        super().__init__(id, label)
        self.driver = driver
        self.min_value = min_value
        self.max_value = max_value
        self.floor = floor  # e.g. a future light that must never go fully dark
        self.max_runtime_ms = max_runtime_ms  # e.g. a future pump safety cutoff; None = unlimited
        self.value = 0.0
        self._on_since_ms = None

    def clamp(self, requested):
        value = max(self.min_value, min(self.max_value, requested))
        if value > 0 and self.floor > 0 and value < self.floor:
            value = self.floor
        return value

    def set(self, requested_value, source="manual"):
        value = self.clamp(requested_value)
        try:
            self._apply(value)
            self.value = value
            self.mark_ok()
            self._on_since_ms = time.ticks_ms() if value > 0 else None
        except Exception as e:
            self.mark_error(e)
        return self.value

    def _apply(self, value):
        """Subclasses drive the actual hardware (e.g. PWM duty_u16)."""
        raise NotImplementedError

    def check_runtime_limit(self):
        if self.max_runtime_ms is None or self._on_since_ms is None:
            return
        if time.ticks_diff(time.ticks_ms(), self._on_since_ms) > self.max_runtime_ms:
            self.set(0.0, source="safety_cutoff")
