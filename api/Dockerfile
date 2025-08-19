FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn[standard] redis pydantic opencv-python-headless
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
