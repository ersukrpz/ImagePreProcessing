# /app/worker.py
import os, time, uuid, base64, json as jsonlib
import cv2, numpy as np, redis

# ===================== Config / Env =====================
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CHANNEL    = os.getenv("CHANNEL_NAME", "imgproc_events")

OUTPUT_DIR = "/app/output"
DATA_DIR   = "/app/data"
CAM_FILE   = os.path.join(DATA_DIR, "cameras.json")

# Örnekleme & anti-spam
SAMPLE_EVERY = int(os.getenv("SAMPLE_EVERY", "3"))   # her 3. kareyi işle
COOLDOWN_SEC = int(os.getenv("COOLDOWN_SEC", "8"))   # aynı track için TTL
GRID         = int(os.getenv("GRID", "32"))          # yedek imza grid boyutu (px)

# Start/Stop kontrolü
PROCESSING_KEY = "processing_enabled"
CONTROL_CH     = "control"

# --- Özellik bayrakları ---
ENABLE_BLUE        = os.getenv("ENABLE_BLUE", "false").lower() == "true"
ENABLE_HEUR_SMOKE  = os.getenv("ENABLE_HEUR_SMOKE", "false").lower() == "true"

# --- Debug bayrakları ---
DEBUG_LOG       = os.getenv("DEBUG_LOG", "true").lower() == "true"
DEBUG_DRAW_RAW  = os.getenv("DEBUG_DRAW_RAW", "true").lower() == "true"

# --- Ek FP azaltma ayarları ---
TOP_FACE_IGNORE_FRAC   = float(os.getenv("TOP_FACE_IGNORE_FRAC", "0.30"))  # kişinin üst %30'u (gözlük) yok say
RAW_MIN_ASPECT         = float(os.getenv("RAW_MIN_ASPECT", "2.0"))         # max/min (ince-uzun alt sınır)
RAW_MAX_ASPECT         = float(os.getenv("RAW_MAX_ASPECT", "12.0"))        # aşırı uzun anomaliyi de ele
RAW_MAX_FRAC_OF_PERSON = float(os.getenv("RAW_MAX_FRAC_OF_PERSON", "0.25"))# ham kutu kişi boyutunun %25'ini geçmesin

# Heuristic SMOKE ayarları (kapalıysa etkisiz)
SMOKE_MIN_AREA = int(os.getenv("SMOKE_MIN_AREA", "1500"))
SMOKE_S_MAX    = int(os.getenv("SMOKE_S_MAX", "70"))
SMOKE_V_MIN    = int(os.getenv("SMOKE_V_MIN", "110"))
SMOKE_MOTION_TH= int(os.getenv("SMOKE_MOTION_TH", "18"))
SMOKE_ERODE    = int(os.getenv("SMOKE_ERODE", "1"))
SMOKE_DILATE   = int(os.getenv("SMOKE_DILATE", "2"))

# YOLO (smoke) model ayarları
SMOKE_MODEL_PATH = os.getenv("SMOKE_MODEL_PATH", "/app/models/smoke.pt")
SMOKE_CONF       = float(os.getenv("SMOKE_CONF", "0.60"))   # compose ile override
SMOKE_IOU        = float(os.getenv("SMOKE_IOU",  "0.45"))
MIN_BOX_AREA     = int(os.getenv("MIN_BOX_AREA", "600"))
MAX_BOX_AREA_RATIO = float(os.getenv("MAX_BOX_AREA_RATIO", "0.03"))
ASPECT_MIN       = float(os.getenv("ASPECT_MIN", "1.6"))

# Kutu kişiye genişletme
BBOX_EXPAND = float(os.getenv("BBOX_EXPAND", "1.6"))
BBOX_PAD    = int(os.getenv("BBOX_PAD", "24"))

ALLOW_DRINKING   = os.getenv("ALLOW_DRINKING", "false").lower() == "true"
ALLOW_CLASSES    = {s.strip().lower() for s in os.getenv("ALLOW_CLASSES", "smoking").split(",") if s.strip()}

# Yayın öncesi kalıcılık şartı
PERSIST_HITS     = int(os.getenv("PERSIST_HITS", "2"))

