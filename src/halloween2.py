#!/usr/bin/env python
"""
Micropython halloween show, Ljósvallagata 30, 2023

Available:
* Spider on a string on a motor
* ws2812 lights.
* PIR sensor
* "radar" sensor
* Perhaps: speakers...

Intent is:
## While idle:
 * led strips around door play a cool/dark slow purply/green idle ripples

## When people detected coming towards doorway  (Updated, we're in reverse, motor doesn't like holding up permanently)
 * spider descends rapidly down
 * led strips switch to "agitated" with reds and oranges
 * Spider slowly re-ascends
 * led strips decay back to idle pattern

## Expected manual requirements
 * even if we get encoders in place, in time, we'll need a way to re-adjust the "position" of the spider
   so we don't get it all over the place  >> done
 * manual "start show" button >> done
 * manual override of the "idle" pattern
 * OTA?  We _might_ be ok with just webrepl and mpremote? (probably not, it's a "TODO" after mp1.20...)


## Stretch goals
 * statsd/whatever to track events, because, why not go overboard
 ** https://github.com/ssube/prometheus_express (and just straight grafana....)
 ** https://github.com/ssube/prometheus_express/pull/32 (for asyncio version)
 * or
 ** port https://github.com/jsocol/pystatsd/ to micropython (looks easy to port)
 ** https://github.com/WoLpH/python-statsd (not touched sine 2017 though..
 ** and needs graphite as well then...

 I _do_ feel that statsd style push is _probably_ less intrusive for this style of project
 as it doesn't need a full webserver interrupting things at arbitrary times, but... lets try shall we...

Initial mock of what the halloween show should do...

## Failures
We're disobeying our first rules about having control and OTA available first,
and using that to get the rest of it deployed.
Partly, this is because we don't even know what the control layer should really look like!


# Ok, so... what next....
* an actual motor control with position based on the encoder, so that it can drive the "right" amount to keep it in place?
 => we might end up having the spider on the ground, and leaps up?  so it can lower down instead?
* we really will need remote access to it...
* we can probably hardcode wifi AP though right?
 => Put it on a powerbank, hardcode tweak credentials, make sure it's reachable?
 => much less work than a wifi manager, which we'd need to "productize" it...
* ok, still need... websockets repl, or mqtt, or ... what?
* I quite like mqtt, I'm used to it...

"""
import time

try:
    import asynco
except:
    import uasyncio as asyncio

import json
import random

import machine
import encoder_portable
import mp_neopixel

import spider2
import icolorsys

class Board:
    """
    TODO - fix this up to match... one board or another
    TODO - use the boards/pins.csv you can use now that you have a proper repo?
    """
    MOTOR1 = machine.Pin(32, machine.Pin.OUT)
    MOTOR2 = machine.Pin(33, machine.Pin.OUT)
    ENCODER1 = machine.Pin(26)
    ENCODER2 = machine.Pin(27)
    STRIP = machine.Pin(25)
    #DETECTOR = machine.Pin(36, machine.Pin.IN)  # input only, but that's fine for this one
    PUSH_BUTTON = machine.Pin(17, machine.Pin.IN)
    DETECTOR_RADAR = machine.Pin(21, machine.Pin.IN)  # 36 was busted?!
    DETECTOR_PIR = machine.Pin(22, machine.Pin.IN)  # 36 was busted?!


class KEncoderPortable(encoder_portable.Encoder):
    pass

class KEncoder(machine.Encoder):
    pass


class KEncoder3:
    """
    Used for positioning feedback from the motor
    """
    def __init__(self, pin1, pin2):
        self.pin1 = pin1
        self.pin2 = pin2


# Fake motor includes encoder as well as motor. Normally these are separate...
class KFMotor():
    def __init__(self, pin1, pin2, **kwargs):
        self.mode = "IDLE"
        self.speed = 0

        self.position = 100
        # Oooh boi, do we run an asyncio runnable to advance position here...?

    def forward(self, speed=50):
        self.mode = "FORWARD"
        self.speed = speed

    def back(self, speed=50):
        self.mode = "BACKWARD"
        self.speed = speed

    def stop(self):
        """
        This does, one of the decay modes.  should probably look at being able to choose which.
        :return:
        """
        self.mode = "STOP"

    def __repr__(self):
        return f"KFMotor<{self.mode}@{self.speed} Position:{self.position}>"


