# encoder_portable.py

# Encoder Support: this version should be portable between MicroPython platforms
# Thanks to Evan Widloski for the adaptation to use the machine module

# Copyright (c) 2017-2022 Peter Hinch
# Released under the MIT License (MIT) - see LICENSE file
import asyncio

from machine import Pin

class Encoder:
    def __init__(self, pin_x, pin_y, scale=1):
        self.scale = scale
        self.forward = True
        self.pin_x = pin_x
        self.pin_y = pin_y
        self._x = pin_x()
        self._y = pin_y()
        self._pos = 0
        #self._max = 0
        #self._min = 0
        self.tmax = None
        self.tmin = None
        self.ev = asyncio.ThreadSafeFlag()

        try:
            self.x_interrupt = pin_x.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self.x_callback, hard=True)
            self.y_interrupt = pin_y.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self.y_callback, hard=True)
        except TypeError:
            self.x_interrupt = pin_x.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self.x_callback)
            self.y_interrupt = pin_y.irq(trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING, handler=self.y_callback)

    def _common_cb(self, a, b, c):
        self.forward = a ^ b ^ c
        self._pos += 1 if self.forward else -1
        #self._max = max(self._pos, self._max)
        #self._min = min(self._pos, self._min)
        if self.tmax and self._pos > self.tmax:
            self.ev.set()
            self._cb(self._pos)  # FIXME -probably dont do this, it does the CB in irq context.
            self.tmax = None
        if self.tmin and self._pos < self.tmin:
            self.ev.set()
            self._cb(self._pos)  # FIXME -probably dont do this, it does the CB in irq context.
            self.tmin = None


    def x_callback(self, pin_x):
        if (x := pin_x()) != self._x:  # Reject short pulses
            self._x = x
            self._common_cb(x, self.pin_y(), 0)

    def y_callback(self, pin_y):
        if (y := pin_y()) != self._y:
            self._y = y
            self._common_cb(y, self.pin_x(), 1)

    def position(self, value=None):
        if value is not None:
            self._pos = round(value / self.scale)  # Improvement provided by @IhorNehrutsa
        return self._pos * self.scale

    def value(self, value=None):
        if value is not None:
            self._pos = value
        return self._pos

    def wait_for(self, cb, max=None, min=None):
        self._cb = cb
        self.ev.clear()  # make self.ev a "user api"
        self.tmax = max
        self.tmin = min

    def wait_rel(self, cb, delta):
        self._cb = cb
        self.ev.clear()  # make self.ev a "user api"
        if delta > 0:
            self.tmax = self._pos + delta
            self.tmin = None
        else:
            self.tmax = None
            self.tmin = self._pos + delta  # yes, delta is signed...

