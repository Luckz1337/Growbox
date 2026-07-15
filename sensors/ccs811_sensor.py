from core.sensor import Sensor
from drivers.ccs811 import CCS811


class Ccs811Sensor(Sensor):
    def _read_raw(self):
        if not self.driver.data_ready():
            # not an error, just no new sample yet - keep last cached values
            return dict(self.last_values) if self.last_values else {"co2": 400, "tvoc": 0}
        return {"co2": self.driver.eCO2, "tvoc": self.driver.tVOC}


def create(spec, bus):
    driver = CCS811(i2c=bus, addr=spec["address"])
    return Ccs811Sensor(spec["id"], spec["label"], driver, spec.get("stale_after_ms", 90_000))
