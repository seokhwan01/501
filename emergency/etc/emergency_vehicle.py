# -*- coding: utf-8 -*-
# 긴급 차량 서버 (사당역 → 목적지, 주행 시뮬레이션)
# 안드로이드앱에서 목적지 수신 → ETA 응답 + MQTT 발행
# 🚨 Kakao Directions API는 반드시 (lng, lat) 순서로 좌표를 넘겨야 함! (경도 → 위도)

import socket
import sys
import json
import time
import requests
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta
HOST = "0.0.0.0"
PORT = 6000

# 🔑 Kakao Mobility REST API Key
REST_API_KEY = "f345f684051191769c60a3d5f15d3774"
API_URL = "https://apis-navi.kakaomobility.com/v1/directions"

# -------------------------------
# MQTT 설정
# -------------------------------
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# 웹용 토픽
MQTT_TOPIC_WEB_ROUTE = "ambulance/web/route"     # 출발 시 1회: 전체 경로 + 시작 위치
MQTT_TOPIC_WEB_CURRENT = "ambulance/web/current" # 주행 중: 현재 좌표만 계속
MQTT_TOPIC_WEB_ARRIVAL = "ambulance/web/arrival"   # 도착 시 1회: 도착 알림
MQTT_TOPIC_WEB_START = "ambulance/web/start" #출발 시 알림

# 주변차량용 토픽
MQTT_TOPIC_VEHICLES = "ambulance/vehicles"       # 주행 중: 전체 경로 + 현재 좌표


mqtt_client = mqtt.Client()
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()

