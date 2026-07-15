from core.sensor import Sensor
from core.adc_channel import CalibratedADC


class MoistureSensor(Sensor):
    def _read_raw(self):
        return {"pct": self.driver.read_percent(), "raw": self.driver.read_raw()}


def create(spec, bus):
    # bus is unused here (bus="adc" sensors own their pin directly, see core/registry.py)
    adc = CalibratedADC(spec["pin"], spec["calib_water"], spec["calib_air"])
    return MoistureSensor(spec["id"], spec["label"], adc, spec.get("stale_after_ms", 90_000))
