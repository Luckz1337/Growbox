from core.sensor import Sensor
from drivers.bh1750 import BH1750


class Bh1750Sensor(Sensor):
    def _read_raw(self):
        return {"lux": self.driver.luminance(BH1750.CONT_HIRES_1)}


def create(spec, bus):
    driver = BH1750(bus)
    return Bh1750Sensor(spec["id"], spec["label"], driver, spec.get("stale_after_ms", 90_000))
