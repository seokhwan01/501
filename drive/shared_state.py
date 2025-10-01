# shared_state.py
import threading

lock = threading.Lock()

shared_data = {
    "running": True,
    "manual_stop": True,
    "is_manual_turning": None,
    "is_moving_backward": False,
    "current_speed": 0.20,
    "latest_vis_jpeg": None,
    "is_evasion_mode": False,
    "ui": {
        "lane_text": "?",
        "lane_total": 3,
        "has_lane": False,
        "offset_norm": 0.0,
        "speed_text": "0.00",
        "state_text": "STOPPED",
        "status_text": "",
        "steering_angle": 0.0,
    },
}
