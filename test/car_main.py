import cv2, time, threading, socketio
# from picamera2 import Picamera2   # 🔹 라즈베리파이 전용 카메라 모듈 → 주석 처리
from car_modules.motor_controller import MotorController
from car_modules.lane_detector import LaneDetector
from car_modules.lcd_display import LcdDisplay

# === 기본 설정 ===
MOTOR_PINS = {
    'M1_DIR': 18, 'M1_PWM': 19,
    'M2_DIR': 20, 'M2_PWM': 21,
    'M3_DIR': 22, 'M3_PWM': 23,
    'M4_DIR': 24, 'M4_PWM': 25,
}
W, H, FPS = 640, 360, 24        # 카메라 해상도 & FPS
PIXEL_TO_DEG = 62.0 / W         # 카메라 화각(62도)을 픽셀 기준 각도로 환산

# === 카메라 초기화 ===
# 🔹 라즈베리파이 카메라 (주석 처리)
# picam2 = Picamera2()
# cfg = picam2.create_video_configuration(
#     main={"size": (W, H), "format": "RGB888"},
#     controls={"FrameRate": FPS}
# )
# picam2.configure(cfg)

# 🔹 노트북 내장 카메라(OpenCV)
cap = cv2.VideoCapture(0)   # 0 → 기본 카메라
cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
cap.set(cv2.CAP_PROP_FPS, FPS)

motor = MotorController(MOTOR_PINS)      
detector = LaneDetector()                
lcd = LcdDisplay(vehicle_name="CAR 2", vehicle_ip="192.168.137.2")   

# === 상태 공유 변수 ===
lock = threading.Lock()
shared_data = {
    "running": True,
    "manual_stop": True,
    "is_manual_turning": None,
    "is_moving_backward": False,
    "current_speed": 0.20,
    "latest_vis_jpeg": None,
    "is_evasion_mode": False,
}

# === Socket.IO 클라이언트 ===
sio = socketio.Client()

@sio.event
def connect():
    print("[CLIENT] 서버 연결됨")

@sio.on("control_response")
def on_control_response(data):
    print("[CLIENT] 서버 응답:", data)
    cmd = data.get("cmd")
    state = data.get("state", {})

    with lock:
        if "manual_stop" in state:
            shared_data["manual_stop"] = state["manual_stop"]
        if "is_backward" in state:
            shared_data["is_moving_backward"] = state["is_backward"]

        if cmd == "turn_left":
            shared_data["is_manual_turning"] = "left"
        elif cmd == "turn_right":
            shared_data["is_manual_turning"] = "right"
        elif cmd == "turn_stop":
            shared_data["is_manual_turning"] = None
        elif cmd == "speed_up":
            shared_data["current_speed"] = min(shared_data["current_speed"] + 0.05, 1.0)
        elif cmd == "speed_down":
            shared_data["current_speed"] = max(shared_data["current_speed"] - 0.05, 0.1)
        elif cmd == "quit":
            shared_data["running"] = False

@sio.event
def disconnect():
    print("[CLIENT] 서버 연결 끊김")

# === 주행 루프 ===
def processing_loop():
    # 🔹 라즈 전용 (주석)
    # picam2.start()
    # time.sleep(0.2)
    try:
        while shared_data["running"]:
            ret, frame = cap.read()   # 🔹 노트북 카메라 캡처
            if not ret:
                print("[ERROR] 카메라에서 프레임을 가져올 수 없음")
                time.sleep(0.1)
                continue

            h, w = frame.shape[:2]; cx = w // 2

            try:
                result = detector.process_frame(frame)
            except Exception as e:
                print(f"[ERROR] Lane detection failed: {e}")
                result = {"vis_frame": frame}

            vis_frame = result["vis_frame"]

            with lock:
                steering_angle = 0.0
                center_smooth = result.get("lane_center_smooth")

                if shared_data["manual_stop"]:
                    motor.stop()
                elif shared_data["is_manual_turning"] == "right":
                    motor.right_turn(); steering_angle = 30.0
                elif shared_data["is_manual_turning"] == "left":
                    motor.left_turn(); steering_angle = -30.0
                elif shared_data["is_moving_backward"]:
                    motor.backward()
                else:
                    if center_smooth is None:
                        motor.forward(shared_data["current_speed"])
                    else:
                        offset = center_smooth - cx
                        steering_angle = offset * PIXEL_TO_DEG
                        if abs(offset) > 80:
                            motor.forward(shared_data["current_speed"])
                        elif offset > 15:
                            motor.right_turn()
                        elif offset < -15:
                            motor.left_turn()
                        else:
                            motor.forward(shared_data["current_speed"])

                ok, buf = cv2.imencode(".jpg", vis_frame)
                if ok:
                    shared_data["latest_vis_jpeg"] = buf.tobytes()
    finally:
        motor.stop()
        # picam2.stop()  # 🔹 라즈 카메라 종료 (주석)
        cap.release()   # 🔹 노트북 카메라 해제

if __name__ == "__main__":
    sio.connect("http://localhost:5000")
    sio.wait()