# -------------------------------
# Kakao API (거리, ETA 계산용)
# -------------------------------
def request_kakao_route(origin_lng, origin_lat, dest_lng, dest_lat):
    headers = {"Authorization": f"KakaoAK {REST_API_KEY}"}
    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{dest_lng},{dest_lat}"
    }
    response = requests.get(API_URL, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        total_distance = 0
        total_duration = 0
        sections = data.get("routes", [])[0].get("sections", [])
        for section in sections:
            total_distance += int(section.get("distance", 0))
            total_duration += int(section.get("duration", 0))

        distance_km = round(total_distance / 1000, 1)
        duration_min = total_duration // 60
        duration_sec = total_duration % 60
        return {
            "success": True,
            "distance": f"{distance_km} km",
            "duration": f"{duration_min}분 {duration_sec}초",
            "raw": data
        }
    else:
        error_msg = response.text
        if error_msg.startswith("<!DOCTYPE"):
            error_msg = "Kakao API HTML Error"
        return {"success": False, "error": error_msg}

# -------------------------------
# Kakao JSON → 좌표 리스트 변환 (원본 전체 반환)
# -------------------------------
def extract_all_route_points(kakao_json):
    points = []
    try:
        routes = kakao_json.get("routes", [])[0].get("sections", [])
        for section in routes:
            for road in section.get("roads", []):
                vertexes = road.get("vertexes", [])
                for i in range(0, len(vertexes), 2):
                    lng = vertexes[i]
                    lat = vertexes[i + 1]
                    points.append({"lat": lat, "lng": lng})
    except Exception as e:
        print("❌ 경로 좌표 추출 실패:", e)
    return points

# -------------------------------
# Kakao JSON → 좌표 리스트 변환 (웹 전용: 500개 이하 샘플링)
# -------------------------------
def extract_web_route_points(kakao_json, max_points=500):
    points = extract_all_route_points(kakao_json)
    total = len(points)
    if total <= max_points:
        return points

    step = total / max_points
    sampled = []
    idx = 0.0
    while int(idx) < total and len(sampled) < max_points:
        sampled.append(points[int(idx)])
        idx += step
    return sampled

# -------------------------------
# 주행 시뮬레이션 (웹 + 주변차량 발행)
# -------------------------------
def simulate_drive(car, dest, kakao_json):
    # 원본 좌표 (주변차량용)
    full_route_points = extract_all_route_points(kakao_json)
    # 샘플링 좌표 (웹용)
    web_route_points = extract_web_route_points(kakao_json, max_points=500)

    if not full_route_points:
        print("❌ 추출된 경로 좌표 없음")
        return

    # 1️⃣ 출발 시: 웹에는 샘플링된 경로만 전송
    web_payload = {
        "car": car,
        "dest": dest,
        "route_points": web_route_points,
        "current": web_route_points[0]
    }
    mqtt_client.publish(MQTT_TOPIC_WEB_ROUTE, json.dumps(web_payload, ensure_ascii=False))
    print(f"📡 웹에 경로 전송 (좌표 {len(web_route_points)}개)")

    # 2️⃣ 출발 시: 주변차량에는 원본 전체 경로 전송
    vehicle_payload = {
        "car": car,
        "dest": dest,
        "route_points": full_route_points,
        "current": full_route_points[0]
    }
    mqtt_client.publish(MQTT_TOPIC_VEHICLES, json.dumps(vehicle_payload, ensure_ascii=False))
    print(f"📡 주변 차량에 경로 전송 (좌표 {len(full_route_points)}개)")

    # 3️⃣ 주행 중: 현재 좌표 계속 전송
    for i, coord in enumerate(full_route_points, start=1):
        # 웹에는 현재 좌표만
        mqtt_client.publish(MQTT_TOPIC_WEB_CURRENT, json.dumps({"car": car, "current": coord}, ensure_ascii=False))

        # 주변차량에는 전체 경로 + 현재 좌표
        mqtt_payload = {
            "car": car,
            "dest": dest,
            "route_points": full_route_points,
            "current": coord
        }
        mqtt_client.publish(MQTT_TOPIC_VEHICLES, json.dumps(mqtt_payload, ensure_ascii=False))

        print(f"📡 웹(현재위치) + 주변차량(전체경로) 발행 {i}/{len(full_route_points)}")
        time.sleep(0.5)

    # 4️⃣ 도착 알림 (웹 전용)
    arrival_payload = {
        "car": car,
        "dest": dest,
        "status": "arrived",
        "message": f"{dest} 도착 완료 🚑"
    }
    mqtt_client.publish(MQTT_TOPIC_WEB_ARRIVAL, json.dumps(arrival_payload, ensure_ascii=False))
    print(f"🏁 도착 알림 발행 → {dest}")


# -------------------------------
# 메인 서버 루프
# -------------------------------
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen()
server.settimeout(10)

print("🚑 소켓 서버 대기중... (Ctrl+C 로 종료)")

# ⚠️ 사당역 좌표 (lng, lat) 순서
SADANG_LNG = "126.9816"
SADANG_LAT = "37.4765"

try:
    while True:
        try:
            conn, addr = server.accept()
            print("📡 연결됨:", addr)
            conn.settimeout(10)

            data = conn.recv(1024).decode().strip()
            if not data:
                continue

            print("📥 원본 수신:", data)
            try:
                msg = json.loads(data)
                car = msg.get("car", "119다119")
                dest = msg.get("dest", "병원")

                dest_lat = float(msg.get("lat"))
                dest_lng = float(msg.get("lng"))

                print(f"🚗 차량번호={car}, 목적지={dest}, 좌표=(lat={dest_lat}, lng={dest_lng})")
                result = request_kakao_route(SADANG_LNG, SADANG_LAT, dest_lng, dest_lat)

                if result["success"]:
                    # 출발/도착 시간 계산
                    now = datetime.now()
                    total_duration = sum(int(section.get("duration", 0)) for section in result["raw"]["routes"][0]["sections"])
                    arrival_time = now + timedelta(seconds=total_duration)

                    response_msg = {
                        "status": "success",
                        "distance": result["distance"],
                        "duration": result["duration"],
                        "start_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "eta_time": arrival_time.strftime("%Y-%m-%d %H:%M:%S")
                    }

                    # 안드로이드로 응답
                    conn.sendall((json.dumps(response_msg, ensure_ascii=False) + "\n").encode())
                    print(f"📤 안드로이드 응답: {response_msg}")

                    # ✅ 출발 알림 MQTT 발행
                    start_payload = {
                        "car": car,
                        "origin": "사당역",
                        "dest": dest,
                        "start_time": response_msg["start_time"],
                        "eta_time": response_msg["eta_time"]
                    }
                    mqtt_client.publish(MQTT_TOPIC_WEB_START, json.dumps(start_payload, ensure_ascii=False))
                    print(f"🕒 출발 알림 발행 → {dest}")

                    # ✅ 주행 시뮬레이션 실행
                    simulate_drive(car, dest, result["raw"])

                else:
                    response_msg = {"status": "fail", "error": result["error"]}
                    conn.sendall((json.dumps(response_msg, ensure_ascii=False) + "\n").encode())
                    print(f"📤 안드로이드 응답: {response_msg}")


                # 안드로이드로 응답
                conn.sendall((json.dumps(response_msg, ensure_ascii=False) + "\n").encode())
                print(f"📤 안드로이드 응답: {response_msg}")

                if result["success"]:
                    # 출발 알림 → 웹 표에 바로 쓰게 발행
                    start_payload = {
                        "car": car,
                        "origin": "사당역",  # 고정
                        "dest": dest,
                        "start_time": response_msg["start_time"],
                        "eta_time": response_msg["eta_time"]
                    }
                    mqtt_client.publish(MQTT_TOPIC_WEB_START, json.dumps(start_payload, ensure_ascii=False))
                    print(f"🕒 출발 알림 발행 → {dest}")

                    # 주행 시뮬레이션 실행
                    simulate_drive(car, dest, result["raw"])

            except json.JSONDecodeError:
                print("❌ JSON 파싱 실패:", data)
                response_msg = {"status": "fail", "error": "Invalid JSON"}
                conn.sendall((json.dumps(response_msg, ensure_ascii=False) + "\n").encode())

        except socket.timeout:
            continue

except KeyboardInterrupt:
    print("\n🛑 서버 종료")
    server.close()
    mqtt_client.loop_stop()
    sys.exit(0)