class KMotor():
    """
    Targetting a DRV8833 style, with two PWM inputs.
    Some notes on the web say that lower freq is better for lower speeds? needs to experiment!
    (yes, 5000 is garbage, it barely starts, 150 is much better :)
    """
    def __init__(self, pin1, pin2, **kwargs):
        defs = dict(freq=25, decay="FAST")
        #kwargs = {**defs, **kwargs} # fixme - later?
        self.pwm_freq = kwargs.get("freq", defs["freq"])  # boo, we were trying to avoid dups...
        decay = kwargs.get("decay", defs["decay"])  # kwargs["decay"]
        self.pmax = 65535 # for mp vanilla 1.21.0
        ddecay = dict(SLOW=self.pmax, FAST=0)
        self.alt_state = ddecay.get(decay, ddecay["SLOW"])
        self.pin1 = pin1
        self.pin2 = pin2
        # You cannot recreate PWM, but we don't want to _start_ anything here...
        self.p1 = machine.PWM(self.pin1, self.pwm_freq, duty_u16=0)
        self.p2 = machine.PWM(self.pin2, self.pwm_freq, duty_u16=0)

    def percents_to_u16(self, percents: int) -> int:
        return (percents * self.pmax + 50) // 100

    # NOTE, this api does not let you simply slide speed up and down, if that matters?
    def forward(self, speed=50):
        self.p1.duty_u16(self.percents_to_u16(speed))
        self.p2.duty_u16(0)

    def back(self, speed=50):
        self.p1.duty_u16(0)
        self.p2.duty_u16(self.percents_to_u16(speed))

    def speed(self, speed: int=50):
        """Allows signed forwards/backwords automatically"""
        if speed >= 0:
            self.forward(speed)
        else:
            self.back(-speed)

    def stop(self):
        """stop, using initial options"""
        self.p1.duty_u16(self.alt_state)
        self.p2.duty_u16(self.alt_state)

    def stop_coast(self):
        """
        coast, aka fast decay
        :return:
        """
        self.p1.duty_u16(0)
        self.p2.duty_u16(0)

    def stop_brake(self):
        """
        brake, aka slow decay
        :return:
        """
        self.p1.duty_u16(self.pmax)
        self.p2.duty_u16(self.pmax)


class KPeopleSensor:
    """
    Wraps up whatever sensor we end up using, maybe even multiple...
    """
    def __init__(self, pin, name=None, trig=machine.Pin.IRQ_FALLING):
        self.pin = pin
        self.name = name
        self.found = asyncio.ThreadSafeFlag()  # From isr_rules.html....
        self.ev = asyncio.Event()
        self.pin.irq(self._handler, trigger=trig)
        self.mq = None
        self.mq_topic = None
        self.t_monitor = None

    def _handler(self, p):
        # I _should_ only get an IRQ when it actually falls, but have been unable to figure
        # out why I get extra... It works just fine
        #print("handler...", self.name, p.value())  # GAH WHY SO MUCH NOISE!
        self.found.set()

    def use_mq(self, mq, mq_topic_base):
        self.mq = mq
        self.mq_topic = mq_topic_base
        self.start_aio()  # will (re) start aio if necessary

    async def task_monitor(self):
        async def post_mq_update():
            if self.mq:
                await self.mq.publish(f"{self.mq_topic}/state", "ON")
            # update LCD screen as well?

        print("starting monitor for ", self.name)
        while True:
            await self.found.wait()
            self.ev.set()
            print(f"DET<{self.name}> found", self.pin.value())
            asyncio.create_task(post_mq_update())
        print("um, we finished?!", self.name)

    def start_aio(self):
        if self.t_monitor:
            self.t_monitor.cancel()
        self.t_monitor = asyncio.create_task(self.task_monitor())

