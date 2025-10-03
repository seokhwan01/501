# kakao_client.py
import requests

class KakaoClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = "https://apis-navi.kakaomobility.com/v1/directions"

    def request_route(self, origin_lng, origin_lat, dest_lng, dest_lat):
        headers = {"Authorization": f"KakaoAK {self.api_key}"}
        params = {
            "origin": f"{origin_lng},{origin_lat}",
            "destination": f"{dest_lng},{dest_lat}",
            "road_details": True,
            "waypoints": "126.9821635,37.4853994", # 🚩 이수역 경유지
            "priority": "DISTANCE"   # ← 최단 거리 기준 (재현성 ↑)
        }
        response = requests.get(self.api_url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            total_distance = 0
            total_duration = 0
            sections = data.get("routes", [])[0].get("sections", [])
            for section in sections:
                total_distance += int(section.get("distance", 0))
                total_duration += int(section.get("duration", 0))

            return {
                "success": True,
                "distance": f"{round(total_distance/1000,1)} km",
                "duration": f"{total_duration//60}분 {total_duration%60}초",
                "raw": data
            }
        else:
            return {"success": False, "error": response.text}

    def extract_all_points(self, kakao_json):
        points = []
        try:
            routes = kakao_json.get("routes", [])[0].get("sections", [])
            for section in routes:
                for road in section.get("roads", []):
                    vertexes = road.get("vertexes", [])
                    for i in range(0, len(vertexes), 2):
                        points.append({"lat": vertexes[i+1], "lng": vertexes[i]})
        except Exception as e:
            print("❌ 경로 좌표 추출 실패:", e)
        return points

    def extract_web_points(self, kakao_json, max_points=500):
        all_points = self.extract_all_points(kakao_json)
        total = len(all_points)
        if total <= max_points:
            return all_points
        step = total / max_points
        return [all_points[int(i*step)] for i in range(max_points)]
