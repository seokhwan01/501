import cv2, time, threading
from flask import Flask, Response, render_template, jsonify, request
from picamera2 import Picamera2

# 모듈 import
from car_modules.motor_controller import MotorController
from car_modules.lane_detector import LaneDetector
from car_modules.lcd_display import LcdDisplay
from car_modules.tts_handler import announce_evasion

# --- 모터 기본 설정 ---
MOTOR_PINS = {
    'M1_DIR': 18, 'M1_PWM': 19, 'M2_DIR': 20, 'M2_PWM': 21,
    'M3_DIR': 22, 'M3_PWM': 23, 'M4_DIR': 24, 'M4_PWM': 25,
}
W, H, FPS = 640, 360, 15
CAMERA_FOV_DEG = 62.0
PIXEL_TO_DEG = CAMERA_FOV_DEG / W

# --- 객체 초기화 ---
picam2 = Picamera2()
cfg = picam2.create_video_configuration(main={"size": (W,H), "format":"RGB888"}, controls={"FrameRate": FPS})
picam2.configure(cfg)

motor = MotorController(MOTOR_PINS)
detector = LaneDetector()
lcd = LcdDisplay(vehicle_name="CAR 2", vehicle_ip="192.168.137.2")

app = Flask(__name__, template_folder='Templates')
lock = threading.Lock()

# 공유 상태
shared_data = {
    "running": True, "manual_stop": True,
    "is_manual_turning": None, "is_moving_backward": False,
    "current_speed": 0.20, "latest_vis_jpeg": None,
    "is_evasion_mode": False,
    "ui": {
        "lane_text": "?", "lane_total": 3, "has_lane": False,
        "offset_norm": 0.0, "speed_text": "0.00",
        "state_text": "STOPPED", "status_text": "",
        "steering_angle": 0.0
    }
}

# --- Flask API ---
@app.route("/")
def index_page(): return render_template("index_s.html")