# --- Person modeli (önerilir) ---
PERSON_MODEL_PATH = os.getenv("PERSON_MODEL_PATH", "").strip()
PERSON_CONF       = float(os.getenv("PERSON_CONF", "0.45"))
PERSON_IMG_SIZE   = int(os.getenv("PERSON_IMG_SIZE", "640"))
REQUIRE_PERSON    = os.getenv("REQUIRE_PERSON", "true").lower() == "true"

os.makedirs(OUTPUT_DIR, exist_ok=True)
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# ===================== YOLO (smoke) =====================
yolo_model = None
yolo_names = {}
yolo_idx_smoking = None
yolo_idx_drinking = None
try:
    from ultralytics import YOLO
    print("[worker][YOLO] model yükleniyor:", SMOKE_MODEL_PATH)
    yolo_model = YOLO(SMOKE_MODEL_PATH)
    yolo_names = yolo_model.model.names if hasattr(yolo_model, "model") else yolo_model.names
    for k, v in yolo_names.items():
        if str(v).lower() == "smoking":
            yolo_idx_smoking = int(k)
        if str(v).lower() == "drinking":
            yolo_idx_drinking = int(k)
    print(f"[worker][YOLO] yüklendi. classes: {yolo_names}")
except Exception as e:
    print("[worker][YOLO] yükleme hatası:", e)

# ===================== YOLO (person) =====================
person_model = None
PERSON_CLASS_IDX = 0
try:
    if PERSON_MODEL_PATH:
        from ultralytics import YOLO
        print("[worker][PERSON] model yükleniyor:", PERSON_MODEL_PATH)
        person_model = YOLO(PERSON_MODEL_PATH)
        pnames = person_model.model.names if hasattr(person_model, "model") else person_model.names
        for k, v in pnames.items():
            if str(v).lower() == "person":
                PERSON_CLASS_IDX = int(k); break
        print("[worker][PERSON] yüklendi. class idx(person) =", PERSON_CLASS_IDX)
except Exception as e:
    print("[worker][PERSON] yükleme hatası:", e)

# ===================== Helpers =====================
def load_first_camera():
    try:
        with open(CAM_FILE, "r", encoding="utf-8") as f:
            cams = jsonlib.load(f)
        if not cams: return None, None
        return cams[0]["id"], cams[0]["ip"]
    except Exception as e:
        print("[worker] cameras.json okunamadı:", e)
        return None, None

def save_jpg(frame, cam_id):
    ts = int(time.time() * 1000)
    name = f"{cam_id}_{ts}.jpg"
    path = os.path.join(OUTPUT_DIR, name)
    ok = cv2.imwrite(path, frame)
    if not ok: raise RuntimeError("cv2.imwrite başarısız")
    for _ in range(20):
        try:
            if os.path.exists(path) and os.path.getsize(path) > 0:
                break
        except: pass
        time.sleep(0.05)
    return name, ts

def make_thumb_b64(frame, max_w=256, quality=70):
    h, w = frame.shape[:2]
    scale = min(max_w/float(w), 1.0)
    if scale < 1.0:
        frame = cv2.resize(frame, (int(w*scale), int(h*scale)))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok: return None
    return base64.b64encode(buf.tobytes()).decode("ascii")

def should_publish_signature(cam_id, label, sig):
    key = f"sig:{cam_id}:{label}:{sig}"
    return bool(r.set(key, "1", ex=COOLDOWN_SEC, nx=True))

def should_publish_track(cam_id, label, tid):
    key = f"trackpub:{cam_id}:{label}:{tid}"
    return bool(r.set(key, "1", ex=COOLDOWN_SEC, nx=True))

def get_pubsub_with_retry():
    while True:
        try:
            ps = r.pubsub()
            ps.subscribe(CONTROL_CH)
            ps.get_message()
            print("[worker] Redis PubSub bağlı.")
            return ps
        except Exception as e:
            print("[worker] Redis bağlanamadı, 2 sn sonra tekrar:", e)
            time.sleep(2)

