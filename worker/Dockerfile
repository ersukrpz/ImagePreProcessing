# worker/Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OpenCV ve genel runtime bağımlılıkları
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libglib2.0-0 libgl1 libgomp1 ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Torch (CPU) + torchvision/torchaudio (CPU)
# Not: --index-url CPU tekerlerini indirir, +cuda gerekmez
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1

# Ultralytics + diğerleri
RUN pip install --no-cache-dir \
    ultralytics==8.3.179 \
    opencv-python-headless \
    numpy \
    redis \
    pillow

# (Volume ile zaten mount edeceğiz ama klasörler dursun)
RUN mkdir -p /app/models /app/output /app/data

# Kod
COPY worker.py .

CMD ["python", "worker.py"]
