
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
            print(f"del: {now - last}: DETECTOR", self.pin.value())
            last = now

    def start_aio(self):
        asyncio.create_task(self.task_monitor())


class Core:
    def __init__(self):
        pin = machine.Pin.board.DETECTOR
        pin.init(pin.IN)
        self.ps = KPeopleSensor(pin)

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
            self.ps.start_aio()
            asyncio.run(wot())
        finally:
            print("exploded, restarting!")
            asyncio.new_event_loop()


c = Core()
c.do_station()  # if we _DONT_ connect to wifi, it works fine?!
print("ok, starting up now....")
c.do_pintest()