# ===================== Basit Centroid Tracker (+hits) =====================
class CentroidTracker:
    def __init__(self, max_distance=60, max_missed=10):
        self.next_id = 1
        self.tracks = {}
        self.max_distance = max_distance
        self.max_missed = max_missed
    @staticmethod
    def _centroid(b):
        x, y, w, h = b
        return (x + w/2.0, y + h/2.0)

    @staticmethod
    def _dist(c1, c2):
        return ((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2) ** 0.5

    def update(self, detections):
        new_ids = []
        if not self.tracks:
            for b in detections:
                tid = self.next_id; self.next_id += 1
                self.tracks[tid] = {"bbox": b, "centroid": self._centroid(b), "missed": 0, "hits": 1}
                new_ids.append(tid)
            return self.tracks, new_ids

        track_ids = list(self.tracks.keys())
        track_centers = [self.tracks[i]["centroid"] for i in track_ids]
        det_centers   = [self._centroid(b) for b in detections]

        used_tracks, used_dets = set(), set()
        pairs = []
        for ti, tc in enumerate(track_centers):
            for di, dc in enumerate(det_centers):
                pairs.append((self._dist(tc, dc), ti, di))
        pairs.sort(key=lambda x: x[0])

        for d, ti, di in pairs:
            if ti in used_tracks or di in used_dets:
                continue
            if d <= self.max_distance:
                tid = track_ids[ti]
                self.tracks[tid]["bbox"] = detections[di]
                self.tracks[tid]["centroid"] = det_centers[di]
                self.tracks[tid]["missed"] = 0
                self.tracks[tid]["hits"] = min(self.tracks[tid]["hits"] + 1, 1000)
                used_tracks.add(ti); used_dets.add(di)

        for di, b in enumerate(detections):
            if di in used_dets: continue
            tid = self.next_id; self.next_id += 1
            self.tracks[tid] = {"bbox": b, "centroid": self._centroid(b), "missed": 0, "hits": 1}
            new_ids.append(tid)

        for ti, tid in enumerate(track_ids):
            if ti in used_tracks: continue
            self.tracks[tid]["missed"] += 1
            self.tracks[tid]["hits"] = max(self.tracks[tid]["hits"] - 1, 0)

        to_del = [tid for tid, t in self.tracks.items() if t["missed"] > self.max_missed]
        for tid in to_del: del self.tracks[tid]
        return self.tracks, new_ids

# ===================== BLUE (isteğe bağlı demo) =====================
LOW_BLUE  = np.array([100,  90,  50], dtype=np.uint8)
HIGH_BLUE = np.array([130, 255, 255], dtype=np.uint8)
BLUE_MIN_AREA = 1200

def detect_blue_bboxes(frame_bgr):
    hsv  = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOW_BLUE, HIGH_BLUE)
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.dilate(mask, kernel, iterations=1)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        area = cv2.contourArea(c)
        if area < BLUE_MIN_AREA: continue
        x,y,w,h = cv2.boundingRect(c)
        boxes.append((x,y,w,h))
    return boxes

# ===================== SMOKE (heuristic, isteğe bağlı) =====================
_bgsub = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=16, detectShadows=True)

def detect_smoke_bboxes_heur(frame_bgr):
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    H, S, V = cv2.split(hsv)
    sat_ok = cv2.threshold(S, SMOKE_S_MAX, 255, cv2.THRESH_BINARY_INV)[1]
    val_ok = cv2.threshold(V, SMOKE_V_MIN, 255, cv2.THRESH_BINARY)[1]
    tonal  = cv2.bitwise_and(sat_ok, val_ok)

    fg = _bgsub.apply(frame_bgr, learningRate=0.01)
    _, fg_bin = cv2.threshold(fg, SMOKE_MOTION_TH, 255, cv2.THRESH_BINARY)

    mask = cv2.bitwise_and(tonal, fg_bin)
    k = np.ones((3,3), np.uint8)
    if SMOKE_ERODE > 0:
        mask = cv2.erode(mask, k, iterations=SMOKE_ERODE)
    if SMOKE_DILATE > 0:
        mask = cv2.dilate(mask, k, iterations=SMOKE_DILATE)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        area = cv2.contourArea(c)
        if area < SMOKE_MIN_AREA: continue
        x,y,w,h = cv2.boundingRect(c)
        boxes.append((x,y,w,h))
    return boxes
