from core.sensor import Sensor
from core.vpd import calculate_vpd, get_vpd_status
from drivers.bme680 import BME680_I2C
from drivers.bme280 import BME280


class Bme680Sensor(Sensor):
    def _read_raw(self):
        d = self.driver
        temp, hum = d.temperature, d.humidity
        vpd = calculate_vpd(temp, hum)
        return {
            "temp": temp, "pressure": d.pressure, "humidity": hum, "gas": d.gas,
            "vpd": vpd, "vpd_status": get_vpd_status(vpd),
        }


class Bme280Sensor(Sensor):
    def _read_raw(self):
        temp_raw, pressure_raw, humidity_raw = self.driver.read_compensated_data()
        temp, hum = temp_raw / 100, humidity_raw / 1024
        vpd = calculate_vpd(temp, hum)
        return {
            "temp": temp, "pressure": pressure_raw / 25600, "humidity": hum,
            "vpd": vpd, "vpd_status": get_vpd_status(vpd),
        }


def create_bme68x(spec, bus):
    driver = BME680_I2C(i2c=bus, address=spec["address"])
    return Bme680Sensor(spec["id"], spec["label"], driver, spec.get("stale_after_ms", 90_000))


def create_bme28x(spec, bus):
    driver = BME280(i2c=bus, address=spec["address"])
    return Bme280Sensor(spec["id"], spec["label"], driver, spec.get("stale_after_ms", 90_000))
