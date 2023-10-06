"""
Main, should just consider the "non application" pieces...

"""

try:
    import secrets
except ImportError:
    print("no wifi config, run an AP mode I guess....")
    pass


import asyncio
import network
import time

import st7789
import tft_config
import vga1_16x16 as font16
import vga1_8x8 as font8

import mqtt_as


class Core:
    def __init__(self):
        self.tft = tft_config.config(rotation=1)
        self.tft.init()
        self.font16 = font16
        self.font8 = font8
        self.h = self.tft.height()
        self.w = self.tft.width()
        self.colour_status = st7789.CYAN
        self.topic_status = "helloween/status"
        self.topic_state = "helloween/state"

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

    def helper_status(self, txt):
        """helper to write status text, hides colours and positioning"""
        # TODO - clear whole line would probable be important...
        # ideally get screen width and font size and expand the string with " " until it's the whole line?
        self.tft.text(self.font8, txt, 0, 110, self.colour_status)

    def do_mqtt(self):
        """
        mqtt-as wants to operate the network interface.  Seems less than ideal, but.. I don't reallllly mind.
        :return: never this starts a mq loop right here
        """
        network.hostname("helloween")
        c = mqtt_as.config
        c["server"] = secrets.Mqtt.HOST
        c["user"] = secrets.Mqtt.USERNAME
        c["password"] = secrets.Mqtt.PASSWORD
        c["ssid"] = secrets.Wifi.SSID
        c["wifi_pw"] = secrets.Wifi.PASSWORD
        c["queue_len"] = 10  # use event interface, basic short queue.

        c["will"] = (self.topic_state, "off", True, 0)

        mqtt_as.MQTTClient.DEBUG = True  # yes please, right now!
        self.mq = mqtt_as.MQTTClient(c)
        try:
            asyncio.run(self.main_mq())
        finally:
            self.mq.close()
            print("exploded, restarting!")
            asyncio.new_event_loop()

    def helper_led(self, led_idx, on):
        col = st7789.BLACK
        if on:
            col = st7789.GREEN
        rad = 10
        space = 24
        self.tft.fill_circle(150 + space * (led_idx - 1), space // 2, rad, col)

    async def pulse(self):
        """ demo code that blinks a "led" on demand"""
        self.helper_led(1, True)
        await asyncio.sleep_ms(500)
        self.helper_led(1, False)

    async def handle_messages(self):
        async for topic, msg, retained in self.mq.queue:
            print(f'Topic: "{topic.decode()}" Message: "{msg.decode()}" Retained: {retained}')
            asyncio.create_task(self.pulse())

    async def down(self):
        """I don't think I need this one at all..."""
        self.mq_down_events = 0
        while True:
            await self.mq.down.wait()
            self.mq.down.clear()
            self.helper_led(2, False)
            self.mq_down_events += 1
            txt = f"mqtt/wifi down {self.mq_down_events}"
            print(txt)
            self.helper_status(txt)

    async def up(self):
        """we want an mq up event, as it's great for re-doing subs..."""
        while True:
            await self.mq.up.wait()
            self.mq.up.clear()
            self.helper_led(2, True)
            txt = "mq good"
            print(txt)
            self.helper_status(txt)
            await self.mq.subscribe("helloween/cmd/#", 0)  # yeah, we actually aren't designing for a qos1 required environment
            await self.mq.publish(self.topic_state, "on", True)

    async def main_mq(self):
        print("starting async main!")
        try:
            await self.mq.connect()
            # TODO - write our IP address to that line?
            my_ip = self.mq._sta_if.ifconfig()[0]
            txt = f"Conn: {my_ip}"
            self.tft.text(self.font8, txt, 0, 120, self.colour_status)
            #self.helper_status(txt)
            print(txt)
        except OSError:
            print("connection failed...")
            return
        for t in [self.up, self.down, self.handle_messages]:
            asyncio.create_task(t())

        i = 0
        while True:
            await asyncio.sleep(2)
            i += 1
            print("bleep bloop")
            await self.mq.publish(self.topic_status, f"{i}, outs: {self.mq_down_events}")



c = Core()
c.start()
# c.do_station()
print("ok, starting up now....")
c.do_mqtt()
print("shouldn't get here")

# here, we would then "import our app" and run it?
# webrepl or what?