# ===================== PERSON tespiti =====================
def detect_person_bboxes(frame_bgr):
    if person_model is None:
        return []
    try:
        res = person_model(frame_bgr, verbose=False, conf=PERSON_CONF, iou=0.6, imgsz=PERSON_IMG_SIZE)[0]
    except Exception as e:
        print("[worker][PERSON] infer hata:", e)
        return []
    if not hasattr(res, "boxes") or res.boxes is None:
        return []
    xyxy = res.boxes.xyxy.cpu().numpy()
    cls  = res.boxes.cls.cpu().numpy().astype(int) if hasattr(res.boxes, "cls") else np.zeros((xyxy.shape[0],), dtype=int)

    H, W = frame_bgr.shape[:2]
    out = []
    for i, (x1, y1, x2, y2) in enumerate(xyxy):
        if cls[i] != PERSON_CLASS_IDX:
            continue
        x1 = int(max(0, x1)); y1 = int(max(0, y1))
        x2 = int(min(W-1, x2)); y2 = int(min(H-1, y2))
        w  = max(1, x2 - x1);   h  = max(1, y2 - y1)
        if w*h < 400:  # çok küçük kişileri at
            continue
        out.append((x1, y1, w, h))
    return out

def detect_person_boxes(frame_bgr):
    return detect_person_bboxes(frame_bgr)

# ===================== FP filtre + NMS yardımcıları =====================
def _fp_filter_raw_box(gx1, gy1, gx2, gy2, px, py, pw, ph, name="smoking", sc=0.0):
    """Ham YOLO kutusu için gözlük/şakak + oran + boyut filtreleri."""
    raw_w = gx2 - gx1
    raw_h = gy2 - gy1
    if raw_w <= 0 or raw_h <= 0:
        return False

    # relatif merkez (0: üst, 1: alt)
    rel_cy = ((gy1 + gy2) / 2.0 - py) / max(1, ph)

    # aspect ratio
    aspect = max(raw_w, raw_h) / max(1, min(raw_w, raw_h))

    # debug log
    print(f"[DEBUG_FILTER_RAW] name={name} sc={sc:.2f} rel_cy={rel_cy:.2f} "
          f"w={raw_w} h={raw_h} aspect={aspect:.2f} "
          f"frac_w={raw_w/pw:.2f} frac_h={raw_h/ph:.2f}")

    # 1) üst-yüz bandı
    if rel_cy < TOP_FACE_IGNORE_FRAC:
        return False

    # 2) ince-uzun şartı
    if aspect < RAW_MIN_ASPECT or aspect > RAW_MAX_ASPECT:
        return False

    # 3) kişiye göre aşırı büyükse
    if raw_w > pw * RAW_MAX_FRAC_OF_PERSON or raw_h > ph * RAW_MAX_FRAC_OF_PERSON:
        return False

    return True

def _nms_xyxy(boxes, iou_th=0.3):
    """boxes: [(x1,y1,x2,y2,score,name)] -> aynı sınıfta IoU>th olanları budar."""
    out = []
    boxes = sorted(boxes, key=lambda b: b[4], reverse=True)
    while boxes:
        best = boxes.pop(0)
        bx1,by1,bx2,by2,bs,bn = best
        keep = []
        for b in boxes:
            x1,y1,x2,y2,s,n = b
            if n != bn:
                keep.append(b); continue
            inter_x1 = max(bx1, x1); inter_y1 = max(by1, y1)
            inter_x2 = min(bx2, x2); inter_y2 = min(by2, y2)
            inter = max(0, inter_x2-inter_x1) * max(0, inter_y2-inter_y1)
            a1 = (bx2-bx1)*(by2-by1); a2 = (x2-x1)*(y2-y1)
            iou = inter / float(a1+a2-inter+1e-6)
            if iou <= iou_th:
                keep.append(b)
        out.append(best)
        boxes = keep
    return out

# ===================== YOLO (sigara) tespiti =====================
def _expand_to_person(px, py, pw, ph, W, H):
    cx, cy = px + pw/2.0, py + ph/2.0
    new_w = int(min(W, pw * BBOX_EXPAND) + 2 * BBOX_PAD)
    new_h = int(min(H, ph * BBOX_EXPAND) + 2 * BBOX_PAD)
    nx = int(max(0, cx - new_w/2.0))
    ny = int(max(0, cy - new_h/2.0))
    if nx + new_w > W: new_w = W - nx
    if ny + new_h > H: new_h = H - ny
    return nx, ny, new_w, new_h

