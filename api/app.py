# api/app.py
import os
import redis as redislib
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from models import Camera
from services.camera_service import read_cameras, add_camera, delete_camera, get_camera
from services.video_service import mjpeg
from services.redis_service import RedisService
from config import Config

app = FastAPI(title="ImageProcessing API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Full resimleri doğrudan servis et
app.mount("/output", StaticFiles(directory=Config.OUTPUT), name="output")

# Redis
redis = RedisService()
r = redislib.Redis(host=Config.REDIS_HOST, port=Config.REDIS_PORT, decode_responses=True)

# --- Camera CRUD ---
@app.get("/cameras")
def get_cameras():
    return JSONResponse(read_cameras())

@app.post("/cameras")
def create_camera(cam: Camera):
    try:
        add_camera(cam.dict())
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/cameras/{camera_id}")
def remove_camera(camera_id: str):
    try:
        delete_camera(camera_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# --- Live video (MJPEG) ---
@app.get("/video/{camera_id}")
def video(camera_id: str):
    cam = get_camera(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return StreamingResponse(
        mjpeg(cam["ip"]),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

# --- Events (SSE) ---
@app.get("/events")
async def events(request: Request):
    return StreamingResponse(redis.sse_stream(request), media_type="text/event-stream")

# --- Processing control (Start/Stop) ---
PROCESSING_KEY = "processing_enabled"
CONTROL_CH     = "control"

@app.post("/control/start")
def start_processing():
    r.set(PROCESSING_KEY, "1")
    r.publish(CONTROL_CH, "start")
    return {"ok": True}

@app.post("/control/stop")
def stop_processing():
    r.set(PROCESSING_KEY, "0")
    r.publish(CONTROL_CH, "stop")
    return {"ok": True}

@app.get("/control/status")
def status_processing():
    return {"enabled": r.get(PROCESSING_KEY) == "1"}
