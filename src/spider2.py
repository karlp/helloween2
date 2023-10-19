"""
Smaller test case for exploring the motor a little more
"""
import asyncio
import collections
import json
import socket
import struct
import time

import halloween2

import machine


# monkey patching to glory..
def deque_clear(d):
    empty = False
    while not empty:
        try:
            d.popleft()
        except IndexError:
            empty = True


class MoveTask:
    def __init__(self, position, speed_limit=None, hold_time_ms=0):
        self.position = position
        self.speed_limit = speed_limit
        self.hold_time_ms = hold_time_ms

class Spider2:
    """
    "spider" is perhaps a misnomer, this is more the actual pairing of the motor and encoder,

    """
    def __init__(self, motor: halloween2.KMotor, encoder: halloween2.KEncoder):
        self.motor = motor
        self.encoder = encoder
        # experimentall, I get ~400 encoder pips per rpm.  aliexpress says it's 11 per rev, but that's
        # before gearing? Implies my gearing ratio is ~36?  Measured gear case is 21mm  Most internet
        # shops imply that my gear case should be 19mm, and have a ratio of 9.6, but also all say 11 per rev?
        # weird as shit.  Use my measured empirical data first I suppose...
        # None of it matters anyway, until/unless I want to get to a point of expressing
        # commands in terms of actual distance to move.

        self.master_enable = False

        self.move_q = collections.deque((), 10)
        self.move_task: MoveTask = None
        self.pos_goal = 0
        self.in_position = True
        self.limits_hit = False
        self.speed_limit = 1
        self.step_ms = 5

        self.e_prev = 0
        self.eint = 0

        self.t_pid = None
        self.t_soft_limits = None
        # Defaults empirically determined for the raw axel flag...
        #pid= 0.8/0.001/0.001 nope..

        # Updates with real spider. These work, but always settle low, presumably because the motor can't
        # give enough to make smaller adjustments?  We can just allow more slop in our measurements though
        # and call it good, as these params result in decent "jiggle" for the spider, but not wildly slewing motors.
        #
        self.kp = 0.8
        self.ki = 0.01
        self.kd = 0.02

        self.mq = None
        self.mq_topic = None

    @property
    def pos_real(self):
        return self.encoder.value()

    @pos_real.setter
    def pos_real(self, value):
        self.encoder.value(value)

    def enable(self, val: bool):
        self.master_enable = val
        if self.master_enable:
            self.restart_pid()
        else:
            if self.t_pid:
                self.t_pid.cancel()
            self.motor.stop_brake()

    def add_move_q(self, task: MoveTask):
        self.move_q.append(task)

    def add_move_q_raw(self, position, max_speed=None, hold_ms=0):
        """
        Appends a position to the move queue.
        :param position:
        :param max_speed:
        :param hold_ms:
        :return:
        """
        mt = MoveTask(position, max_speed, hold_ms)
        self.add_move_q(mt)

    def move_to(self, position):
        """
        Requests a move to an absolute position
        Empties any existing move queue.
        """
        #self.move_q.clear() # not in micropython...
        deque_clear(self.move_q)
        self.add_move_q(MoveTask(position))

    def soft_limits(self, max, min, enable=True):
        """
        Enable an asyncio task that monitors the limits
        If the limits are hit, the motor is stopped,
        and if a pid control task is running, it's cancelled as well.
        this is very _soft_ however, don't rely on this by itself!
        (I think there's more corners here to work out!)
        """
        async def t_limit_monitor():
            while True:
                if self.pos_real >= max or self.pos_real <= min:
                    print("SOFT LIMITS HIT!")
                    self.motor.stop_brake()
                    if self.t_pid:
                        self.t_pid.cancel()
                    self.limits_hit = True
                    break
                await asyncio.sleep_ms(500)
            print("finished monitor task")

        self.limits_hit = False
        if self.t_soft_limits:
            self.t_soft_limits.cancel()
            del self.t_soft_limits
        if enable:
            self.t_soft_limits = asyncio.create_task(t_limit_monitor())

    async def maintain_position(self):
        """Uses a PID loop to maintain any given position"""
        MIN_MOTOR_THRESHOLD = 8 // 2 # so, it needs 8 to turn it frrom still, but can we go a bit lower when we're running?
        CLOSE_ENOUGH = 25
        last = time.ticks_ms() - self.step_ms  # just for initial condition

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        addr = socket.getaddrinfo("192.168.88.124", 4242)[0][-1]
        def trace_udp(now, pos, goal, out):
            try:
                b = struct.pack("<iiif", now, pos, goal, out)
                sock.sendto(b, addr)
            except:
                # We've hit OSError: [Errno 12] ENOMEM here, and we do _not_ want task death!
                pass

        t_hold_time = 0
        while True:
            now = time.ticks_ms()
            delta_t = now - last
            # if delta_t > self.step_ms * 2:
            #     print("long loop: ", delta_t)
            last = now
            pos = self.pos_real

            # if we don't have a current task...
            if not self.move_task:
                # try and get a new movement task
                try:
                    self.move_task: MoveTask = self.move_q.popleft()
                    self.pos_goal = self.move_task.position
                    print("new task pos: ", self.move_task.position)
                    t_hold_time = 0
                except IndexError:
                    # ok, no new position goals then, carry on.
                    pass

            e = self.pos_goal - pos
            # ideally, we should get a real time here, rather than assuming asyncio gave us precise timings?
            # Could use real time here?
            #delta_ts = self.step_ms / 1000  # careful, either always use ms, or always seconds....
            delta_ts = delta_t / 1000
            dedt = (e - self.e_prev) / delta_ts
            self.eint = self.eint + e * delta_ts

            # in_position is only used for a flag in HASS, for deciding when to stop spewing UDP
            # and for deciding when a task is "done" so expanding the delta is ok, it will still
            # chatter, we don't need to pid tune further
            self.in_position = abs(e) <= CLOSE_ENOUGH and abs(self.e_prev) <= CLOSE_ENOUGH
            if self.in_position:
                # yeah baby, this is enough, just stop here.  pid tuning sounds gross
                # we still have encoder absolute positioning, so we still know where we are _truly_
                # and can still use precise numbers to always move to "close enough" to the same place time after time
                if self.move_task is not None:
                    t_hold_time += delta_t
                    if t_hold_time >= self.move_task.hold_time_ms:
                        self.move_task = None
                        t_hold_time = 0
                out = 0
            else:
                out = self.kp * e + self.ki * self.eint + self.kd * dedt
                # out = kkp * e + self.ki * self.eint + self.kd * dedt

            # so, we may have set a slow speed as we narrow in our final goal.
            # but, as we know, lowest speeds won't even turn the motor, so we need push it up.
            # but, we don't want to just lift up the slow speeds, so we need to remap by our
            # known minimum range.
            # but, shortcut, can we just add the starting threshold as a fixed offset??
            # out += MIN_MOTOR_THRESHOLD if out > 0 else -MIN_MOTOR_THRESHOLD
            # no, that didn't work well...

            # potentially, if e is -ve, we might need _small_ positive to let it fall slowly?
            if out > 0 and out < MIN_MOTOR_THRESHOLD:
                out = MIN_MOTOR_THRESHOLD
            if out < 0 and out > -MIN_MOTOR_THRESHOLD:
                out = -MIN_MOTOR_THRESHOLD  # FIXME actually, maybe don't have this when we're going down?
            # limit down speed, we want to lower, not drop...
            if out < 0 and out < -10:
                out = -10

            # range clamp to +- 100
            if out > 100 * self.speed_limit:
                out = 100 * self.speed_limit
            if out < -100 * self.speed_limit:
                out = -100 * self.speed_limit

            if self.move_task and self.move_task.speed_limit is not None:
                if out > 0 and out > self.move_task.speed_limit:
                    out = self.move_task.speed_limit
                if out < 0 and out < -self.move_task.speed_limit:
                    out = -self.move_task.speed_limit
            #print("speed: ", out)  # you can scan this for overshoot if you like, but it's spammy
            # This is absolutely not fast enough
            # if self.mq:
            #     asyncio.create_task(self.mq.publish("bin/pid", f"{now},{pos},{self.pos_goal},{out}"))
            if not self.in_position:
                trace_udp(now, pos, self.pos_goal, out)

            self.motor.speed(int(out))
            self.e_prev = e
            await asyncio.sleep_ms(self.step_ms)

    def restart_pid(self, step_ms=None, kp=None, ki=None, kd=None, speed_limit=None):
        """
        Start or restart pid loop...
        :param step_ms:
        :param kp:
        :param ki:
        :param kd:
        :param speed_limit: how much to scale down again.  Yes, this is like P, but with a max speed limit....
        :return:
        """
        # Use the internal defaults unless specified
        if step_ms:
            self.step_ms = step_ms
        if kp:
            self.kp = kp
        if ki:
            self.ki = ki
        if kd:
            self.kd = kd
        if speed_limit:
            self.speed_limit = speed_limit
        self.e_prev = 0
        if self.t_pid:
            self.t_pid.cancel()
        if self.master_enable:
            print("restarting with ", self.kp, self.ki, self.kd)
            self.t_pid = asyncio.create_task(self.maintain_position())
        else:
            print("Ignoring restart, master disabled")

    def use_mq(self, mq, mq_topic_base):
        self.mq = mq
        self.mq_topic = mq_topic_base
        self.start_aio()

    async def task_monitor(self):
        async def post_mq_update():
            if self.mq:
                msg = dict(master="ON" if self.master_enable else "OFF",
                           kp=self.kp,
                           ki=self.ki,
                           kd=self.kd,
                           position=self.pos_real,
                           in_position="ON" if self.in_position else "OFF",
                           goal=self.pos_goal,
                           task=dict(pos=self.move_task.position,
                                     speed=self.move_task.speed_limit,
                                     hold_ms=self.move_task.hold_time_ms) if self.move_task else {})
                await self.mq.publish(f"{self.mq_topic}/state", json.dumps(msg))

        # send one when we start
        await post_mq_update()
        last_send = time.time()
        last_pos = self.pos_real
        POS_DELTA_MIN = 5
        T_DELTA_MIN = 10
        while True:
            # Otherwise, send... either every 10? seconds, or if position has changed more than 5 in the last second?
            await asyncio.sleep(1)
            if abs(self.pos_real - last_pos) > POS_DELTA_MIN:
                await post_mq_update()
                last_send = time.time()
            if time.time() - last_send > T_DELTA_MIN:
                await post_mq_update()
                last_send = time.time()

    def start_aio(self):
        # so, we want an update with _present_ values... "real soon"
        # but then, we only want to bother sending stuff... when something's happening, and not too often?
        # use timeout to send stuff maybe?
        asyncio.create_task(self.task_monitor())



