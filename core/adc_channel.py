from machine import ADC, Pin


class CalibratedADC:
    """Wraps a raw ADC pin with a two-point (air/water style) calibration to a 0-100 percent scale."""

    def __init__(self, pin, calib_low_raw, calib_high_raw, atten=ADC.ATTN_11DB, width=ADC.WIDTH_12BIT):
        self.adc = ADC(Pin(pin))
        self.adc.atten(atten)
        self.adc.width(width)
        # raw reading AT calib_low_raw reads as 100%, AT calib_high_raw reads as 0%
        # (for moisture: calib_low_raw=water_raw, calib_high_raw=air_raw - wetter reads higher)
        self.calib_low_raw = calib_low_raw
        self.calib_high_raw = calib_high_raw

    def read_raw(self):
        return self.adc.read()

    def read_percent(self):
        raw = self.read_raw()
        span = self.calib_high_raw - self.calib_low_raw
        pct = (self.calib_high_raw - raw) * 100 / span
        return max(0, min(100, round(pct, 1)))
