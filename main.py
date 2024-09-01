from machine import Pin, I2C
import time
import CCS811
import bme280
import bh1750

class I2CMultiplexer:
    def __init__(self, i2c, address=0x70):
        self.i2c = i2c
        self.address = address

    def select_channel(self, channel):
        if channel < 0 or channel > 7:
            raise ValueError('Kanal muss zwischen 0 und 7 liegen')
        self.i2c.writeto(self.address, bytearray([1 << channel]))
        time.sleep(0.1)  # Kurze Verzögerung, um sicherzustellen, dass der Kanal aktiviert ist

class SensorManager:
    def __init__(self, multiplexer):
        self.multiplexer = multiplexer
        self.ccs811 = None
        self.bme280 = None
        self.bh1750 = None

    def init_ccs811(self, channel):
        self.multiplexer.select_channel(channel)
        self.ccs811 = CCS811.CCS811(i2c=self.multiplexer.i2c, addr=0x5A)
        while not self.ccs811.data_ready():
            time.sleep(1)

    def init_bme280(self, channel):
        self.multiplexer.select_channel(channel)
        self.bme280 = bme280.BME280(i2c=self.multiplexer.i2c)

    def init_bh1750(self, channel):
        self.multiplexer.select_channel(channel)
        self.bh1750 = bh1750.BH1750(self.multiplexer.i2c)

    def read_ccs811(self):
        self.multiplexer.select_channel(0)
        co2 = self.ccs811.eCO2
        tvoc = self.ccs811.tVOC
        print('CO2: {} ppm'.format(co2))
        print('TVOC: {} ppb'.format(tvoc))

    def read_bme280(self):
        self.multiplexer.select_channel(1)
        temperature, pressure, humidity = self.bme280.read_compensated_data()
        temp_celsius = temperature / 100
        pressure_hpa = pressure / 25600
        humidity_percent = humidity / 1024
        print('Temperatur: {:.2f}°C'.format(temp_celsius))
        print('Luftdruck: {:.2f} hPa'.format(pressure_hpa))
        print('Luftfeuchtigkeit: {:.2f}%'.format(humidity_percent))

    def read_bh1750(self):
        self.multiplexer.select_channel(2)
        light_intensity = self.bh1750.luminance(bh1750.BH1750.CONT_HIRES_1)
        print('Lichtintensität: {:.2f} Lux'.format(light_intensity))

def main():
    i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=100000)
    multiplexer = I2CMultiplexer(i2c)
    sensors = SensorManager(multiplexer)

    sensors.init_ccs811(channel=0)
    sensors.init_bme280(channel=1)
    sensors.init_bh1750(channel=2)

    while True:
        sensors.read_ccs811()
        sensors.read_bme280()
        sensors.read_bh1750()
        time.sleep(2)

if __name__ == '__main__':
    main()

