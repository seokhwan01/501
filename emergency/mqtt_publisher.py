# mqtt_publisher.py
import json
import paho.mqtt.client as mqtt
from datetime import datetime
class MqttPublisher:
    def __init__(self, broker="localhost", port=1883):
        self.client = mqtt.Client(client_id="ambulance-publisher", clean_session=True)
        self.client.connect(broker, port, 60)
        self.client.loop_start()

    def publish(self, topic, payload):
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False))

    def send_start(self, car, origin, dest, start_time):
        self.publish("ambulance/web/start", {
            "car": car, "origin": origin, "dest": dest,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S")
        })

    def send_route(self, car, dest, route_points, current):
        self.publish("ambulance/web/route", {
            "car": car, "dest": dest,
            "route_points": route_points, "current": current
        })
   


    def send_current(self, car, dest, current, route_info=None, web=True):
        if web:
            # 웹 대시보드 → 현재 좌표만
            self.publish("ambulance/web/current", {
                "car": car, "dest": dest,
                "current": current
            })
        else:
            # 차량 → 현재 좌표 + 원본 route_info
            self.publish("ambulance/vehicles", {
                "car": car, "dest": dest,
                "current": current,
                "route_info": route_info
            })


    def send_arrival(self, car, dest, start_time):
        self.publish("ambulance/web/arrival", {
            "car": car,
            "dest": dest,
            "status": "arrived",
            "start_time": start_time,  # ✅ 추가
            "arrival_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": f"{dest} 도착 완료 🚑"
        })
