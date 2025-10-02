
from gpiozero import LED, PWMLED

class MotorController:
    def __init__(self, pins): #모터 초기화
        """
        pins: M1, M2, M3, M4의 DIR, PWM 핀 정보가 담긴 딕셔너리
        """
        self.M1_DIR = LED(pins['M1_DIR'])
        self.M1_PWM = PWMLED(pins['M1_PWM'])
        self.M2_DIR = LED(pins['M2_DIR'])
        self.M2_PWM = PWMLED(pins['M2_PWM'])
        self.M3_DIR = LED(pins['M3_DIR'])
        self.M3_PWM = PWMLED(pins['M3_PWM'])
        self.M4_DIR = LED(pins['M4_DIR'])
        self.M4_PWM = PWMLED(pins['M4_PWM'])

        self.SPEED_FWD = 0.15
        self.SPEED_TURN = 0.30

    def _stop_all_pwm(self):
        self.M1_PWM.value = 0.0
        self.M2_PWM.value = 0.0
        self.M3_PWM.value = 0.0
        self.M4_PWM.value = 0.0

    def forward(self, speed=None):
        if speed is None:
            speed = self.SPEED_FWD
        self.M1_DIR.on()
        self.M2_DIR.off()
        self.M3_DIR.on()
        self.M4_DIR.off()
        self.M1_PWM.value = speed
        self.M2_PWM.value = speed
        self.M3_PWM.value = speed
        self.M4_PWM.value = speed

    def backward(self):
        self.M1_DIR.off()
        self.M2_DIR.on()
        self.M3_DIR.off()
        self.M4_DIR.on()
        self.M1_PWM.value = self.SPEED_FWD
        self.M2_PWM.value = self.SPEED_FWD
        self.M3_PWM.value = self.SPEED_FWD
        self.M4_PWM.value = self.SPEED_FWD

    def right_turn(self):
        self.M1_DIR.on()
        self.M2_DIR.off()
        self.M3_DIR.on()
        self.M4_DIR.off()
        self.M1_PWM.value = self.SPEED_TURN
        self.M2_PWM.value = 0.0
        self.M3_PWM.value = self.SPEED_TURN
        self.M4_PWM.value = 0.0

    def left_turn(self):
        self.M1_DIR.on()
        self.M2_DIR.off()
        self.M3_DIR.on()
        self.M4_DIR.off()
        self.M1_PWM.value = 0.0
        self.M2_PWM.value = self.SPEED_TURN
        self.M3_PWM.value = 0.0
        self.M4_PWM.value = self.SPEED_TURN

    def stop(self):
        self._stop_all_pwm()