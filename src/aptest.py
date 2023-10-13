
import asyncio
import binascii
import machine
import network
import time

import halloween2
import secrets

class Core:
    def __init__(self):
        self.app = halloween2.KApp()

    def do_station(self):
        """ An alternate simple start, normally we let mqtt-as just take care of bizness"""
        self.sta = network.WLAN(network.STA_IF)
        self.sta.active(False)  # reset interface
        self.sta.active(True)
        self.sta.connect(secrets.Wifi.SSID, secrets.Wifi.PASSWORD)

        att = 0
        while not self.sta.isconnected():
            time.sleep(1)
            att += 1
            txt = f"Trying: {secrets.Wifi.SSID}, #{att}"
            print(txt)
            # Might be nice to even run a connection loop a few times,
            # offer an AP for x minutes, but retry again every now and again?
            # ie, offer a chance to have an AP to reconfigure, but still do the right thing if we're brought back
            # into range of the desired place?
        txt = f"Conn: {self.sta.ifconfig()[0]}"
        print(txt)

    def do_pintest(self):
        async def wot():
            while True:
                print("bleh")
                await asyncio.sleep_ms(2000)
        try:
            self.app.people_sensor.start_aio()
            asyncio.run(wot())
        finally:
            print("exploded, restarting!")
            asyncio.new_event_loop()



c = Core()
c.do_station()
print("ok, starting up now....")
c.do_pintest()