def _inside(b, p):
    bx, by, bw, bh = b; px, py, pw, ph = p
    cx = bx + bw/2.0; cy = by + bh/2.0
    return (px <= cx <= px+pw) and (py <= cy <= py+ph)

def detect_yolo_bboxes(frame_bgr):
    """
    1) (Varsa) kişi kutularını bul.
    2) Kişi üst-gövde crop'larında arama (conf gevşek).
    3) Global arama.
    4) FP filtreleri (gözlük/şakak, oran, boyut) ve NMS.
    return: final (x,y,w,h,conf,name), debug_raw (x1,y1,x2,y2,conf,name)
    """
    if yolo_model is None:
        return [], []

    H, W = frame_bgr.shape[:2]
    candidates = []
    debug_raw = []

    persons = detect_person_bboxes(frame_bgr) if person_model is not None else []

    # ---- 2) Kişi içi arama
    for (px, py, pw, ph) in persons:
        pad = int(0.08 * max(pw, ph)) + 12
        y2  = py + int(ph * 0.70)  # üst gövde/baş+eller
        cx0 = max(0, px - pad); cy0 = max(0, py - pad)
        cx1 = min(W, px + pw + pad); cy1 = min(H, y2 + pad)

        crop = frame_bgr[cy0:cy1, cx0:cx1]
        if crop.size == 0: continue

        try:
            res = yolo_model(
                crop, verbose=False,
                conf=max(0.20, SMOKE_CONF * 0.8),
                iou=SMOKE_IOU,
                imgsz=max(int(os.getenv("IMG_SIZE", "640")), 960)
            )[0]
        except Exception as e:
            if DEBUG_LOG: print("[worker][YOLO] person-crop infer hata:", e)
            continue

        if hasattr(res, "boxes") and res.boxes is not None:
            xyxy = res.boxes.xyxy.cpu().numpy()
            conf = res.boxes.conf.cpu().numpy() if hasattr(res, "boxes") and hasattr(res.boxes, "conf") else np.ones((xyxy.shape[0],), dtype=np.float32)
            cls  = res.boxes.cls.cpu().numpy().astype(int) if hasattr(res, "boxes") and hasattr(res.boxes, "cls") else np.zeros((xyxy.shape[0],), dtype=int)

            allowed = set(ALLOW_CLASSES)
            if ALLOW_DRINKING: allowed.add("drinking")

            for i, (x1, y1, x2, y2) in enumerate(xyxy):
                name = str(yolo_names.get(int(cls[i]), cls[i])).lower()
                if name not in allowed: continue
                sc = float(conf[i])

                gx1, gy1 = int(cx0 + x1), int(cy0 + y1)
                gx2, gy2 = int(cx0 + x2), int(cy0 + y2)
                debug_raw.append((gx1, gy1, gx2, gy2, sc, name))

                # FP filtreleri
                if not _fp_filter_raw_box(gx1, gy1, gx2, gy2, px, py, pw, ph, name, sc):
                    continue

                gw = max(1, gx2 - gx1); gh = max(1, gy2 - gy1)
                if REQUIRE_PERSON and not _inside((gx1, gy1, gw, gh), (px, py, pw, ph)):
                    continue

                nx, ny, nw, nh = _expand_to_person(px, py, pw, ph, W, H)
                candidates.append((nx, ny, nw, nh, sc, name))

        # ---- 3) Global arama
    try:
        res_g = yolo_model(
            frame_bgr, verbose=False,
            conf=min(SMOKE_CONF, 0.25),
            iou=SMOKE_IOU,
            imgsz=int(os.getenv("IMG_SIZE", "640"))
        )[0]
        if hasattr(res_g, "boxes") and res_g.boxes is not None:
            xyxy = res_g.boxes.xyxy.cpu().numpy()
            conf = res_g.boxes.conf.cpu().numpy() if hasattr(res_g.boxes, "conf") else np.ones((xyxy.shape[0],), dtype=np.float32)
            cls  = res_g.boxes.cls.cpu().numpy().astype(int) if hasattr(res_g.boxes, "cls") else np.zeros((xyxy.shape[0],), dtype=int)

            allowed = set(ALLOW_CLASSES)
            if ALLOW_DRINKING: allowed.add("drinking")

            for i, (x1, y1, x2, y2) in enumerate(xyxy):
                name = str(yolo_names.get(int(cls[i]), cls[i])).lower()
                if name not in allowed: continue
                sc = float(conf[i])

                gx1, gy1 = int(max(0, x1)), int(max(0, y1))
                gx2, gy2 = int(min(W-1, x2)), int(min(H-1, y2))
                debug_raw.append((gx1, gy1, gx2, gy2, sc, name))

                gw = max(1, gx2 - gx1); gh = max(1, gy2 - gy1)

                if REQUIRE_PERSON and persons:
                    # en çok örtüşen kişiyi seç
                    best_iou = 0.0; mx=my=mw=mh=0
                    for (px, py, pw, ph) in persons:
                        xx1 = max(gx1, px); yy1 = max(gy1, py)
                        xx2 = min(gx2, px+pw); yy2 = min(gy2, py+ph)
                        inter = max(0, xx2-xx1) * max(0, yy2-yy1)
                        iou_p = inter / float(gw*gh + pw*ph - inter + 1e-6)
                        if iou_p > best_iou:
                            best_iou = iou_p; mx, my, mw, mh = px, py, pw, ph
                    if best_iou < 0.05:
                        continue

                    # FP filtreleri (kişiye göre)
                    if not _fp_filter_raw_box(gx1, gy1, gx2, gy2, mx, my, mw, mh, name, sc):
                        continue

                    nx, ny, nw, nh = _expand_to_person(mx, my, mw, mh, W, H)
                    candidates.append((nx, ny, nw, nh, sc, name))
                else:
                    nx, ny, nw, nh = _expand_to_person(gx1, gy1, gw, gh, W, H)
                    candidates.append((nx, ny, nw, nh, sc, name))
    except Exception as e:
        if DEBUG_LOG: print("[worker][YOLO] global infer hata:", e)

    # ---- 4) Son filtre ve rapor ----
    frame_area = W * H
    final = []
    for (x, y, w, h, sc, name) in candidates:
        area = w * h
        if area < MIN_BOX_AREA: continue
        if area > frame_area * MAX_BOX_AREA_RATIO: continue
        final.append((x, y, w, h, sc, name))

    # ham kutulara hafif NMS (debug görünüm daha temiz)
    debug_raw = _nms_xyxy(debug_raw, iou_th=0.3)

    if DEBUG_LOG:
        print(f"[DEBUG] persons={len(persons)} raw_yolo={len(debug_raw)} final={len(final)}")

    return final, debug_raw

