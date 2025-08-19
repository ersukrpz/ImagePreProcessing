import os

class Config:
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

    # Kanal adı: her iki isim de mevcut (eski kodlarla uyum için)
    CHANNEL = os.getenv("CHANNEL_NAME", "imgproc_events")
    CHANNEL_NAME = CHANNEL

    DATA_DIR = "/app/data"
    CAM_FILE = os.path.join(DATA_DIR, "cameras.json")

    # Worker ve API’nin PAYLAŞTIĞI volume
    OUTPUT = "/app/output"
