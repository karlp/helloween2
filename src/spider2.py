"""
Smaller test case for exploring the motor a little more
"""
import halloween2

import asyncio
import machine

class Spider2():
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

        self.pos_goal = 0
        self.in_position = True
        self.limits_hit = False
        self.speed_limit = 1

        self.e_prev = 0
        self.eint = 0

        self.t_pid = None
        self.t_soft_limits = None
        # Defaults empirically determined for the raw axel flag...
        self.kp = 0.6
        self.ki = 0.003
        self.kd = 0.01

    @property
    def pos_real(self):
        return self.encoder.position()

    @pos_real.setter
    def pos_real(self, value):
        self.encoder.position(value)

    def move_to(self, position):
        """Requests a move to an absolute position"""
        self.pos_goal = position
        self.in_position = False

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
        while True:
            e = self.pos_goal - self.pos_real
            self.in_position = abs(e) <= 1  # Good enough?
            # ideally, we should get a real time here, rather than assuming asyncio gave us precise timings?
            delta_t = self.step_ms / 1000  # careful, either always use ms, or always seconds....
            dedt = (e - self.e_prev) / delta_t
            self.eint = self.eint + e * delta_t

            out = self.kp * e + self.ki * self.eint + self.kd * dedt
            # range clamp to +- 100
            if out > 100 * self.speed_limit:
                out = 100 * self.speed_limit
            if out < -100 * self.speed_limit:
                out = -100 * self.speed_limit
            # print("speed: ", out)  # you can scan this for overshoot if you like, but it's spammy
            self.motor.speed(int(out))
            self.e_prev = e
            await asyncio.sleep_ms(self.step_ms)


    def restart_pid(self, step_ms=5, kp=None, ki=None, kd=None, speed_limit=1):
        """
        Start or restart pid loop...
        :param step_ms:
        :param kp:
        :param ki:
        :param kd:
        :param speed_limit: how much to scale down again.  Yes, this is like P, but with a max speed limit....
        :return:
        """
        self.step_ms = step_ms
        # Use the internal defaults unless specified
        if kp:
            self.kp = kp
        if ki:
            self.ki = ki
        if kd:
            self.kd = kd
        self.speed_limit = speed_limit
        self.e_prev = 0
        if self.t_pid:
            self.t_pid.cancel()
        self.t_pid = asyncio.create_task(self.maintain_position())


def MakeSpider():
    motor = halloween2.KMotor(machine.Pin.board.MOTOR1, machine.Pin.board.MOTOR2)
    encoder = halloween2.KEncoder(machine.Pin.board.ENCODER1, machine.Pin.board.ENCODER2)

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

#s = MakeSpider()
