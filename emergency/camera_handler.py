import cv2, boto3, base64, time, threading
import socketio
import numpy as np
from datetime import datetime
import os
from s3_client import s3, bucket_name
from config import Config
import subprocess

save_dir = os.path.abspath("videos")
os.makedirs(save_dir, exist_ok=True)

# -------------------------------
# 소켓 연결
# -------------------------------
# 🚗 차량 라즈베리파이 (영상 송출지)
CAR_SERVER_URL = Config.CAR_SERVER_URL #얘는 ip 바꿀 필요 없음

# 🖥️ 관제탑 서버 (영상 최종 목적지)
WEB_SERVER_URL = Config.WEB_SERVER_URL

sio_car = socketio.Client()       # 라즈에서 수신
sio_control = socketio.Client()   # 관제탑으로 송출
sio_control.connect(WEB_SERVER_URL)

@sio_car.event
def connect():
    print("✅ 라즈 서버와 소켓 연결 성공")

@sio_car.event
def disconnect():
    print("❌ 라즈 서버와 소켓 끊김")

# -------------------------------
# 차량번호 변환
# -------------------------------
kor_map = {"가":"ga","나":"na","다":"da","라":"ra","마":"ma",
           "바":"ba","사":"sa","아":"a","자":"ja","차":"cha",
           "카":"ka","타":"ta","파":"pa","하":"ha"}

def normalize_car_id(car_id: str) -> str:
    return "".join(kor_map.get(ch, ch if ch.isalnum() else "_") for ch in car_id)

# -------------------------------
# CameraHandler
# -------------------------------
class CameraHandler:
    def __init__(self):
        self.running = False
        self.file_name = None
        self.file_path = None
        self.out = None

    def start(self, car_id, start_time):
        ts = start_time.strftime("%Y%m%d_%H%M%S")
        safe_car_id = normalize_car_id(car_id)
        self.file_name = f"{safe_car_id}_{ts}.mp4"
        self.file_path = os.path.join(save_dir, self.file_name)
        self.out = cv2.VideoWriter(
        self.file_path,
        cv2.VideoWriter_fourcc(*'mp4v'),  # ✅ 여기서 mp4v로
        15.0,
        (640, 360)
    )

        self.running = True
        print(f"[CameraHandler] 녹화 시작: {self.file_path}")

    def write_frame(self, frame):
        if self.running and self.out:
            self.out.write(frame)

    def stop_and_upload(self):
        self.running = False
        if self.out:
            self.out.release()
            print("[CameraHandler] 녹화 종료")

            # 변환된 파일 이름 (H.264)
            converted_path = self.file_path.replace(".mp4", ".mp4")

            # ffmpeg로 H.264 변환
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-i", self.file_path,
                    "-vcodec", "libx264", "-acodec", "aac",
                    converted_path
                ], check=True)
                print(f"🎬 ffmpeg 변환 완료: {converted_path}")
            except Exception as e:
                print(f"❌ ffmpeg 변환 실패: {e}")
                return

            # 변환된 파일 S3 업로드
            s3_key = f"videos/{os.path.basename(converted_path)}"
            try:
                s3.upload_file(converted_path, bucket_name, s3_key,
                               ExtraArgs={'ContentType': 'video/mp4'})
                print(f"✅ 업로드 완료 → https://{bucket_name}.s3.us-east-1.amazonaws.com/{s3_key}")
            except Exception as e:
                print(f"❌ 업로드 실패: {e}")


# -------------------------------
# 라즈에서 영상 프레임 수신
# -------------------------------
camera_handler = CameraHandler()

@sio_car.on("video_frame")
def on_video_frame(data):
    print("[DEBUG] video_frame 수신, data 길이:", len(data.get("img","")))
    try:
        jpg_as_text = data["img"]

        # 1) 관제탑으로 중계
        sio_control.emit("image_broadcast_cam1", jpg_as_text)

        # 2) 디코딩해서 로컬 녹화
        jpg_bytes = base64.b64decode(jpg_as_text)
        np_arr = np.frombuffer(jpg_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is not None:
            camera_handler.write_frame(frame)

    except Exception as e:
        print(f"❌ 영상 처리 오류: {e}")


def start_camera_relay(car_id, start_time):
    camera_handler.start(car_id, start_time)
    sio_car.connect(CAR_SERVER_URL)
