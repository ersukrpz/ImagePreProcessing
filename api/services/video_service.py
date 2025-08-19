import cv2, time

def mjpeg(src: str):
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        for _ in range(5):
            time.sleep(1)
            cap.open(src)
            if cap.isOpened():
                break
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")
