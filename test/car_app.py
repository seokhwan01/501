from flask import Flask, render_template
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# 🚗 상태 변수
car_state = {
    "manual_stop": True,       # True=정지, False=주행
    "is_backward": False       # True=후진, False=전진
}

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("video_frame")
def handle_video(data):
    frame_bytes = data["frame"]
    # 여기서 브라우저로 다시 중계하거나 저장 가능
    socketio.emit("video_broadcast", frame_bytes, broadcast=True)


@socketio.on("control_cmd")
def handle_control(cmd):
    global car_state
    print(f"[CONTROL] 명령 수신: {cmd}")

    if cmd == "stop_resume":
        car_state["manual_stop"] = not car_state["manual_stop"]
        if car_state["manual_stop"]:
            print(">>> 차량 정지")
        else:
            print(">>> 차량 주행")

    elif cmd == "toggle_backward":
        car_state["is_backward"] = not car_state["is_backward"]
        if car_state["is_backward"]:
            print(">>> 차량 후진")
        else:
            print(">>> 차량 전진")

    elif cmd == "turn_left":
        print(">>> 차량 왼쪽 회전")
    elif cmd == "turn_right":
        print(">>> 차량 오른쪽 회전")
    elif cmd == "turn_stop":
        print(">>> 회전 멈춤")
    elif cmd == "speed_up":
        print(">>> 속도 증가")
    elif cmd == "speed_down":
        print(">>> 속도 감소")
    elif cmd == "quit":
        print(">>> 프로그램 종료 요청")
        car_state["manual_stop"] = True
    else:
        socketio.emit("control_response", {"ok": False, "error": "Unknown command"})
        return

    # 🚀 클라이언트에게 현재 상태 + 명령 같이 전송
    socketio.emit("control_response", {
        "ok": True,
        "cmd": cmd,          # 방금 실행된 명령
        "state": car_state   # 현재 차량 상태
    })

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