def MakeSpider():
    motor = halloween2.KMotor(machine.Pin.board.MOTOR1, machine.Pin.board.MOTOR2)
    #encoder = halloween2.KEncoderPortabl(machine.Pin.board.ENCODER1, machine.Pin.board.ENCODER2)
    encoder = halloween2.KEncoder(0, machine.Pin.board.ENCODER1, machine.Pin.board.ENCODER2)

    return Spider2(motor, encoder)



def sample(spider: Spider2, newpos=0, kp=0.6, ki=0, kd=0.005, speed_limit=1):
    """
    what do I want the consumer api to look like?

    I believe I want:
    to make a spider, and have it .start() which starts an asyncio task coro,
    and that coro just "maintains" it's "position" and you just tell the spider a new position when you want it to move.
    it should/must then have an event/or flag to check if it is "in position" (with some slop?)

    # this is very good for the raw axel with a flag on it....
    # time to try with the spider though?
    sample(s, 2000, kp=0.9, ki=0.001, kd=0.01)
    sample(s, 2000, kp=0.5, ki=0.003, kd=0.01, speed_limit=1) seems even better...
    """

    async def t_blah1():
        i = 0
        while not spider.in_position and not spider.limits_hit:
            i += 1
            print(f"tick: {i}, pos: {spider.pos_real}, in position? {spider.in_position}")
            await asyncio.sleep_ms(100)
        print("In position!, waiting for a bit to see it sit there....")
        await asyncio.sleep(3)
        print("ok, lets turn it off now..")
        spider.motor.stop()

    spider.soft_limits(5000, -5000)
    spider.move_to(newpos)
    spider.restart_pid(step_ms=5, kp=kp, ki=ki, kd=kd, speed_limit=speed_limit)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(t_blah1())

def little_play(s: Spider2, speed: int, t: int = 100):
    """ let me fire the motor for t ms at speed to test some up/down slowly tthings..."""

    s.motor.speed(speed)
    time.sleep_ms(t)
    s.motor.stop_brake()


#s = MakeSpider()