@app.route("/video")
def video_feed():
    def mjpeg_gen():
        boundary = b"--frame"
        while shared_data["running"]:
            with lock: buf = shared_data["latest_vis_jpeg"]
            if buf:
                yield b"%s\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n"%(boundary,len(buf))+buf+b"\r\n"
            else: time.sleep(0.01)
    return Response(mjpeg_gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/status")
def api_status():
    with lock: return jsonify(shared_data["ui"])

@app.route("/api/turn_left", methods=["POST"])
def api_turn_left():
    with lock: shared_data["is_manual_turning"] = "left"; return jsonify(ok=True)
@app.route("/api/turn_right", methods=["POST"])
def api_turn_right():
    with lock: shared_data["is_manual_turning"] = "right"; return jsonify(ok=True)
@app.route("/api/turn_stop", methods=["POST"])
def api_turn_stop():
    with lock: shared_data["is_manual_turning"] = None; return jsonify(ok=True)
@app.route("/api/speed_up", methods=["POST"])
def api_speed_up():
    with lock: shared_data["current_speed"] = min(shared_data["current_speed"]+0.05, 1.0)
    return jsonify(ok=True, speed=shared_data["current_speed"])
@app.route("/api/speed_down", methods=["POST"])
def api_speed_down():
    with lock: shared_data["current_speed"] = max(shared_data["current_speed"]-0.05, 0.1)
    return jsonify(ok=True, speed=shared_data["current_speed"])
@app.route("/api/toggle_stop", methods=["POST"])
def api_toggle_stop():
    with lock: shared_data["manual_stop"] = not shared_data["manual_stop"]
    return jsonify(ok=True, stopped=shared_data["manual_stop"])
@app.route("/api/toggle_backward", methods=["POST"])
def api_toggle_backward():
    with lock: shared_data["is_moving_backward"] = not shared_data["is_moving_backward"]
    return jsonify(ok=True, backward=shared_data["is_moving_backward"])
@app.route("/api/quit", methods=["POST"])
def api_quit():
    with lock: shared_data["running"] = False; return jsonify(ok=True)

@app.route("/api/emergency_event", methods=["POST"])
def api_emergency_event():
    data = request.json
    direction = data.get("direction", "오른쪽"); minutes = data.get("minutes", 1)
    with lock: shared_data["is_evasion_mode"] = True
    lcd.update_eta(minutes)
    announce_evasion(direction, minutes)
    return jsonify(ok=True, message="Evasion mode activated.")

@app.route("/api/clear_emergency_event", methods=["POST"])
def api_clear_emergency_event():
    with lock: shared_data["is_evasion_mode"] = False
    lcd.update_eta(None)
    return jsonify(ok=True, message="Evasion mode cleared.")

# --- 메인 루프 ---
def processing_loop():
    picam2.start(); time.sleep(0.2)
    
    CROSS_MIN_FRAMES = 3; CROSS_MIN_TIME = 1.0
    cross_trigger_count = 0; cross_mode = False
    cross_start = 0.0; cross_passed = False
    
    try:
        while shared_data["running"]:
            frame = picam2.capture_array(); h, w = frame.shape[:2]; cx = w//2
            try:
                result = detector.process_frame(frame)
                vis_frame = result["vis_frame"]
            except Exception as e:
                print(f"[ERROR] Lane detection failed: {e}")
                result = {}; vis_frame = frame.copy()
                cv2.putText(vis_frame, "Detector Error!", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

            with lock:
                steering_angle = 0.0
                center_smooth = result.get("lane_center_smooth"); center_raw = result.get("lane_center_raw")
                right_line = result.get("right_line_ctrl")

                trigger = False
                if right_line is None: trigger = True
                elif center_raw is not None and abs(center_raw - cx) > 20: trigger = True
                
                if trigger: cross_trigger_count += 1
                else: cross_trigger_count = 0

                if (not cross_mode) and (cross_trigger_count >= CROSS_MIN_FRAMES):
                    cross_mode = True; cross_start = time.time(); cross_passed = False
                
                if cross_mode and (not cross_passed):
                    if time.time() - cross_start >= CROSS_MIN_TIME: cross_passed = True

                if shared_data["manual_stop"]:
                    motor.stop(); base_state_text = "MANUAL STOP"
                elif shared_data["is_manual_turning"] == "right":
                    motor.right_turn(); steering_angle = 30.0; base_state_text = "MANUAL TURN"
                elif shared_data["is_manual_turning"] == "left":
                    motor.left_turn(); steering_angle = -30.0; base_state_text = "MANUAL TURN"
                elif shared_data["is_moving_backward"]:
                    motor.backward(); base_state_text = "BACKWARD"
                else:
                    if cross_mode:
                        motor.forward(shared_data["current_speed"]); base_state_text = "CROSSING"
                        if cross_passed and (center_raw is not None) and (right_line is not None):
                            cross_mode = False; cross_passed = False; cross_trigger_count = 0
                            if detector.lane_center_ema is not None and center_raw is not None:
                                 detector.lane_center_ema = int(center_raw)
                            base_state_text = "CROSS END"
                    else:
                        if center_smooth is None:
                            motor.forward(shared_data["current_speed"]); base_state_text = "RUNNING (FWD)"
                        else:
                            offset = center_smooth - cx; steering_angle = offset * PIXEL_TO_DEG
                            if abs(offset) > 40:
                                motor.forward(shared_data["current_speed"]); base_state_text = "RUNNING (OFFSET LOCK)"
                            elif offset > 15:
                                motor.right_turn(); base_state_text = "RUNNING (RIGHT)"
                            elif offset < -15:
                                motor.left_turn(); base_state_text = "RUNNING (LEFT)"
                            else:
                                motor.forward(shared_data["current_speed"]); base_state_text = "RUNNING (LANE)"
                
                state_text = f"EVASION: {base_state_text}" if shared_data["is_evasion_mode"] else base_state_text
                
                # --- 교차로 차선 데이터 ---
                shared_data["ui"].update({
                    "has_lane": result.get("left_line_ctrl") or result.get("right_line_ctrl"),
                    "lane_text": "2",
                    "lane_total": 2,
                    "offset_norm": float((center_smooth - cx) / (w / 2)) if center_smooth else 0.0,
                    "speed_text": f"{shared_data['current_speed']:.2f}",
                    "state_text": state_text,
                    "steering_angle": round(steering_angle, 2)
                })
                
                ok, buf = cv2.imencode(".jpg", vis_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if ok: shared_data["latest_vis_jpeg"] = buf.tobytes()
    finally:
        motor.stop(); picam2.stop()

# --- 실행 ---
if __name__ == "__main__":
    try:
        lcd.start()
        threading.Thread(target=processing_loop, daemon=True).start()
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        shared_data["running"] = False
        motor.stop(); lcd.stop(); time.sleep(0.2)
