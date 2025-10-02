import os, json, time, threading, base64
import cv2
import paho.mqtt.client as mqtt
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from picamera2 import Picamera2


# --- Car 관련 모듈 ---
from car_modules.motor_controller import MotorController
from car_modules.lane_detector import LaneDetector
from shared_state import shared_data, lock

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

MQTT_BROKER = config.get("MQTT_BROKER","localhost")
MQTT_PORT   = config.get("MQTT_PORT", 1883)


# --- MQTT 클라이언트 초기화 ---
mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()


# --- 모터 기본 설정 ---
MOTOR_PINS = {
    'M1_DIR': 18, 'M1_PWM': 19, 'M2_DIR': 20, 'M2_PWM': 21,
    'M3_DIR': 22, 'M3_PWM': 23, 'M4_DIR': 24, 'M4_PWM': 25,
}
W, H, FPS = 640, 360, 24
CAMERA_FOV_DEG = 62.0
PIXEL_TO_DEG = CAMERA_FOV_DEG / W

# --- 객체 초기화 ---
picam2 = Picamera2()
cfg = picam2.create_video_configuration(main={"size": (W,H), "format":"RGB888"}, controls={"FrameRate": FPS})
picam2.configure(cfg)


last_lane = None        # 마지막 확정된 차선
candidate_lane = None   # 후보 차선
candidate_count = 0     # 후보 차선이 연속으로 들어온 횟수
STABLE_THRESHOLD = 3    # 몇 번 연속 들어와야 확정할지


motor = MotorController(MOTOR_PINS)
detector = LaneDetector()


app = Flask(__name__)
socketio = SocketIO(app,cors_allowed_origins="*", async_mode="threading")



# --- Flask API (기존과 동일) ---
@app.route("/")
def index_page(): return render_template("index.html")


@app.route("/api/status")
def api_status():
    with lock: return jsonify(shared_data["ui"])

@app.route("/api/control", methods=["POST"])
def api_control():
    data = request.json or {}
    action = data.get("action")
    response = {"ok": True}

    with lock:
        if action == "turn_left":
            print("left")
            shared_data["is_manual_turning"] = "left"
        elif action == "turn_right":
            shared_data["is_manual_turning"] = "right"
        elif action == "turn_stop":
            shared_data["is_manual_turning"] = None
        elif action == "speed_up":
            shared_data["current_speed"] = min(shared_data["current_speed"] + 0.05, 1.0)
            response["speed"] = shared_data["current_speed"]
        elif action == "speed_down":
            shared_data["current_speed"] = max(shared_data["current_speed"] - 0.05, 0.1)
            response["speed"] = shared_data["current_speed"]
        elif action == "toggle_stop":
            shared_data["manual_stop"] = not shared_data["manual_stop"]
            response["stopped"] = shared_data["manual_stop"]
        elif action == "toggle_backward":
            shared_data["is_moving_backward"] = not shared_data["is_moving_backward"]
            response["backward"] = shared_data["is_moving_backward"]
        elif action == "quit":
            shared_data["running"] = False
        else:
            return jsonify(ok=False, error="Unknown action"), 400

    return jsonify(response)



# --- 메인 루프 ---
def processing_loop():
    global last_lane, candidate_lane, candidate_count  # 전역 변수 사용 선언
    picam2.start()
    time.sleep(0.2)

    try:
        while shared_data["running"]:
            frame = picam2.capture_array()
            h, w = frame.shape[:2]
            cx = w//2 


            try:
                result = detector.process_frame(frame)
                vis_frame = result["vis_frame"]
            except Exception as e:
                print(f"[ERROR] Lane detection failed: {e}")
                result = {}; vis_frame = frame.copy()
                cv2.putText(vis_frame, "Detector Error!", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            with lock:
                steering_angle = 0.0
                center_smooth = result.get("lane_center_smooth")
                current_lane = result.get("current_lane")

                # --- 주행 로직 ---
                if shared_data["manual_stop"]:
                    motor.stop(); base_state_text = "MANUAL STOP"
                elif shared_data["is_manual_turning"] == "right":
                    motor.right_turn(); steering_angle = 30.0; base_state_text = "MANUAL TURN"
                elif shared_data["is_manual_turning"] == "left":
                    motor.left_turn(); steering_angle = -30.0; base_state_text = "MANUAL TURN"
                elif shared_data["is_moving_backward"]:
                    motor.backward(); base_state_text = "BACKWARD"
                
                # 자율 주행 로직
                else:
                    if center_smooth is None:
                        motor.forward(shared_data["current_speed"])
                        base_state_text = "RUNNING (FWD)"
                    else:
                        offset = center_smooth - cx
                        steering_angle = offset * PIXEL_TO_DEG
                        # [추가됨] 트랙 끝(offset 급증)에서 직진하도록 하는 안전장치
                        if abs(offset) > 80:
                            motor.forward(shared_data["current_speed"])
                            base_state_text = "RUNNING (OFFSET LOCK)"
                        elif offset > 15:
                            motor.right_turn(); base_state_text = "RUNNING (RIGHT)"
                        elif offset < -15:
                            motor.left_turn(); base_state_text = "RUNNING (LEFT)"
                        else:
                            motor.forward(shared_data["current_speed"]); base_state_text = "RUNNING (LANE)"
                
                # --- UI 상태 업데이트 ---
                state_text = f"EVASION: {base_state_text}" if shared_data["is_evasion_mode"] else base_state_text
                
                shared_data["ui"].update({
                    "has_lane": result.get("left_line_ctrl") or result.get("right_line_ctrl"),
                    "lane_text": str(current_lane) if current_lane is not None else "?",
                    "lane_total": 3,
                    "offset_norm": float((center_smooth - cx) / (w / 2)) if center_smooth else 0.0,
                    "speed_text": f"{shared_data['current_speed']:.2f}",
                    "state_text": state_text,
                    "steering_angle": round(steering_angle, 2)
                })
                # --- 영상 소켓 송출 ---
                ok, buf = cv2.imencode(".jpg", vis_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok:
                    jpg_as_text = base64.b64encode(buf).decode('utf-8') 
                    socketio.emit("video_frame", {"img": jpg_as_text})

    finally:  # <-- 반드시 finally로 자원 정리
        motor.stop()
        # cap.release()
        picam2.stop()

# --- 실행 ---
if __name__ == "__main__":
    try:
        threading.Thread(target=processing_loop, daemon=True).start()
        socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)

    finally:
        shared_data["running"] = False
        motor.stop()

        time.sleep(0.2)

 