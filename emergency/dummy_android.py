# dummy_client.py
# -*- coding: utf-8 -*-
import socket
import json

HOST = "127.0.0.1"   # 서버 주소
PORT = 6000

def send_dummy_request():
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((HOST, PORT))

        # 테스트용 메시지
        msg = {
            "car": "119다119",
            "dest": "중앙대학교 병원",
            "lat": 37.506696,
            "lng": 126.960597
        }

        client.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        print(f"📤 전송: {msg}")

        # 서버 응답 수신
        response = client.recv(1024).decode().strip()
        print(f"📥 응답: {response}")

        client.close()

    except Exception as e:
        print("❌ 오류:", e)

def main():
    while True:
        print("\n=== 더미 클라이언트 메뉴 ===")
        print("1. 서버로 요청 보내기")
        print("0. 종료")
        choice = input("번호 입력: ").strip()

        if choice == "1":
            send_dummy_request()
        elif choice == "0":
            print("👋 종료합니다.")
            break
        else:
            print("⚠️ 잘못된 입력입니다. 다시 선택하세요.")

if __name__ == "__main__":
    main()