class KActionWrapper:
    """
    Wraps up sources of action triggers.  Not happy with the name.
    We want to make "shows" be triggerable by one of any source:
    PIR, radar, manual button push, mqtt message, HASS event, etc
    However, we don't have asyncio.wait() in MP, so we have to wrap up all sources here...
    approach we're taking is a "add event" thingy?
    (Or just hard code it for now?)

    We're likely going to have to poll them though, so we have a step time.
    As we're doing this with low speed things, it can be pretty slow...
    """
    def __init__(self, step_ms=100):
        self.step_ms = step_ms
        self.sources = []

    async def wait(self):
        """Wait for the first of any of our sources"""
        while True:
            for s in self.sources:
                if s.is_set(): # FUCKing TSF doesn't have is_set!
                    s.clear()
                    return s
            await asyncio.sleep_ms(self.step_ms)

    def add_source(self, source):
        """source should be something that behaves like an ~~asyncio.ThreadSafeFlag~~ or an asyncio.Event"""
        self.sources.append(source)




class KLights:
    """
    Intended to encapuslate the pixel strip leds around the door frame
    """
    def __init__(self, strip: mp_neopixel.NeoPixel):
        self.np = strip
        self.np.ORDER = (0, 1, 2, 3)  # My ws2815 are actualyl rgb, not grb like classics.
        self.SCALE = 4
        self.config_max_v = 200  # use this to make a global, across effects master brightness...
        self.t_lights = None
        self.mq = None
        self.mq_topic = None
        # "our" purple/green...
        self.C_PURPLE = (158//self.SCALE, 50//self.SCALE, 168//self.SCALE)
        self.C_GREEN = (50//self.SCALE, 168//self.SCALE, 131//self.SCALE)
        self.C_RED = (230//self.SCALE, 0, 0)
        self.C_ORANGE = (227//self.SCALE, 98//self.SCALE, 0)

        self.known_patterns = [
            ("idle_simple", self.run_idle_simple),
            ("attack_simple1", self.run_attack_simple1),
            ("blue_dummy1", self.run_blue_dummy1),
            ("rainbow1", self.run_rainbow1),
            ("vagrearg1", self.run_vagrearg1),
            ("attack2", self.run_attack2),
            ("idle2", self.run_idle2),
        ]
        self.off()

    @staticmethod
    def MakeKLights():
        return KLights(mp_neopixel.NeoPixel(Board.STRIP, 300))

    def run_pattern(self, name, func, **kwargs):
        if self.t_lights:
            self.t_lights.cancel()
        self.helper_update_mq(dict(state="ON", effect=name))
        self.t_lights = asyncio.create_task(func(**kwargs))

    def run_pattern_by_name(self, name, **kwargs):
        func = None
        for pat, f in self.known_patterns:  # (string, func...) tuples?
            if name == pat:
                func = f
        if not func:
            raise IndexError("No light matching:" + name)
        self.run_pattern(name, func, **kwargs)

    def use_mq(self, mq, topic_base):
        """Provide the base topic that this should use for updates/states"""
        self.mq = mq
        self.mq_topic = topic_base
        # also, fire of an update
        # ummm, actually, we don't have state... just turnourselves off when we are requested to start using mq?
        # gud enuff for gubmint work...
        self.off()

    def helper_update_mq(self, mydict):
        """Let methods update mq, without boilerpalte"""
        if not self.mq:
            return
        async def blah():
            await self.mq.publish(f"{self.mq_topic}/state", json.dumps(mydict))
        asyncio.create_task(blah())

    def off(self):
        if self.t_lights:
            self.t_lights.cancel()
        self.helper_update_mq(dict(state="OFF", master_v=self.config_max_v))
        self.np.fill((0, 0, 0))
        self.np.write()

    def on_soft(self):
        if self.t_lights:
            self.t_lights.cancel()
        self.helper_update_mq(dict(state="ON", master_v=self.config_max_v))
        rgb_tungsten = 255, 214, 170
        h, s, v = icolorsys.RGB_2_HSV(rgb_tungsten)
        # now, use config master V limit...
        rgb = icolorsys.HSV_2_RGB((h, s, self.config_max_v))
        #self.np.fill((255 // self.SCALE, 210//self.SCALE, 105 // self.SCALE))
        self.np.fill(rgb)
        self.np.write()

    async def run_vagrearg1(self, step_ms=50):
        """Sample program from https://www.vagrearg.org/content/hsvrgb"""
        hue = 0
        val = 255
        val_max = self.config_max_v
        hue_max = 255
        direction = -3

        while True:
            # rotate hue circle
            hue += 1
            if hue > hue_max:
                hue = 0

            # vary value between 25-100% of value
            val += direction
            if val < val_max // 4 or val == val_max:
                direction = -direction  # reverse


            r, g, b = icolorsys.HSV_2_RGB((hue, 255, val))
            self.np.fill((r//4, g//4, b//4))  # limit to half brightness at least...
            self.np.write()
            await asyncio.sleep_ms(step_ms)

    async def run_rainbow1(self, step_ms=100):
        """
        just pick roygbiv colours
        divide length into equal segments of roygbiv
        anything left at the end will be left black,and we'll rotate into it...
        then... rotate?
        # FIXME - this one doesn't respect max V!
        :return:
        """
        # // 4 is to cut the brightness down so that I don't brown out my supply.... :)
        R = (255//4,0,0)
        O = (255//4,127//4,0)
        Y = (255//4,255//4,0)
        G = (0,255//4,0)
        B = (0,0,255//4)
        I = (75//4,0,130//4)
        V = (148//4,0,211//4)
        colours = [R, O, Y, G, B, I, V]
        chunk = self.np.n // len(colours)
        self.np.fill((0, 0, 0))
        for i, c in enumerate(colours):
            self.np[i*chunk:(i+1)*chunk] = c

        self.np.write()

        while True:
            rot_n = 1
            self.np.rotate(rot_n)
            self.np.write()
            await asyncio.sleep_ms(step_ms)

    async def run_blue_dummy1(self, segs=5):
        """
        divide total length into segs.
        for each seg, write triangular intensity, same colour...
        (needs hsl...)
        then, rotate each segment each iteration?
        :return:
        """
        b1 = (0//self.SCALE, 71//self.SCALE, 194//self.SCALE)
        while True:
            for n in range(self.np.n):
                pass # lol, this isn't ready
            self.np.fill(b1)

            await asyncio.sleep_ms(500)

    async def run_idle_simple(self):
        print("starting show idle1")
        while True:
            self.np.fill(self.C_PURPLE)
            self.np.write()
            #await asyncio.sleep(0.2)
            # for now, randomly select an increasing percentage to be
            myrange = [x for x in range(5, 40, 5)]
            myrange.extend(range(50, 0, -5))
            for x in myrange:
                selected = [random.randrange(0, self.np.n) for _ in range(x)]
                print("IDLE1 x ", len(selected))
                ## ideally, we want some variance in the next colour now though really...
                #[self.np.__setitem__(sel, self.C_GREEN) for sel in selected]
                for sel in selected:
                    #self.np[sel] = self.C_GREEN
                    self.np.set_pixel(sel, self.C_GREEN)
                self.np.write()
                # put them back before next selected set to be green...
                for sel in selected:
                    #self.np[sel] = self.C_PURPLE
                    self.np.set_pixel(sel, self.C_PURPLE)
                await asyncio.sleep_ms(500)
            # then go back down again... if we like this sort of thing...

    async def run_idle2(self):
        """
        We want this one to be the more ripply one.
        Fill to a random spot in the "purple" area, (so it's not always the same)
        Then, pick a random number of "nuclei" sort of like ~0-2 per meter?
        Those then over time ripple up towards the blue, with triangular around them...

        This isn't bad, but all the drops starting at the same time and growing at the same rate
        isn't ideal.
        Probably want a way of just saying, "add drop" and "step drop" each loop, but want to save this before
        hacking further...
        :return:
        """
        print("starting show idle2")

        BASE_PURPLE_H = (211, 255, self.config_max_v)
        BASE_CYAN_H = (127, 255, 5)  # starts dim
        LEDS_PER_M = 60
        STRIP_LEN = self.np.n // LEDS_PER_M
        MAX_NUCLEI = 2 * STRIP_LEN
        MIN_NUCLEI = 2
        MAX_DROP_WIDTH = 6  # "radius"
        NEW_BG_TIME = 5000  # ms between new background colour rotations.
        RIPPLE_SPEED_MS = 100  # we run the loop at this speed
        RIPPLE_EXPANSION = 5  # expand ripples every N iterations

        class Nuclei:
            def __init__(self, np, pos, color_hsv):
                self.np = np
                self.pos = pos
                self.h, self.s, self.v = color_hsv
                self.index = 0
                self.sub_index = 0

            def step(self):
                for i in range(self.index):
                    self.v += (self.index-i) * 30 + self.sub_index * 3
                    if self.v > 255:
                        self.v = 255
                    rgb = icolorsys.HSV_2_RGB((self.h, self.s, self.v))
                    self.np[self.pos+i] = rgb
                    self.np[self.pos-i] = rgb
                self.sub_index += 1
                if self.sub_index == RIPPLE_EXPANSION:
                    self.index += 1
                    self.sub_index = 0

        def random_near_h(h, s, v, spread=15):
            new_hue = random.randrange(h - spread, h + spread)
            return new_hue, s, v

        # A nucleii has a position, a base colour, and a "current step index"...
        # just add it to the tuple? nope. tuples are immutable..
        # and every iter, randomly add a new drop if count < max?
        # (in an insane world, we adjsut random chance to higher as we get closer to min... but fuck that)

        nuclei = []

        def make_new_nuclei():
            # make sure position will stay in bounds...
            n = random.randrange(1 + MAX_DROP_WIDTH, self.np.n - MAX_DROP_WIDTH - 1)  # I can't be arsed to count properly.
            col_h = random_near_h(*BASE_CYAN_H)
            return Nuclei(self.np, n, col_h)

        last_purple_h = BASE_PURPLE_H[0]
        last_purple_t = time.ticks_ms()
        dst = last_purple_h - 1  # force a change first time.
        while True:
            now = time.ticks_ms()
            if now - last_purple_t > NEW_BG_TIME:
                dst, _, _ = random_near_h(*BASE_PURPLE_H)
                #print("picking a new bg colour:  ", dst)
                last_purple_t = now  # make sure you dont't make the time step shorter than how long it takes to fade!

            if last_purple_h != dst:
                if last_purple_h > dst:
                    last_purple_h -= 1
                else:
                    last_purple_h += 1
            self.np.fill(icolorsys.HSV_2_RGB((last_purple_h, BASE_PURPLE_H[1], BASE_PURPLE_H[2])))

            if len(nuclei) < MAX_NUCLEI:
                # randomly add a drop or not...
                # say 10% chance of new drop, as we run this relatively often?
                if random.randrange(0, 100) > 90:
                    nuclei.append(make_new_nuclei())
            if len(nuclei) < MIN_NUCLEI:
                nuclei.append(make_new_nuclei())

            for nuc in nuclei:
                nuc.step()

            # drop finished nucleii!
            nuclei = [nuc for nuc in nuclei if nuc.index < MAX_DROP_WIDTH]
            self.np.write()
            await asyncio.sleep_ms(RIPPLE_SPEED_MS)

    async def run_attack_simple1(self):
        """ Basic, getting started "attack" pattern...
        Can endlessly tweak the graphics, but get two running "modes" first...
        """
        choices = [self.C_RED, self.C_ORANGE]
        while True:
            #print("ACK!",)
            for n in range(self.np.n):
                #self.np[n] = random.choice(choices)
                self.np.set_pixel(n, random.choice(choices))
            self.np.write()
            await asyncio.sleep_ms(100)

    async def run_attack2(self):
        """
        An alternative..
        """
        choices = [self.C_RED, self.C_ORANGE]
        choices_hsv = [icolorsys.RGB_2_HSV(rgb) for rgb in choices]

        for n in range(self.np.n):
            rh, rs, rv = random.choice(choices_hsv)
            #self.np.set_pixel(n, random.choice(choices))
            self.np.set_pixel(n, icolorsys.HSV_2_RGB((rh, rs, self.config_max_v)))
        self.np.write()
        while True:
            for i in range(0, 5):
                await asyncio.sleep_ms(50)
                self.np.rotate(1)
                self.np.write()
            for i in range(0, 5):
                await asyncio.sleep_ms(50)
                self.np.rotate(-1)
                self.np.write()

class KApp():
    """
    Holy shit, I still want to do neat things like put it on the wifi
    so i can do shit with my phone....

    # Um. need to separate the understanding of tasks that we want to wait for (like moving objects)
    and tasks that just start and stay there, like keeping lights in certain modes...

    I also need lots of helper bits for manual interation and debugging!
    """
    def __init__(self):
        self.motor = KMotor(Board.MOTOR1, Board.MOTOR2)
        self.mencoder = KEncoder(0, Board.ENCODER1, Board.ENCODER2)
        self.spider = spider2.Spider2(self.motor, self.mencoder)
        self.lights = KLights(mp_neopixel.NeoPixel(Board.STRIP, 300))
        self.people_sensor_rad = KPeopleSensor(Board.DETECTOR_RADAR, "rad", trig=machine.Pin.IRQ_RISING)
        self.people_sensor_pir = KPeopleSensor(Board.DETECTOR_PIR, "pir", trig=machine.Pin.IRQ_RISING)
        self.people_sensor_button = KPeopleSensor(Board.PUSH_BUTTON, "btn", trig=machine.Pin.IRQ_FALLING)
        self.people_sensor_rad.start_aio()
        self.people_sensor_pir.start_aio()
        self.people_sensor_button.start_aio()
        self.ev_manual_trigger = asyncio.Event()
        # Do I make a single object that contains both to wait on either?
        self.action_wrapper = KActionWrapper()
        self.action_wrapper.add_source(self.people_sensor_rad.ev)
        self.action_wrapper.add_source(self.people_sensor_pir.ev)
        self.action_wrapper.add_source(self.people_sensor_button.ev)
        self.action_wrapper.add_source(self.ev_manual_trigger)

        self.t_auto = None

    async def wait_for_stuff(self):
        """
        I think this needs a check on some sort of enable flag?
        I'm pretty sure we need to make sure there's only one of these too?
        :return:
        """

        while True:
            print("(RE)starting outer loop")
            #await self.start_over()
            #t_idle = asyncio.create_task(self.lights.run_idle_simple())
            #self.lights.run_pattern_by_name("idle_simple")
            self.lights.run_pattern_by_name("idle2")

            # lol, no .wait in microptyhon...
            # await asyncio.wait([
            #     self.people_sensor_rad.found.wait(),
            #     self.people_sensor_pir.found.wait(),
            # ], return_when=asyncio.FIRST_COMPLETED)
            # so we'll just wait for one for right now...
            #await self.people_sensor_rad.found.wait()
            x = await self.action_wrapper.wait()
            # notify internet about scaring another person?!!!
            print("main found a person!")
            #t_attack = asyncio.create_task(self.lights.run_attack_simple1())
            #self.lights.run_pattern_by_name("attack_simple1")
            self.lights.run_pattern_by_name("attack2")
            self.spider.add_move_q(spider2.MoveTask(800))
            self.spider.add_move_q(spider2.MoveTask(200, hold_time_ms=200))
            self.spider.add_move_q(spider2.MoveTask(600))

            print("running attack mode for XXX seconds before sleeping before allowing a new person")
            await asyncio.sleep(10)
            self.spider.move_to(0)  # resting...

    def auto_restart(self):
        self.auto_stop()
        self.t_auto = asyncio.create_task(self.wait_for_stuff())

    def auto_stop(self):
        if self.t_auto:
            self.lights.off()
            self.t_auto.cancel()



def t3():
    """This works fine, no weird spurious irq handlers. so why do we get it with our own app?!"""
    loop = asyncio.get_event_loop()
    app = KApp()
    loop.run_until_complete(app.wait_for_stuff())


def t5():
    loop = asyncio.get_event_loop()
    app = KApp()
    app.people_sensor_rad.start_aio()
    app.people_sensor_pir.start_aio()
    async def wot():
        while True:
            print("bleh")
            await asyncio.sleep_ms(2000)
    loop.run_until_complete(wot())

def tlights(pattern):
    """ Lets you test light pattens without the whole flash / mq loop"""
    #app = KApp()
    #app.lights.off()
    lights = KLights.MakeKLights()
    found = False
    for pat, f in lights.known_patterns:  # (string, func...) tuples?
        if pat in pattern:
            lights.run_pattern(pat, f)
            found = True
    if not found:
        raise IndexError("No light matching in ", lights.known_patterns)
    async def wot():
        while True:
            # print("bleh")
            await asyncio.sleep_ms(2000)

    try:
        asyncio.run(wot())
    finally:
        print("Making sure we killed all our dangling tasks from last call ;)")
        asyncio.new_event_loop()

