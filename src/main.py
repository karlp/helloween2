"""
Main, should just consider the "non application" pieces...

"""

try:
    import secrets
except ImportError:
    print("no wifi config, run an AP mode I guess....")
    pass


import asyncio
import binascii
import json
import machine
import network
import time

import st7789
import tft_config
import vga1_16x16 as font16
import vga1_8x8 as font8

import mqtt_as

import halloween2


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
        self.app = halloween2.KApp()
        self.uid_s = binascii.hexlify(machine.unique_id()).decode()
        self.nodeid = f"helloween-{self.uid_s[:-4]}"
        self.ha_prefix = "homeassistant"


    def start(self):
        self.tft.on()
        self.tft.text(self.font16, "Helloween!", 0, 0, st7789.RED)


    def do_station(self):
        """ An alternate simple start, normally we let mqtt-as just take care of bizness"""
        network.hostname(self.nodeid)
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

    def helper_status(self, line, txt, clear=True):
        """helper to write status text, hides colours and positioning"""
        # TODO - clear whole line would probable be important...
        # ideally get screen width and font size and expand the string with " " until it's the whole line?
        line_h = 10 # 8 for the font, plus padding
        y = 100 + (line * line_h)
        if clear:
            self.tft.fill_rect(0, y, self.tft.width(), line_h, st7789.BLACK)
        self.tft.text(self.font8, txt, 0, y, self.colour_status)

    def do_mqtt(self):
        """
        mqtt-as wants to operate the network interface.  Seems less than ideal, but.. I don't reallllly mind.
        :return: never this starts a mq loop right here
        """
        network.hostname(self.nodeid)
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
        await asyncio.sleep_ms(200)
        self.helper_led(1, False)

    def generate_status_msg(self):
        """stuff we want to post to mqtt regularly, as status stuff."""
        return f"""spider: pos: {self.app.spider.pos_real} goal: {self.app.spider.pos_goal} in pos: {self.app.spider.in_position}
        spider: t: {self.app.spider.step_ms} pid= {self.app.spider.kp}/{self.app.spider.ki}/{self.app.spider.kd}
            lights: lol, nothing yet. detector: {self.app.people_sensor}"""

    async def update_hass(self):
        """
        WIP for publishing discovery stuff to Home assistant
        Intent is for... at least.
        * one "switch" for master lights on/off
        * one "switch" for master motor on/off
        * one button to reset positions for spider...

        extra goals
        * "slider"  for "direct" motor control
        * drop down or pattern selector or whatever or free text to set light patterns...
        *
        """
        retain = True
        qos = 0
        # Note, we use "nodeid" but for ha purposes, this is the "objectid"
        # base message...
        msg = dict(
            cmd_t="~/set",
            stat_t="~/state",
            schema="json",
            unique_id="yes_please_uid",
            dev=dict(mf="Ekta Labs",
                     name="hell-o-ween",
                     model="proto1",
                     sw_version="0.3",
                     identifiers=self.nodeid),  # Same nodeid again?
        )

        msg["name"] = "ze lights"
        base = f"{self.ha_prefix}/light/{self.nodeid}"
        msg["~"] = base
        msg["effect"] = True
        msg["effect_list"] = [x[0] for x in self.app.lights.known_patterns]
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)
        # We _also_ need to tell the modules about their mq now!
        self.app.lights.use_mq(self.mq, base)


        # msg["name"] = "motor master"
        # base = f"{self.ha_prefix}/switch/{self.nodeid}"
        # msg["~"] = base
        # await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)
        # This gets discovery, but you still now need _state_ topics to make the ui nicer in HA

    async def handle_ha_message(self, topic: str, msg: str, retained: bool):
        """
        Take care of HA messages and routing appropriately...
        """
        jmsg = json.loads(msg)
        # just assume it worked.... (will we crash our tasks if we get a bad message? that should be protected right?)
        # (if it does, put a try/finally in the top level message handler like normal please!)
        if "light" in topic:
            if jmsg["state"] == "OFF":
                self.app.lights.off()
                return
            # ok, on, or effects?
            effect = jmsg.get("effect", None)
            if effect:
                for e, f in self.app.lights.known_patterns:
                    if effect == e:
                        return self.app.lights.run_pattern(e, f)
                print("should not be possible... out of date ha with app?!")
            self.app.lights.on_soft()
        else:
            print("Unhandled HA update?", jmsg)

    async def handle_messages(self):
        async for topic, msg, retained in self.mq.queue:
            print(f'Topic: "{topic.decode()}" Message: "{msg.decode()}" Retained: {retained}')
            asyncio.create_task(self.pulse())
            topic = topic.decode()
            msg = msg.decode()
            await self.handle_single_message(topic, msg, retained)

    async def handle_single_message(self, topic: str, msg: str, retained: bool):
        """Handle just a single message, allows returning nicely."""
        if topic.startswith(self.ha_prefix):
            return await self.handle_ha_message(topic, msg, retained)

        jmsg = None
        if "json" in topic:
            jmsg = json.loads(msg)
        # FIXME - lots of safety validation on messages please!
        # dispatch these all straight into their classes? or is control external?
        # FIXME - I'm pretty sure I end up with multiple tsks running :|
        if "lights" in topic:
            if "pattern" in topic:
                for pat, f in self.app.lights.known_patterns:  # (string, func...) tuples?
                    if pat in msg:
                        # we made run_pattern take kwargs, can we send it jmsg perhaps?
                        self.app.lights.run_pattern(pat, f)

            if "idle" in msg:
                print("(re)engaging idle lights")
                if self.app.lights.t_lights:
                    self.app.lights.cancel()
                self.app.lights.t_lights = asyncio.create_task(self.app.lights.run_idle_simple())
            if "off" in msg:
                if self.app.lights.t_lights:
                    self.app.lights.cancel()
                self.app.lights.off()
            if "on_soft" in msg:
                if self.app.lights.t_lights:
                    self.app.lights.cancel()
                self.app.lights.on_soft()
        if "lcd" in topic:
            if "line2" in topic:
                self.helper_status(2, msg, clear="clear" in topic)
        if "spider" in topic:
            if "restart" in topic:
                # you may want to set more params here yo... json is inevitable!
                if jmsg:
                    print("restarting pid with json message")
                    self.app.spider.restart_pid(
                        step_ms=jmsg.get("step_ms", None),
                        speed_limit=jmsg.get("speed_limit", None),
                        kp=jmsg.get("kp", None),
                        ki=jmsg.get("ki", None),
                        kd=jmsg.get("ki", None),
                        )
                else:
                    self.app.spider.restart_pid()
            if "off" in topic:
                self.app.spider.t_pid.cancel()
                self.app.motor.stop()
            if "speedlimit" in topic:
                param = float(msg)
                print("setting speed limit to ", param)
                self.app.spider.speed_limit = param
            if "moveabs" in topic:
                param = int(msg)
                self.helper_status(2, f"moving to: {param}")
                self.app.spider.move_to(param)
            if "movedelta" in topic:
                param = int(msg)
                dest = self.app.spider.pos_real + param
                self.helper_status(2, f"moving to: {dest}")
                self.app.spider.move_to(dest)
            if "resetzero" in topic:
                self.app.spider.pos_real = self.app.spider.pos_goal = 0
            if "dump" in topic:
                msg = "um, stuff?"


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
            self.helper_status(1, txt)

    async def up(self):
        """we want an mq up event, as it's great for re-doing subs..."""
        while True:
            await self.mq.up.wait()
            self.mq.up.clear()
            self.helper_led(2, True)
            txt = "mq good"
            print(txt)
            self.helper_status(1, txt)
            await self.mq.subscribe("helloween/cmd/#", 0)  # yeah, we actually aren't designing for a qos1 required environment
            await self.mq.subscribe("helloween/cmdjson/#", 0)  # yeah, we actually aren't designing for a qos1 required environment
            await self.mq.subscribe(f"{self.ha_prefix}/+/{self.nodeid}/set", 0)  # some examples have an extra piece between node and set?!
            await self.mq.publish(self.topic_state, "on", True)
            asyncio.create_task(self.update_hass())

    async def main_mq(self):
        print("starting async main!")
        try:
            await self.mq.connect(quick=True)
            # TODO - write our IP address to that line?
            my_ip = self.mq._sta_if.ifconfig()[0]
            txt = f"Conn: {my_ip}"
            #self.tft.text(self.font8, txt, 0, 120, self.colour_status)
            self.helper_status(0, txt)
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
            self.helper_status(1, f"{self.app.spider.pos_goal} / {self.app.spider.pos_real}")
            #await self.mq.publish(self.topic_status, f"{i}, outs: {self.mq_down_events}")
            await self.mq.publish(self.topic_status, self.generate_status_msg())



c = Core()
c.start()
# c.do_station()
print("ok, starting up now....")
c.do_mqtt()
print("shouldn't get here")

# here, we would then "import our app" and run it?
# webrepl or what?


## TODO: if it's 400ticks per RPM, tomorrow, run it for a minute, and see if you really get to a ~630*400 ticks?
## ok, it's night time, I could/should be working on the leds, on the rest of it's operation, the stats, the controls?