# ===================== Main Loop =====================
def main():
    cam_id, rtsp = load_first_camera()
    if not rtsp:
        print("[worker] Kamera yok. /app/data/cameras.json doldur.")
        time.sleep(5); return

    cap = cv2.VideoCapture(rtsp)
    if not cap.isOpened():
        print(f"[worker] RTSP açılamadı: {rtsp}. Deneniyor…")

    trackers = {
        "smoking":   CentroidTracker(max_distance=80, max_missed=12),
        "drinking":  CentroidTracker(max_distance=80, max_missed=12),
        "blue":      CentroidTracker(max_distance=60, max_missed=10),
        "smoke_heur":CentroidTracker(max_distance=80, max_missed=12),
    }

    pubsub = get_pubsub_with_retry()

    frame_i = 0
    while True:
        _ = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.001)
        if r.get(PROCESSING_KEY) != "1":
            time.sleep(0.2); continue

        if not cap.isOpened():
            time.sleep(1.0); cap.open(rtsp); continue

        ok, frame = cap.read()
        if not ok:
            time.sleep(0.03); continue

        frame_i += 1
        if frame_i % SAMPLE_EVERY != 0:
            continue

        annotated = frame.copy()
        events = []

        # ---------- YOLO smoking/drinking ----------
        dets, debug_raw = detect_yolo_bboxes(frame)

        if DEBUG_DRAW_RAW:
            for (rx1, ry1, rx2, ry2, rsc, rname) in debug_raw:
                cv2.rectangle(annotated, (rx1, ry1), (rx2, ry2), (200, 0, 200), 1)
                cv2.putText(annotated, f"{rname}:{rsc:.2f}", (rx1, max(0, ry1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 0, 200), 1, cv2.LINE_AA)

        det_map = {"smoking": [], "drinking": []}
        for x, y, w, h, score, name in dets:
            det_map.get(name, []).append((x, y, w, h, score))

        for label in ("smoking", "drinking"):
            if label == "drinking" and not ALLOW_DRINKING:
                continue
            boxes = [(x, y, w, h) for (x, y, w, h, s) in det_map[label]]
            tracks, _ = trackers[label].update(boxes)

            for tid, t in list(tracks.items()):
                x, y, w, h = t["bbox"]
                cx, cy = int(t["centroid"][0]), int(t["centroid"][1])

                if t["hits"] < PERSIST_HITS:
                    continue
                if not should_publish_track(cam_id, label, tid):
                    continue

                color = (0, 255, 255) if label == "smoking" else (0, 165, 255)
                cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
                cv2.putText(annotated, f"{label} id={tid}", (x, max(0, y - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

                score = 0.0
                if det_map[label]:
                    def d2(b):
                        bx, by, bw, bh, s = b
                        cc = (bx + bw/2, by + bh/2)
                        return (cc[0]-cx)**2 + (cc[1]-cy)**2
                    bx, by, bw, bh, s = min(det_map[label], key=d2)
                    score = float(s)

                events.append((label, tid, (x, y, w, h), score))

        # ---------- (opsiyonel) BLUE ----------
        if ENABLE_BLUE:
            blue_boxes = detect_blue_bboxes(frame)
            tracks, new_ids = trackers["blue"].update(blue_boxes)
            for tid in new_ids:
                t = tracks.get(tid)
                if t is None: continue
                x, y, w, h = t["bbox"]
                cx, cy = int(t["centroid"][0]), int(t["centroid"][1])
                sig = f"{(cx//GRID)}-{(cy//GRID)}"
                if not should_publish_signature(cam_id, "blue", sig):
                    continue
                cv2.rectangle(annotated, (x,y), (x+w,y+h), (255,0,0), 2)
                cv2.putText(annotated, f"blue id={tid}", (x, max(0, y-8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,0,0), 2, cv2.LINE_AA)
                events.append(("blue", tid, (x,y,w,h), 1.0))

        # ---------- (opsiyonel) HEURISTIC SMOKE ----------
        if ENABLE_HEUR_SMOKE:
            smoke_boxes = detect_smoke_bboxes_heur(frame)
            tracks, new_ids = trackers["smoke_heur"].update(smoke_boxes)
            for tid in new_ids:
                t = tracks.get(tid)
                if t is None: continue
                x, y, w, h = t["bbox"]
                cx, cy = int(t["centroid"][0]), int(t["centroid"][1])
                sig = f"{(cx//GRID)}-{(cy//GRID)}"
                if not should_publish_signature(cam_id, "smoke", sig):
                    continue
                cv2.rectangle(annotated, (x,y), (x+w,y+h), (0,255,255), 2)
                cv2.putText(annotated, f"smoke id={tid}", (x, max(0, y-8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2, cv2.LINE_AA)
                events.append(("smoke", tid, (x,y,w,h), 0.0))

        # ---------- Yayın ----------
        if events:
            try:
                fname, ts = save_jpg(annotated, cam_id)
                thumb = make_thumb_b64(annotated, max_w=256, quality=70)
            except Exception as e:
                print("[worker] kaydet/thumbnail hata:", e)
                time.sleep(0.01); continue

            for label, tid, (x,y,w,h), score in events:
                ev = {
                    "id": str(uuid.uuid4()),
                    "cam_id": cam_id,
                    "label": label,
                    "track_id": tid,
                    "bbox": [int(x), int(y), int(w), int(h)],
                    "score": round(float(score), 3),
                    "image": fname,
                    "thumb": thumb,
                    "ts": ts,
                }
                try:
                    r.publish(CHANNEL, jsonlib.dumps(ev))
                except Exception as e:
                    print("[worker] publish hata:", e)

        time.sleep(0.01)

if __name__ == "__main__":
    main()
