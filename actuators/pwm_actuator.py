from machine import Pin, PWM

from core.actuator import Actuator


class PwmActuator(Actuator):
    def _apply(self, value):
        duty = int(value / 100 * 65535)
        self.driver.duty_u16(duty)


def create(spec):
    pwm = PWM(Pin(spec["pin"]))
    pwm.freq(spec["pwm_freq"])
    return PwmActuator(
        spec["id"], spec["label"], pwm,
        min_value=spec.get("min_value", 0), max_value=spec.get("max_value", 100),
        floor=spec.get("floor", 0), max_runtime_ms=spec.get("max_runtime_ms"),
    )
