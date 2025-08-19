import json, os, threading
from typing import List, Dict
from config import Config

_lock = threading.Lock()

def _ensure_file():
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    if not os.path.exists(Config.CAM_FILE):
        with open(Config.CAM_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

def read_cameras() -> List[Dict]:
    _ensure_file()
    with _lock, open(Config.CAM_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def write_cameras(cams: List[Dict]):
    with _lock, open(Config.CAM_FILE, "w", encoding="utf-8") as f:
        json.dump(cams, f, ensure_ascii=False, indent=2)

def add_camera(camera: Dict):
    cams = read_cameras()
    if any(c["id"] == camera["id"] for c in cams):
        raise ValueError("Camera ID already exists")
    cams.append({"id": camera["id"], "ip": camera["ip"]})
    write_cameras(cams)

def delete_camera(camera_id: str):
    cams = read_cameras()
    new_cams = [c for c in cams if c["id"] != camera_id]
    if len(new_cams) == len(cams):
        raise ValueError("Camera not found")
    write_cameras(new_cams)

def get_camera(camera_id: str) -> Dict | None:
    cams = read_cameras()
    for c in cams:
        if c["id"] == camera_id:
            return c
    return None
