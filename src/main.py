"""
Main, should just consider the "non application" pieces...

"""

try:
    import secrets
except ImportError:
    print("no wifi config, run an AP mode I guess....")
    pass


import network
import time

import st7789
import tft_config
import vga1_16x16 as font16
import vga1_8x8 as font8


class Core:
    def __init__(self):
        self.tft = tft_config.config(rotation=1)
        self.tft.init()
        self.font16 = font16
        self.font8 = font8
        self.h = self.tft.height()
        self.w = self.tft.width()
        self.colour_status = st7789.CYAN

    def start(self):
        self.tft.on()
        self.tft.text(self.font16, "Helloween!", 0, 0, st7789.RED)


    def do_station(self):
        network.hostname("helloween")
        self.sta = network.WLAN(network.STA_IF)
        self.sta.active(False)  # reset interface
        self.sta.active(True)
        self.sta.connect(secrets.Wifi.SSID, secrets.Wifi.PASSWORD)

        att = 0
        while not self.sta.isconnected():
            time.sleep(1)
            att += 1
            txt = f"Trying: {secrets.Wifi.SSID}, #{att}"
            self.tft.text(self.font8, txt, 0, 100, self.colour_status)
            print(txt)
            # Might be nice to even run a connection loop a few times,
            # offer an AP for x minutes, but retry again every now and again?
            # ie, offer a chance to have an AP to reconfigure, but still do the right thing if we're brought back
            # into range of the desired place?
        txt = f"Conn: {self.sta.ifconfig()[0]}"
        self.tft.text(self.font8, txt, 0, 100, self.colour_status)
        print(txt)


c = Core()
c.start()
c.do_station()

# here, we would then "import our app" and run it?
# webrepl or what?

