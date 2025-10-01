import smbus2
import time
import threading
import os

class LcdDisplay:
    def __init__(self, i2c_addr=0x27, lcd_width=20, vehicle_name="CAR", vehicle_ip=None):
        # --- 기본 설정 ---
        self.I2C_ADDR = i2c_addr         # LCD I2C 주소 (보통 0x27 또는 0x3F)
        self.LCD_WIDTH = lcd_width       # 한 줄의 문자 수 (20x4 LCD → 20)
        self.VEHICLE_NAME = vehicle_name # 표시할 차량 이름
        self.VEHICLE_IP = self._get_local_ip(vehicle_ip)  # 차량 IP 주소

        # --- LCD 명령/데이터 상수 ---
        self.LCD_CHR = 1                 # 문자 전송 모드
        self.LCD_CMD = 0                 # 명령 전송 모드
        self.LINE_ADDR = [0x80, 0xC0, 0x94, 0xD4]  # LCD 각 라인의 DDRAM 주소
        self.ENABLE = 0b00000100         # Enable 비트
        self.BACKLIGHT = 0b00001000      # 백라이트 ON 비트

        # --- 내부 상태 변수 ---
        self._bus = None                 # I2C 버스 핸들
        self._thread_running = False     # 업데이트 스레드 실행 여부
        self._lock = threading.Lock()    # ETA 접근 동기화용 락
        self._latest_eta_minutes = None  # 최신 ETA (분 단위)

    # ========================
    # 내부 유틸리티 함수
    # ========================

    def _get_local_ip(self, static_ip=None):
        """IP 주소 조회 (static_ip 있으면 그대로 사용, 없으면 hostname -I로 가져옴)"""
        if static_ip: 
            return static_ip
        try:
            return os.popen("hostname -I").read().strip().split()[0]
        except Exception:
            return "0.0.0.0"

    def _write(self, bits, mode):
        """LCD에 8비트(상위/하위 nibble 분리) 전송"""
        high = mode | (bits & 0xF0) | self.BACKLIGHT  # 상위 4비트
        low  = mode | ((bits << 4) & 0xF0) | self.BACKLIGHT  # 하위 4비트
        self._bus.write_byte(self.I2C_ADDR, high)
        self._toggle(high)
        self._bus.write_byte(self.I2C_ADDR, low)
        self._toggle(low)

    def _toggle(self, bits):
        """Enable 신호 토글 (LCD에 데이터 확정)"""
        time.sleep(0.0005)
        self._bus.write_byte(self.I2C_ADDR, bits | self.ENABLE)
        time.sleep(0.0005)
        self._bus.write_byte(self.I2C_ADDR, (bits & ~self.ENABLE))
        time.sleep(0.0001)

    def _init_lcd(self):
        """LCD 초기화 시퀀스 (HD44780 표준)"""
        self._write(0x33, self.LCD_CMD)  # 초기화
        self._write(0x32, self.LCD_CMD)  # 4비트 모드 설정
        self._write(0x06, self.LCD_CMD)  # 커서 오른쪽 이동
        self._write(0x0C, self.LCD_CMD)  # 디스플레이 ON, 커서 OFF
        self._write(0x28, self.LCD_CMD)  # 2라인 모드, 5x8 폰트
        self._write(0x01, self.LCD_CMD)  # 화면 클리어
        time.sleep(0.005)

    # ========================
    # 사용자 함수
    # ========================

    def print_line(self, line, message):
        """특정 라인(line)에 문자열 출력"""
        message = message.ljust(self.LCD_WIDTH, " ")  # 오른쪽 패딩
        self._write(self.LINE_ADDR[line], self.LCD_CMD)  # 라인 주소 설정
        for char in message[:self.LCD_WIDTH]:
            self._write(ord(char), self.LCD_CHR)  # 문자 하나씩 출력

    def _update_loop(self):
        """주기적으로 LCD 내용을 갱신하는 백그라운드 루프"""
        while self._thread_running:
            try:
                # ETA 가져오기
                with self._lock:
                    eta_min = self._latest_eta_minutes

                # ETA 텍스트 구성
                eta_text = f"ETA: {eta_min:02d} min" if eta_min is not None else "ETA: -- min"

                # LCD 표시 (20x4 라인)
                self.print_line(0, f"{self.VEHICLE_NAME}")     # 차량 이름
                self.print_line(1, f"IP: {self.VEHICLE_IP}")   # 차량 IP
                self.print_line(2, eta_text)                   # ETA
                if eta_min is not None and eta_min <= 3:
                    self.print_line(3, "Approaching")          # 3분 이내 도착 시 경고
                else:
                    self.print_line(3, "")

            except Exception as e:
                print(f"[LCD] Update loop error: {e}")
                time.sleep(2)

            time.sleep(1)  # 1초마다 새로고침

    def update_eta(self, minutes):
        """ETA(분) 갱신 (thread-safe)"""
        with self._lock:
            self._latest_eta_minutes = minutes

    def start(self):
        """LCD 시작: I2C 초기화 + 업데이트 스레드 실행"""
        try:
            self._bus = smbus2.SMBus(1)   # I2C 버스 열기 (라즈베리파이 기본은 1번)
            self._init_lcd()              # LCD 초기화
            self._thread_running = True
            threading.Thread(target=self._update_loop, daemon=True).start()
            print("[LCD] started.")
        except Exception as e:
            print(f"[LCD] init failed: {e}")

    def stop(self):
        """LCD 정지: 스레드 종료 + I2C 닫기"""
        self._thread_running = False
        time.sleep(0.1)
        try:
            if self._bus is not None:
                self._bus.close()
                self._bus = None
                print("[LCD] stopped.")
        except Exception as e:
            print(f"[LCD] stop error: {e}")
