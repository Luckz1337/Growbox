from core.device import Device


class Sensor(Device):
    """Base for all sensors: uniform caching so a failed read never raises,
    it just returns the last known-good values (or an empty dict if there never was one)."""

    def __init__(self, id, label, driver, stale_after_ms=90_000):
        super().__init__(id, label)
        self.driver = driver
        self.stale_after_ms = stale_after_ms
        self.last_values = {}

    def read(self):
        try:
            values = self._read_raw()
            self.last_values = values
            self.mark_ok()
            return values
        except Exception as e:
            self.mark_error(e)
            return dict(self.last_values)

    def is_stale(self):
        age = self.age_ms()
        return age is None or age > self.stale_after_ms

    def _read_raw(self):
        """Subclasses return a dict of {field: value}. Raise on failure, don't return partial/garbage data."""
        raise NotImplementedError
