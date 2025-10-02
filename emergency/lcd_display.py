
import smbus2
import time
import threading
import os

class LcdDisplay:
    def __init__(self, i2c_addr=0x27, lcd_width=20, vehicle_name="119ga 119", vehicle_ip=None):
        self.I2C_ADDR = i2c_addr
        self.LCD_WIDTH = lcd_width
        self.VEHICLE_NAME = vehicle_name
        self.VEHICLE_IP = self._get_local_ip(vehicle_ip)
        # LCD 상수
        self.LCD_CHR = 1
        self.LCD_CMD = 0
        self.LINE_ADDR = [0x80, 0xC0, 0x94, 0xD4]
        self.ENABLE = 0b00000100
        self.BACKLIGHT = 0b00001000

        self._bus = None
        self._thread_running = False
        self._lock = threading.Lock()
        self._latest_eta_minutes = None

    def _get_local_ip(self, static_ip=None):
        if static_ip: 
            return static_ip
        try:
            return os.popen("hostname -I").read().strip().split()[0]
        except Exception:
            return "0.0.0.0"

    def _write(self, bits, mode):
        high = mode | (bits & 0xF0) | self.BACKLIGHT
        low  = mode | ((bits << 4) & 0xF0) | self.BACKLIGHT
        self._bus.write_byte(self.I2C_ADDR, high)
        self._toggle(high)
        self._bus.write_byte(self.I2C_ADDR, low)
        self._toggle(low)

    def _toggle(self, bits):
        time.sleep(0.0005)
        self._bus.write_byte(self.I2C_ADDR, bits | self.ENABLE)
        time.sleep(0.0005)
        self._bus.write_byte(self.I2C_ADDR, (bits & ~self.ENABLE))
        time.sleep(0.0001)

    def _init_lcd(self):
        self._write(0x33, self.LCD_CMD)
        self._write(0x32, self.LCD_CMD)
        self._write(0x06, self.LCD_CMD)
        self._write(0x0C, self.LCD_CMD)
        self._write(0x28, self.LCD_CMD)
        self._write(0x01, self.LCD_CMD)
        time.sleep(0.005)

    def print_line(self, line, message):
        # 먼저 라인 전체 지움 (공백으로 채움)
        clear_msg = " " * self.LCD_WIDTH
        self._write(self.LINE_ADDR[line], self.LCD_CMD)
        for char in clear_msg:
            self._write(ord(char), self.LCD_CHR)

        message = message.ljust(self.LCD_WIDTH, " ")
        self._write(self.LINE_ADDR[line], self.LCD_CMD)
        for char in message[:self.LCD_WIDTH]:
            self._write(ord(char), self.LCD_CHR)

    # 🚑 상태 업데이트 (출발/종료만 표시)
    def update_status(self, state):
        self.print_line(0, f"{self.VEHICLE_NAME}")
        self.print_line(1, f"IP: {self.VEHICLE_IP}")
        if state == "start":
            self.print_line(2, "Dispatching".ljust(self.LCD_WIDTH))
        elif state == "finished":
            self.print_line(2, "Finished".ljust(self.LCD_WIDTH))
        elif state == "standby":
            self.print_line(2, "Standby".ljust(self.LCD_WIDTH))
        else:
            self.print_line(2, "Error".ljust(self.LCD_WIDTH))

    def start(self):
        try:
            self._bus = smbus2.SMBus(1)
            self._init_lcd()
            print("[LCD] ready.")
            self.update_status("standby")   # 기본 표시
        except Exception as e:
            print(f"[LCD] init failed: {e}")

    def stop(self):
        try:
            if self._bus is not None:
                self._bus.close()
                self._bus = None
                print("[LCD] stopped.")
                
        except Exception as e:
            print(f"[LCD] stop error: {e}")