# NeoPixel driver for MicroPython
# MIT license; Copyright (c) 2016 Damien P. George, 2021 Jim Mussared

from machine import bitstream

class slice_maker_class:
    def __getitem__(self, slc):
        return slc


slice_maker = slice_maker_class()


class NeoPixel:
    # G R B W
    ORDER = (1, 0, 2, 3)

    def __init__(self, pin, n, bpp=3, timing=1):
        self.pin = pin
        self.n = n
        self.bpp = bpp
        self.buf = bytearray(n * bpp)
        self.pin.init(pin.OUT)
        # Timing arg can either be 1 for 800kHz or 0 for 400kHz,
        # or a user-specified timing ns tuple (high_0, low_0, high_1, low_1).
        self.timing = (
            ((400, 850, 800, 450) if timing else (800, 1700, 1600, 900))
            if isinstance(timing, int)
            else timing
        )

    def __len__(self):
        return self.n

    def set_pixel(self, pixel_num, v):
        def _set_pixel1(pixel_num, v):
            offset = pixel_num * self.bpp
            for nn in range(self.bpp):
                self.buf[offset + self.ORDER[nn]] = v[nn]

        if type(pixel_num) is slice:
            for i in range(*pixel_num.indices(self.n)):
                _set_pixel1(i, v)
        else:
            _set_pixel1(pixel_num, v)

    def __setitem__(self, i, v):
        self.set_pixel(i, v)

    def __getitem__(self, i):
        offset = i * self.bpp
        return tuple(self.buf[offset + self.ORDER[i]] for i in range(self.bpp))

    def rotate(self, count=1):
        """Rotate.  count can be positive or negative..."""
        self.buf = self.buf[count*self.bpp:] + self.buf[:count*self.bpp]

    def fill(self, v):
        b = self.buf
        l = len(self.buf)
        bpp = self.bpp
        for i in range(bpp):
            c = v[i]
            j = self.ORDER[i]
            while j < l:
                b[j] = c
                j += bpp

    def write(self):
        # BITSTREAM_TYPE_HIGH_LOW = 0
        bitstream(self.pin, 0, self.timing, self.buf)
