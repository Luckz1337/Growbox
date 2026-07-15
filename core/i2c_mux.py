import time


class TCA9548AChannel:
    """Duck-types machine.I2C for one channel of a TCA9548A multiplexer, so existing
    chip drivers (drivers/ccs811.py etc.) work unchanged - they never need to know a mux exists."""

    def __init__(self, i2c, mux_addr, channel):
        self.i2c = i2c
        self.mux_addr = mux_addr
        self.channel = channel

    def _select(self):
        self.i2c.writeto(self.mux_addr, bytearray([1 << self.channel]))
        time.sleep_ms(10)

    def scan(self):
        self._select()
        return self.i2c.scan()

    def readfrom(self, addr, nbytes, stop=True):
        self._select()
        return self.i2c.readfrom(addr, nbytes, stop)

    def readfrom_into(self, addr, buf, stop=True):
        self._select()
        return self.i2c.readfrom_into(addr, buf, stop)

    def writeto(self, addr, buf, stop=True):
        self._select()
        return self.i2c.writeto(addr, buf, stop)

    def readfrom_mem(self, addr, memaddr, nbytes, addrsize=8):
        self._select()
        return self.i2c.readfrom_mem(addr, memaddr, nbytes, addrsize=addrsize)

    def readfrom_mem_into(self, addr, memaddr, buf, addrsize=8):
        self._select()
        return self.i2c.readfrom_mem_into(addr, memaddr, buf, addrsize=addrsize)

    def writeto_mem(self, addr, memaddr, buf, addrsize=8):
        self._select()
        return self.i2c.writeto_mem(addr, memaddr, buf, addrsize=addrsize)


def mux_available(i2c, mux_addr=0x70):
    return mux_addr in i2c.scan()
