import time


class DeviceStatus:
    NEVER_CONNECTED = "never_connected"
    ONLINE = "online"
    STALE = "stale"
    ERROR = "error"


class Device:
    """Shared base for every sensor and actuator: identity, status, and error/staleness bookkeeping."""

    def __init__(self, id, label):
        self.id = id
        self.label = label
        self.last_ok_ms = None
        self.last_error = None
        self.status = DeviceStatus.NEVER_CONNECTED

    def mark_ok(self):
        self.last_ok_ms = time.ticks_ms()
        self.status = DeviceStatus.ONLINE
        self.last_error = None

    def mark_error(self, exc):
        self.last_error = str(exc)
        self.status = DeviceStatus.ERROR if self.last_ok_ms is None else DeviceStatus.STALE

    def age_ms(self):
        if self.last_ok_ms is None:
            return None
        return time.ticks_diff(time.ticks_ms(), self.last_ok_ms)

    def to_status_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "last_ok_ms_ago": self.age_ms(),
            "last_error": self.last_error,
        }
