"""
Main, should just consider the "non application" pieces...
(should)
"""

try:
    import secrets
except ImportError:
    print("no wifi config, run an AP mode I guess....")
    pass


import asyncio
import binascii
import deflate
import gc
import io
import json
import machine
import network
import os
import requests
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

        c["will"] = (self.topic_state, "offline", True, 0)

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
        Publish all the discovery information required for Home Assistant.
        Also, notify all components of the MQ details they need for feeding status back.
        
        Intent is for... at least.
        * one "switch" for master lights on/off  <done>
        * one "switch" for master motor on/off <done>
        * one button to reset positions for spider...  <done>

        extra goals
        * "slider"  for "direct" motor control (have a box with sliders, done)
        * drop down or pattern selector or whatever or free text to set light patterns...  <done>
        *

        TODO - must uids be unique within a node? or unique across the entire HASS environment?
        (I don't feel like making real guids or anything...)
        """
        retain = True
        qos = 0
        # Note, we use "nodeid" but for ha purposes, this is the "objectid"
        # base message...
        msg = dict(
            cmd_t="~/set",
            stat_t="~/state",
            schema="json",
            availability_topic=self.topic_state,
            dev=dict(mf="Ekta Labs",
                     name="hell-o-ween",
                     model="proto1",
                     sw_version="0.3",
                     identifiers=self.nodeid),  # Same nodeid again?
        )

        msg["name"] = "ze lights"
        uid = "uid_strip_lights"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/light/{self.nodeid}/{uid}"
        msg["~"] = base
        msg["effect"] = True
        msg["effect_list"] = [x[0] for x in self.app.lights.known_patterns]
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)
        # We _also_ need to tell the modules about their mq now!
        self.app.lights.use_mq(self.mq, base)
        del msg["effect"]
        del msg["effect_list"]

        ## people sensors  This one works, with expiry and stuff, just the detector itself is busted.
        msg["name"] = "people detector rad"
        uid = "uid_people_detector_rad"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/sensor/{self.nodeid}/{uid}"
        msg["~"] = base
        msg["expire_after"] = 10
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)
        self.app.people_sensor_rad.use_mq(self.mq, base)

        msg["name"] = "people detector pir"
        uid = "uid_people_detector_pir"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/sensor/{self.nodeid}/{uid}"
        msg["~"] = base
        msg["expire_after"] = 10
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)
        self.app.people_sensor_pir.use_mq(self.mq, base)

        msg["name"] = "people detector button"
        uid = "uid_people_detector_btn"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/sensor/{self.nodeid}/{uid}"
        msg["~"] = base
        msg["expire_after"] = 10
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)
        self.app.people_sensor_btn.use_mq(self.mq, base)

        msg["name"] = "In Position"
        uid = "uid_in_position"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/sensor/{self.nodeid}/{uid}"
        msg["~"] = base
        msg["expire_after"] = 10
        msg["stat_t"] = f"{self.ha_prefix}/sensor/{self.nodeid}/motor_state/state"
        msg["value_template"] = "{{value_json.in_position}}"
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)

        del msg["expire_after"]


        ### Button to reset positions
        msg["name"] = "reset position"
        uid = "uid_btn_reset"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/button/{self.nodeid}/{uid}"
        msg["~"] = base
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)

        msg["name"] = "Up 100"
        uid = "uid_btn_up100"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/button/{self.nodeid}/{uid}"
        msg["~"] = base
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)

        msg["name"] = "Down 100"
        uid = "uid_btn_down100"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/button/{self.nodeid}/{uid}"
        msg["~"] = base
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)

        msg["name"] = "Trigger Person"
        uid = "uid_btn_manual_trigger"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/button/{self.nodeid}/{uid}"
        msg["~"] = base
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)

        msg["name"] = "Test Action"
        uid = "uid_btn_test_action"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/button/{self.nodeid}/{uid}"
        msg["~"] = base
        await self.mq.publish(f"{base}/config", json.dumps(msg), retain, qos)

        ### Top level motor switch...
        msg["name"] = "motor master"
        uid = "uid_sw_mmaster"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/switch/{self.nodeid}"
        msg["stat_t"] = f"{self.ha_prefix}/sensor/{self.nodeid}/motor_state/state"
        msg["cmd_t"] = f"~/{uid}/set"
        msg["value_template"] = "{{value_json.master}}"
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)

        # this makes a switch with no state, but can still send events?
        msg["name"] = "auto enable"
        uid = "uid_sw_auto_enable"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/switch/{self.nodeid}"
        del msg["stat_t"] # = f"{self.ha_prefix}/sensor/{self.nodeid}/motor_state/state"
        msg["cmd_t"] = f"~/{uid}/set"
        del msg["value_template"] # = "{{value_json.master}}"
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)

        ## motor numbers too please...
        ## FIXME - it's probably worth having a whole separate routine for the motor params, to avoid this crap
        # we probably want to have these get their state from a shared message with position or something
        # so I don't have to spam all those messages separately?
        msg["name"] = "pid term P"
        uid = "uid_termp"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/number/{self.nodeid}"
        msg["stat_t"] = f"{self.ha_prefix}/sensor/{self.nodeid}/motor_state/state"
        msg["cmd_t"] = f"~/{uid}/set"
        msg["value_template"] = "{{value_json.kp}}"
        msg["min"] = 0
        msg["max"] = 5
        msg["mode"] = "box"
        msg["step"] = 0.01
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)
        msg["name"] = "pid term I"
        uid = "uid_termi"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/number/{self.nodeid}"
        msg["stat_t"] = f"{self.ha_prefix}/sensor/{self.nodeid}/motor_state/state"
        msg["cmd_t"] = f"~/{uid}/set"
        msg["value_template"] = "{{value_json.ki}}"
        msg["min"] = 0
        msg["max"] = 1
        msg["mode"] = "box"
        msg["step"] = 0.001
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)
        msg["name"] = "pid term D"
        uid = "uid_termd"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/number/{self.nodeid}"
        msg["stat_t"] = f"{self.ha_prefix}/sensor/{self.nodeid}/motor_state/state"
        msg["cmd_t"] = f"~/{uid}/set"
        msg["value_template"] = "{{value_json.kd}}"
        msg["min"] = 0
        msg["max"] = 1
        msg["mode"] = "box"
        msg["step"] = 0.001
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)
        msg["name"] = "position goal"
        uid = "uid_pos_goal"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/number/{self.nodeid}"
        msg["stat_t"] = f"{self.ha_prefix}/sensor/{self.nodeid}/motor_state/state"
        msg["cmd_t"] = f"~/{uid}/set"
        msg["value_template"] = "{{value_json.goal}}"
        msg["min"] = -10000
        msg["max"] = 10000
        msg["mode"] = "box"
        msg["step"] = 5
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)
        msg["name"] = "master_v"
        uid = "uid_master_v"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/number/{self.nodeid}"
        msg["stat_t"] = f"{self.ha_prefix}/light/{self.nodeid}/uid_strip_lights/state"
        msg["cmd_t"] = f"~/{uid}/set"
        msg["value_template"] = "{{value_json.master_v}}"
        msg["min"] = 0
        msg["max"] = 255
        msg["mode"] = "slider"
        msg["step"] = 1
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)

        del msg["min"]
        del msg["max"]
        del msg["mode"]
        del msg["step"]

        msg["name"] = "position real"
        uid = "uid_pos_real"
        msg["unique_id"] = uid
        base = f"{self.ha_prefix}/sensor/{self.nodeid}"
        msg["stat_t"] = f"~/motor_state/state"
        msg["value_template"] = "{{value_json.position}}"
        msg["~"] = base
        await self.mq.publish(f"{base}/{uid}/config", json.dumps(msg), retain, qos)


        # Reset stat_t/cmd_t too!
        msg["cmd_t"] = "~/set"
        msg["stat_t"] = "~/state"
        self.app.spider.use_mq(self.mq, f"{base}/motor_state")

    async def handle_ha_message(self, topic: str, msg: str, retained: bool):
        """
        Take care of HA messages and routing appropriately...
        """
        # just assume it worked.... (will we crash our tasks if we get a bad message? that should be protected right?)
        # (if it does, put a try/finally in the top level message handler like normal please!)
        if topic.startswith(f"{self.ha_prefix}/light"):
            if "uid_strip_lights" in topic:
                jmsg = json.loads(msg)
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
                print("UNHANDLED LIGHTS")
        elif topic.startswith(f"{self.ha_prefix}/switch"):
            if "uid_sw_mmaster" in topic:
                self.app.spider.enable(msg == "ON")
            elif "uid_sw_auto_enable" in topic:
                if msg == "ON":
                    self.app.auto_restart()
                else:
                    self.app.auto_stop()
            else:
                print("UNHANDLED SWITCH")
        elif topic.startswith(f"{self.ha_prefix}/button"):
            print("handling button from HA:")
            if "uid_btn_up100" in topic:
                pos = self.app.spider.pos_real # hrm, goal?
                self.app.spider.move_to(pos + 100)
                self.app.spider.restart_pid()
            elif "uid_btn_down100" in topic:
                pos = self.app.spider.pos_real
                self.app.spider.move_to(pos - 100)
                self.app.spider.restart_pid()
            elif "uid_btn_reset" in topic:
                self.app.spider.pos_real = self.app.spider.pos_goal = 0
            elif "uid_btn_manual_trigger" in topic:
                self.app.ev_manual_trigger.set()
            elif "uid_btn_test_action" in topic:
                ### Whateve we feel like right now.
                print("ok, karls test action...")
                self.app.spider.add_move_q_raw(800)
                self.app.spider.add_move_q_raw(0)

            else:
                print("UNHANDLED BUTTON")
        elif topic.startswith(f"{self.ha_prefix}/number"):
            if "uid_termp" in topic:
                term = float(msg)
                self.app.spider.restart_pid(kp=term)
            elif "uid_termi" in topic:
                term = float(msg)
                self.app.spider.restart_pid(ki=term)
            elif "uid_termd" in topic:
                term = float(msg)
                self.app.spider.restart_pid(kd=term)
            elif "uid_pos_goal" in topic:
                term = int(msg)
                self.app.spider.move_to(term)
            elif "uid_master_v" in topic:
                term = int(msg)
                self.app.lights.config_max_v = term
            else:
                print("UNHANDLED NUMBER")
        else:
            print("Unhandled HA prefix entirely?", msg)

    async def handle_messages(self):
        async for topic, msg, retained in self.mq.queue:
            #print(f'Topic: "{topic.decode()}" Message: "{msg.decode()}" Retained: {retained}')
            asyncio.create_task(self.pulse())
            topic = topic.decode()
            msg = msg.decode()
            #try:
            await self.handle_single_message(topic, msg, retained)
            #except Exception as e:
            #    print(f"internal message handler crashed, protecting!", e)

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
        if "system" in topic:
            print("ok, working wuith a system topic?")
            chunks = topic.split("/")
            if chunks[3] == "reboot":
                machine.reset()
            if chunks[3] == "rebootsoft":
                machine.soft_reset()
            if chunks[3] == "file":
                await self.handle_mqtt_file(chunks[4], chunks[5], msg)

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
            if "movetask" in topic:
                chunks = msg.split(",")
                params = [int(x) for x in chunks]
                self.app.spider.add_move_q_raw(*params)
            if "resetzero" in topic:
                self.app.spider.pos_real = self.app.spider.pos_goal = 0
            if "dump" in topic:
                msg = "um, stuff?"

    async def handle_mqtt_file(self, action, name, data):
        """lol, you trust your local network right?"""
        gc.collect()
        if action == "new":
            # MemoryError: memory allocation failed, allocating 24877 bytes
            print(f"creating {name} with {len(data)} bytes..")
            with open(name, "w") as f:
                f.write(data)
        elif action == "newgz":
            # memory alloc failed, allocated 32k...
            with deflate.DeflateIO(io.BytesIO(data), deflate.GZIP) as d:
                with open(name, "w") as f:
                    f.write(d.read())
        elif action == "newhttp":
            # payload is URL..  This way works at least!
            r = requests.get(data, headers={})
            print("fetched http..")
            if r.status_code == 200:
                with open(name, "w") as f:
                    while True:
                        n = r.raw.read(1024)
                        f.write(n)
                        print("rx chunk: ", len(n))
                        if len(n) != 1024:  # even sized files will hit this? who cares!
                            break
            else:
                print("request failed: ", r)
            r.close()
        elif action == "rm":
            os.remove(name)
            print(f"removed {name}")
        elif action == "cat":
            with open(name, "r") as f:
                blob = f.read()
                await self.mq.publish(f"{self.topic_status}/system/file/{name}", blob)
        elif action == "list":
            print("attempting to list...")
            files = os.listdir()
            for f in files:
            #    print("lkisting?", x)
                await self.mq.publish(f"{self.topic_status}/system/list", f)
        else:
            print("Unhandled mqtt file action")

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
            # no, just accept node + "entity" uids..
            #await self.mq.subscribe(f"{self.ha_prefix}/+/{self.nodeid}/set", 0)
            await self.mq.subscribe(f"{self.ha_prefix}/+/{self.nodeid}/+/set", 0)
            await self.mq.publish(self.topic_state, "online", True)
            asyncio.create_task(self.update_hass())
            self.app.auto_restart()

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

        async def xxx_unusuable():
            # mp doesn't have all_tasks, nor names on tasks...
            # so forget about doing it like this...
            tn: asyncio.Task = asyncio.current_task()
            tset = asyncio.all_tasks()
            print(f"current: {tn}, {tn.get_name()}set={tset}")

        i = 0
        while True:
            await asyncio.sleep(2)
            i += 1
            #print("bleep bloop", self.app.spider.kp, self.app.spider.ki, self.app.spider.kd)
            print(f"lolicats RAD: {self.app.people_sensor_rad.pin.value()}, PIR: {self.app.people_sensor_pir.pin.value()}, BTN: {self.app.people_sensor_button.pin.value()}")
            self.helper_status(1, f"{self.app.spider.pos_goal} / {self.app.spider.pos_real}")
            #await self.mq.publish(self.topic_status, f"{i}, outs: {self.mq_down_events}")
            #await self.mq.publish(self.topic_status, self.generate_status_msg())



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