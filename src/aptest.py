"""
On GPIO 36 and 39 (only ones I've found so far) _and_ only if wifi is active,
I get spurious IRQs around every 100ms, but sometimes on a multiple of that.

example output:

bleh
Pin(36) del: 303: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 204: DETECTOR 1
Pin(36) del: 103: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 103: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 103: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 205: DETECTOR 1
Pin(36) del: 410: DETECTOR 1
Pin(36) del: 204: DETECTOR 1
Pin(36) del: 103: DETECTOR 1
bleh
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 103: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 103: DETECTOR 1
Pin(36) del: 102: DETECTOR 1
Pin(36) del: 103: DETECTOR 1
Pin(36) del: 204: DETECTOR 1

"""
import asyncio
import machine
import network
import time

import secrets

class KPeopleSensor:
    """
    This is _meant_ to just be an asyncio task wrapper for a pin change interrupt..
    However, we get irq events while idle, without any change on the pin (scoped even)
    we get them at a rate of about every 100ms, or, roughly a multiple thereof
    """
    def __init__(self, pin):
        self.pin = pin
        self.found = asyncio.ThreadSafeFlag()  # From isr_rules.html....
        self.pin.irq(self._handler, trigger=machine.Pin.IRQ_FALLING)

    def _handler(self, p):
        # I _should_ only get an IRQ when it actually falls, but have been unable to figure
        # out why I get extra... It works just fine
        #print("handler...", p.value())  # GAH WHY SO MUCH NOISE!
        self.found.set()

    async def task_monitor(self):
        last = time.ticks_ms()
        while True:
            await self.found.wait()
            now = time.ticks_ms()
            print(f"{self.pin} del: {now - last}: DETECTOR", self.pin.value())
            last = now

    def start_aio(self):
        asyncio.create_task(self.task_monitor())


class Core:
    def __init__(self):
        #pin = machine.Pin.board.DETECTOR
        # Fails on pin 36, works on pin 25...
        # pin_n = 36
        # pin = machine.Pin(pin_n, machine.Pin.IN)
        # self.ps = KPeopleSensor(pin)

        # try a bunch of pins.
        self.all = [
            KPeopleSensor(machine.Pin(36, machine.Pin.IN)),
            KPeopleSensor(machine.Pin(37, machine.Pin.IN)),
            KPeopleSensor(machine.Pin(38, machine.Pin.IN)),
            KPeopleSensor(machine.Pin(39, machine.Pin.IN)),
            KPeopleSensor(machine.Pin(25, machine.Pin.IN)),
            KPeopleSensor(machine.Pin(26, machine.Pin.IN)),
            KPeopleSensor(machine.Pin(27, machine.Pin.IN)),
        ]

    def do_station(self):
        self.sta = network.WLAN(network.STA_IF)
        self.sta.active(False)  # reset interface
        self.sta.active(True)
        self.sta.connect(secrets.Wifi.SSID, secrets.Wifi.PASSWORD)

        att = 0
        while not self.sta.isconnected():
            time.sleep(1)
            att += 1
            print(f"Trying: {secrets.Wifi.SSID}, #{att}")
        print(f"Conn: {self.sta.ifconfig()[0]}")

    def do_pintest(self):
        async def wot():
            while True:
                print("bleh")
                await asyncio.sleep_ms(2000)
        try:
            for ps in self.all:
                ps.start_aio()
            asyncio.run(wot())
        finally:
            print("exploded, restarting!")
            asyncio.new_event_loop()


c = Core()
c.do_station()  # if we _DONT_ connect to wifi, it works fine?!
print("ok, starting up now....")
c.do_pintest()
