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

## When people detected coming towards doorway
 * spider descends rapidly down
 * led strips switch to "agitated" with reds and oranges
 * Spider slowly re-ascends
 * led strips decay back to idle pattern

## Expected manual requirements
 * even if we get encoders in place, in time, we'll need a way to re-adjust the "position" of the spider
   so we don't get it all over the place
 * manual "start show" button
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

try:
    import asynco
except:
    import uasyncio as asyncio

import random

import machine
import encoder_portable
import neopixel

import spider2

class Board:
    """
    TODO - fix this up to match... one board or another
    TODO - use the boards/pins.csv you can use now that you have a proper repo?
    """
    MOTOR1 = machine.Pin(32, machine.Pin.OUT)
    MOTOR2 = machine.Pin(33, machine.Pin.OUT)
    ENCODER1 = machine.Pin(21)
    ENCODER2 = machine.Pin(22)
    STRIP = machine.Pin(17)
    DETECTOR = machine.Pin(36, machine.Pin.IN)  # input only, but that's fine for this one



class KEncoder(encoder_portable.Encoder):
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
    def __init__(self, pin):
        self.pin = pin
        self.found = asyncio.ThreadSafeFlag()  # From isr_rules.html....
        self.pin.irq(self._handler, trigger=machine.Pin.IRQ_FALLING)

    def _handler(self, p):
        print("handler...", p.value())
        self.found.set()

class KLights:
    """
    Intended to encapuslate the pixel strip leds around the door frame
    """
    def __init__(self, strip: neopixel.NeoPixel):
        self.np = strip
        self.np.ORDER = (0, 1, 2, 3)  # My ws2815 are actualyl rgb, not grb like classics.
        self.available = asyncio.Event()
        self.irq = asyncio.Event()
        self.available.set()
        self.SCALE = 4
        # "our" purple/green...
        self.C_PURPLE = (158//self.SCALE, 50//self.SCALE, 168//self.SCALE)
        self.C_GREEN = (50//self.SCALE, 168//self.SCALE, 131//self.SCALE)
        self.C_RED = (230//self.SCALE, 0, 0)
        self.C_ORANGE = (227//self.SCALE, 98//self.SCALE, 0)

    def off(self):
        self.np.fill((0, 0, 0))
        self.np.write()

    async def _inner_show_fake(self):
        lights = "purplegreenpurplegreen"

        lstr = ''.join(random.choice((str.upper, str.lower))(c) for c in lights)
        print(f"lights: {lstr}")
        await asyncio.sleep_ms(100)

    async def _inner_show_idle1(self):
        print("starting show idle1")
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
            for sel in selected: self.np[sel] = self.C_GREEN
            self.np.write()
            # put them back before next selected set to be green...
            for sel in selected: self.np[sel] = self.C_PURPLE
            await asyncio.sleep_ms(500)
        # then go back down again... if we like this sort of thing...

    async def _inner_show_idle2(self):
        """
        Super fancy, select a few "nodes"
        then, normal distribution a few neighbours up the brightness of the alt-colour..
        ie, lots of little "pools" of colour appearing and disappearing...
        :return:
        """
        pass

    async def _inner_show_attack_fake(self):
        lights = "angry red orange attack"
        lstr = ''.join(random.choice((str.upper, str.lower))(c) for c in lights)
        print(f"lights: {lstr}")
        await asyncio.sleep(0.2)

    async def _inner_show_attack1(self):
        """ Basic, getting started "attack" pattern...
        Can endlessly tweak the graphics, but get two running "modes" first...
        """
        choices = [self.C_RED, self.C_ORANGE]
        #print("ACK!",)
        for n in range(self.np.n): self.np[n] = random.choice(choices)
        self.np.write()
        await asyncio.sleep_ms(100)

    async def run_idle_simple(self):
        """
        Just the wrapper, events and stuff are now external...
        :return:
        """
        while True:
            await self._inner_show_idle1()

    async def run_attack_simple(self):
        """no events, just the wrapper"""
        while True:
            await self._inner_show_attack1()

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
        self.mencoder = KEncoder(Board.ENCODER1, Board.ENCODER2)
        self.spider = spider2.Spider2(self.motor, self.mencoder)
        self.lights = KLights(neopixel.NeoPixel(Board.STRIP, 300))
        self.people_sensor = KPeopleSensor(Board.DETECTOR)

    async def set_position(self, position):
        """
        Intended to help reset things... when you have reset things, but need to
        re-set encoders / motors after losing all your state ...
        """
        pass

    async def start_over(self):
        # await for these...?
        asyncio.gather(
            self.spider.move_to(100),
            self.lights.run_idle(),
        )
        # FIXME - reinitialize sensors? whatever?

    async def show1(self):
        """ wait til everyone's in place """
        # In parallel, switch the lighting mode and start the spider moving
        # FIXME - sooo, am I meant to be cancelling the existing task within the lights class there?
        asyncio.gather(
            self.lights.run_attack1(),
            self.spider.move_to(0, 100)
        )

    async def wait_for_stuff(self):
        # Initialize sensors,
        # fuck, I bit off more async python than I'm really ready for didn't I :)
        # pseudocode ftw???
        while True:
            print("(RE)starting outer loop")
            #await self.start_over()
            t_idle = asyncio.create_task(self.lights.run_idle_simple())
            await self.people_sensor.found.wait()
            t_idle.cancel()
            # notify internet about scaring another person?!!!
            print("main found a person!")
            # add a lighting task here...
            t_attack = asyncio.create_task(self.lights.run_attack_simple())
            print("running attack mode for XXX seconds before sleeping before allowing a new person")
            await asyncio.sleep(5)
            t_attack.cancel()




def t3():
    loop = asyncio.get_event_loop()
    app = KApp()
    loop.run_until_complete(app.wait_for_stuff())


def t4():
    loop = asyncio.get_event_loop()
    app = KApp()
    loop.run_until_complete(app.spider.move_to(500))
    print("ok loop finished stop sotp stop")
    app.motor.stop()
    # ok, assume position is at "zero"

