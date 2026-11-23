"""
Skrip Deteksi Kelengkapan APD Real-Time (YOLOv8 + OpenCV + HTTP Alert)
Fitur:
- Input Kamera Webcam (0) atau RTSP Stream IP Camera
- Inferensi Ultralytics YOLOv8
- Logika Anti-Flicker (Pelanggaran harus bertahan >= 2 detik)
- Logika Cooldown (Minimal jeda 10 detik antar alert)
- Simpan snapshot dengan bounding box ke folder ../snapshots/
- Kirim HTTP POST Alert ke backend lokal FastAPI
- Opsi Mode Headless (tanpa GUI cv2.imshow) untuk server tanpa monitor
"""

import os
import sys
import time
import argparse
import threading
import ctypes
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
import requests

# Lokasi File Audio Sirine Notifikasi
AUDIO_ALARM_PATH = Path(__file__).resolve().parent.parent / "audio" / "alarm.mp3"

# ----------------- KONFIGURASI SISTEM -----------------
# 0 untuk webcam bawaan/USB, atau ganti dengan string URL RTSP seperti:
# "rtsp://admin:password@192.168.1.100:554/stream1"
VIDEO_SOURCE = 0

# Identitas Kamera
CAMERA_NAME = "Kamera 01 - Area Kerja"

# Lokasi Model YOLO (.pt)
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "best.pt"

# URL Endpoint Backend Alert
BACKEND_URL = "http://127.0.0.1:8000/api/alert"

# Folder Penyimpanan Bukti Snapshot
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "snapshots"

# Daftar 3 APD Utama yang Diawasi: Helm Kepala, Rompi, dan Sepatu Boot
TARGET_APD_MAP = {
    # --- HELM KEPALA ---
    "no-helmet": {"type": "violation", "canonical": "no_helmet", "label": "TIDAK PAKAI HELM", "part": "head"},
    "no_helmet": {"type": "violation", "canonical": "no_helmet", "label": "TIDAK PAKAI HELM", "part": "head"},
    "no helmet": {"type": "violation", "canonical": "no_helmet", "label": "TIDAK PAKAI HELM", "part": "head"},
    "no-hardhat": {"type": "violation", "canonical": "no_helmet", "label": "TIDAK PAKAI HELM", "part": "head"},
    "no_hardhat": {"type": "violation", "canonical": "no_helmet", "label": "TIDAK PAKAI HELM", "part": "head"},
    "hard_hat": {"type": "safe", "canonical": "helmet", "label": "HELM KEPALA", "part": "head"},
    "hardhat": {"type": "safe", "canonical": "helmet", "label": "HELM KEPALA", "part": "head"},
    "helmet": {"type": "safe", "canonical": "helmet", "label": "HELM KEPALA", "part": "head"},

    # --- ROMPI (VEST) ---
    "no-vest": {"type": "violation", "canonical": "no_vest", "label": "TIDAK PAKAI ROMPI", "part": "torso"},
    "no_vest": {"type": "violation", "canonical": "no_vest", "label": "TIDAK PAKAI ROMPI", "part": "torso"},
    "no vest": {"type": "violation", "canonical": "no_vest", "label": "TIDAK PAKAI ROMPI", "part": "torso"},
    "no-safety-vest": {"type": "violation", "canonical": "no_vest", "label": "TIDAK PAKAI ROMPI", "part": "torso"},
    "no_safety_vest": {"type": "violation", "canonical": "no_vest", "label": "TIDAK PAKAI ROMPI", "part": "torso"},
    "vest": {"type": "safe", "canonical": "vest", "label": "ROMPI SAFETY", "part": "torso"},

    # --- SEPATU BOOT ---
    "no-boots": {"type": "violation", "canonical": "no_boots", "label": "TIDAK PAKAI SEPATU BOOT", "part": "feet"},
    "no_boots": {"type": "violation", "canonical": "no_boots", "label": "TIDAK PAKAI SEPATU BOOT", "part": "feet"},
    "no boots": {"type": "violation", "canonical": "no_boots", "label": "TIDAK PAKAI SEPATU BOOT", "part": "feet"},
    "no-shoes": {"type": "violation", "canonical": "no_boots", "label": "TIDAK PAKAI SEPATU BOOT", "part": "feet"},
    "no_shoes": {"type": "violation", "canonical": "no_boots", "label": "TIDAK PAKAI SEPATU BOOT", "part": "feet"},
    "boots": {"type": "safe", "canonical": "boots", "label": "SEPATU BOOT", "part": "feet"},
    "shoes": {"type": "safe", "canonical": "boots", "label": "SEPATU BOOT", "part": "feet"},
}

# Ambang batas kepercayaan deteksi (Confidence)
CONFIDENCE_THRESHOLD = 0.30

# Ambang batas khusus per kategori APD
PER_CLASS_CONF = {
    "vest": 0.30,        # Responsif mendeteksi rompi safety (oranye / hijau stabilo)
    "no_vest": 0.30,     # Sensitif mendeteksi baju biasa (tanpa rompi)
    "helmet": 0.30,      # Helm keselamatan (mendukung helm merah, kuning, putih)
    "no_helmet": 0.30,   # Sensitif mendeteksi kepala tanpa helm
    "boots": 0.25,       # Kaki telanjang akan diverifikasi oleh is_barefoot()
    "no_boots": 0.25     # Sensitif mendeteksi tanpa sepatu boot
}

# Anti-flicker: Pelanggaran harus bertahan minimal durasi ini (detik)
PERSISTENCE_THRESHOLD_SEC = 2.0

# Cooldown: Jeda waktu sebelum alert baru untuk pelanggaran berikutnya dapat dikirim (detik)
COOLDOWN_SEC = 10.0

# Pastikan folder snapshot dibuat
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Detektor APD Real-Time YOLO")
    parser.add_argument(
        "--source", 
        type=str, 
        default=str(VIDEO_SOURCE), 
        help="Sumber video: 0 untuk webcam atau URL rtsp://..."
    )
    parser.add_argument(
        "--model", 
        type=str, 
        default=str(DEFAULT_MODEL_PATH), 
        help="Path ke file weights YOLO (.pt)"
    )
    parser.add_argument(
        "--camera-name", 
        type=str, 
        default=CAMERA_NAME, 
        help="Nama identitas kamera"
    )
    parser.add_argument(
        "--headless", 
        action="store_true", 
        help="Jalankan dalam mode headless tanpa jendela cv2.imshow"
    )
    parser.add_argument(
        "--conf", 
        type=float, 
        default=CONFIDENCE_THRESHOLD, 
        help="Threshold confidence model YOLO"
    )
    parser.add_argument(
        "--imgsz", 
        type=int, 
        default=480, 
        help="Resolusi inferensi gambar YOLO (480 untuk performa tinggi & responsif)"
    )
    return parser.parse_args()


def load_yolo_model(model_path_str: str):
    """
    Memuat model Ultralytics YOLO.
    Jika file best.pt belum ada di folder models/, gunakan yolov8n.pt sebagai fallback testing.
    """
    from ultralytics import YOLO

    model_path = Path(model_path_str)
    if not model_path.exists():
        print(f"[PERINGATAN] File model kustom '{model_path}' tidak ditemukan.")
        print("[INFO] Menggunakan model dasar 'yolov8n.pt' untuk pengujian koneksi...")
        print("[TIPS] Letakkan bobot model APD terlatih Anda di folder: models/best.pt\n")
        return YOLO("yolov8n.pt")
    
    print(f"[INFO] Memuat model APD dari: {model_path}")
    return YOLO(str(model_path))


def is_violation_class(class_name: str) -> bool:
    """Mengecek apakah nama kelas terdeteksi merupakan salah satu dari 3 pelanggaran APD (Helm, Rompi, Sepatu Boot)."""
    c_clean = class_name.lower().strip()
    item = TARGET_APD_MAP.get(c_clean)
    return item is not None and item["type"] == "violation"


def is_barefoot(crop):
    """
    Mendeteksi apakah area kaki adalah kaki telanjang (kulit manusia), bukan sepatu safety boot K3.
    Menggunakan aturan Peer et al. RGB + YCrCb color space yang membedakan kulit asli
    dari lantai/background putih-abu dan sepatu hitam/cokelat K3.
    """
    if crop is None or crop.size == 0:
        return False

    b = crop[:, :, 0].astype(int)
    g = crop[:, :, 1].astype(int)
    r = crop[:, :, 2].astype(int)

    # Aturan warna kulit manusia: R dominan, selisih R-G dan R-B tegas (bukan grayscale lantai/sepatu)
    rgb_skin = (
        (r > 95) & (g > 40) & (b > 20) &
        ((np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)) > 15) &
        (np.abs(r - g) > 10) &
        (r > g) & (r > b)
    )

    ycrcb = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    ycrcb_skin = (cr > 135) & (cb < 130) & (cr > cb)

    skin_ratio = float(np.mean(rgb_skin & ycrcb_skin))

    # Cek persentase warna gelap (khas sepatu safety boot hitam/kulit gelap)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    dark_ratio = float(np.mean(hsv[:, :, 2] < 70))

    # Jika terdeteksi warna kulit >= 2.0% -> Kaki telanjang!
    if skin_ratio >= 0.020:
        return True
    # Jika dominan gelap (>= 20%) dan hampir nol kulit (< 1.5%) -> Sepatu boot
    if dark_ratio >= 0.20 and skin_ratio < 0.015:
        return False
    # Threshold sensitifitas cadangan
    return skin_ratio >= 0.015


def has_fluorescent_vest(crop):
    """
    Mendeteksi apakah area torso memakai rompi reflektif fluorescent K3 (kuning stabilo / oranye terang).
    Mendukung kondisi pencahayaan indoor webcam ruangan yang dinamis.
    """
    if crop is None or crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Hijau/Kuning stabilo K3 (toleransi pencahayaan indoor luas): H 22-75, Saturation >= 35, Brightness >= 45
    lime_mask = (
        (hsv[:, :, 0] >= 22) & (hsv[:, :, 0] <= 75) &
        (hsv[:, :, 1] >= 35) & (hsv[:, :, 2] >= 45)
    )
    # Oranye terang K3: H 5-22, Saturation >= 55, Brightness >= 60
    orange_mask = (
        (hsv[:, :, 0] >= 5) & (hsv[:, :, 0] <= 22) &
        (hsv[:, :, 1] >= 55) & (hsv[:, :, 2] >= 60)
    )
    vest_ratio = float(np.mean(lime_mask | orange_mask))
    return vest_ratio >= 0.07


def is_spatially_valid(apd_box: tuple, worker_boxes: list, part: str) -> bool:
    """
    Memvalidasi posisi objek APD agar sesuai dengan anatomi tubuh pekerja:
    - Head (Helm): Berada di 30% bagian teratas tubuh pekerja (mencegah jempol/jari dikira helm).
    - Torso (Rompi): Titik tengah rompi berada di dada/badan pekerja (0.05 - 0.85 tinggi pekerja).
    - Feet (Sepatu): Berada di 40% bagian paling bawah tubuh pekerja.
    """
    if not worker_boxes or part == "any":
        return True

    bx1, by1, bx2, by2 = apd_box
    b_center_x = (bx1 + bx2) / 2
    b_center_y = (by1 + by2) / 2

    for wx1, wy1, wx2, wy2 in worker_boxes:
        w_height = wy2 - wy1
        w_width = wx2 - wx1
        margin_x = w_width * 0.40

        # Harus berada dalam rentang horizontal tubuh pekerja
        if b_center_x < wx1 - margin_x or b_center_x > wx2 + margin_x:
            continue

        if part == "head":
            if by1 <= wy1 + 0.30 * w_height:
                return True
        elif part == "torso":
            if b_center_y >= wy1 + 0.05 * w_height and b_center_y <= wy1 + 0.85 * w_height:
                return True
        elif part == "feet":
            if by2 >= wy1 + 0.60 * w_height:
                return True

    return False


class BoxSmoother:
    """
    Menghaluskan pergerakan bounding box antar-frame (EMA Smoothing).
    Mencegah getaran/jitter dan membuat tracking terlihat mulus dan stabil.
    """
    def __init__(self, alpha=0.65):
        self.history = {}
        self.alpha = alpha

    def smooth(self, key, box):
        if key not in self.history:
            self.history[key] = list(box)
            return box
        prev = self.history[key]
        smoothed = [
            int(self.alpha * box[i] + (1.0 - self.alpha) * prev[i])
            for i in range(4)
        ]
        self.history[key] = smoothed
        return smoothed


is_alarm_playing = False
alarm_lock = threading.Lock()

def start_local_alarm_loop():
    """
    Memulai pemutaran sirine MP3 secara berulang-ulang (looping) di speaker PC.
    Dijalankan di thread terpisah agar proses inferensi video tidak terganggu.
    """
    global is_alarm_playing
    if not AUDIO_ALARM_PATH.exists() or not sys.platform.startswith("win"):
        return

    with alarm_lock:
        if is_alarm_playing:
            return
        is_alarm_playing = True

    def _loop():
        global is_alarm_playing
        try:
            winmm = ctypes.windll.winmm
            winmm.mciSendStringW('close apd_alarm', None, 0, None)
            cmd_open = f'open "{AUDIO_ALARM_PATH}" type mpegvideo alias apd_alarm'
            winmm.mciSendStringW(cmd_open, None, 0, None)
            # Putar audio secara berulang-ulang (repeat/loop)
            winmm.mciSendStringW('play apd_alarm repeat', None, 0, None)
        except Exception:
            pass

    threading.Thread(target=_loop, daemon=True).start()


def stop_local_alarm_loop():
    """Menghentikan pemutaran suara sirine MP3 looping."""
    global is_alarm_playing
    with alarm_lock:
        if not is_alarm_playing:
            return
        is_alarm_playing = False

    try:
        winmm = ctypes.windll.winmm
        winmm.mciSendStringW('stop apd_alarm', None, 0, None)
        winmm.mciSendStringW('close apd_alarm', None, 0, None)
    except Exception:
        pass


def send_alert_to_backend(camera_name: str, violations: list, snapshot_filename: str, confidence: float):
    """Mengirim data pelanggaran ke backend server lokal FastAPI dan memicu sirine alarm looping."""
    # Nyalakan sirine alarm looping di speaker komputer
    start_local_alarm_loop()

    payload = {
        "camera_id": camera_name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "violations": violations,
        "snapshot": snapshot_filename,
        "confidence": round(confidence, 2)
    }

    try:
        response = requests.post(BACKEND_URL, json=payload, timeout=3.0)
        if response.status_code == 200:
            print(f"[ALERT BERHASIL DIKIRIM] {violations} terdeteksi! Response: {response.json().get('status')}")
        else:
            print(f"[GAGAL KIRIM ALERT] Status code: {response.status_code}, Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"[KONEKSI ERROR] Tidak dapat terhubung ke server backend di {BACKEND_URL}: {e}")


def main():
    args = parse_arguments()

    # Tentukan sumber video (integer untuk webcam atau string untuk RTSP/video file)
    source = int(args.source) if args.source.isdigit() else args.source

    print("=" * 60)
    print("      SISTEM DETEKSI KELENGKAPAN APD (ON-PREMISE)")
    print("=" * 60)
    print(f"Sumber Video          : {source}")
    print(f"Nama Kamera           : {args.camera_name}")
    print(f"Model YOLO            : {args.model}")
    print(f"Confidence Threshold  : {args.conf}")
    print(f"Anti-Flicker Threshold: {PERSISTENCE_THRESHOLD_SEC} detik")
    print(f"Cooldown Period       : {COOLDOWN_SEC} detik")
    print(f"Mode Headless         : {'Ya' if args.headless else 'Tidak (Menampilkan GUI)'}")
    print(f"Target Backend        : {BACKEND_URL}")
    print("=" * 60)

    # Inisialisasi Model YOLO
    model = load_yolo_model(args.model)

    # Inisialisasi Video Capture
    print(f"[INFO] Membuka video capture dari '{source}'...")
    if isinstance(source, int) and sys.platform.startswith("win"):
        # Gunakan DirectShow (CAP_DSHOW) di Windows untuk mencegah blank screen / timeout MSMF pada USB webcam
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(source)
    else:
        cap = cv2.VideoCapture(source)

    # Atur buffer size kecil dan resolusi optimal untuk meminimalkan latency & memaksimalkan FPS
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if isinstance(source, int):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print(f"[ERROR] Gagal membuka sumber video: {source}")
        print("Pastikan webcam terpasang atau URL RTSP dapat diakses dari jaringan ini.")
        sys.exit(1)

    print("[INFO] Video stream aktif. Memulai inferensi APD real-time...")
    print("Tekan 'q' pada jendela tampilan untuk keluar.\n")

    # Inisialisasi Box Smoother untuk animasi bounding box yang mulus (tanpa flicker)
    smoother = BoxSmoother(alpha=0.65)

    # Variabel State Anti-Flicker & Cooldown
    violation_start_time = None
    last_alert_time = 0.0
    active_violations = set()
    highest_conf = 0.0

    fps_time = time.time()
    frame_count = 0
    fps = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("[PERINGATAN] Frame kosong atau koneksi stream terputus. Mencoba membaca ulang...")
                time.sleep(0.5)
                continue

            current_time = time.time()
            frame_count += 1
            if current_time - fps_time >= 1.0:
                fps = frame_count / (current_time - fps_time)
                frame_count = 0
                fps_time = current_time

            # Jalankan Tracking YOLO dengan ByteTrack agar deteksi stabil dan tidak patah-patah
            results = model.track(
                frame, 
                persist=True, 
                tracker="bytetrack.yaml", 
                conf=0.25, 
                imgsz=args.imgsz, 
                verbose=False
            )
            detected_in_frame = []
            frame_highest_conf = 0.0

            # Salin frame untuk rendering visual
            annotated_frame = frame.copy()

            if results and len(results) > 0:
                result = results[0]
                boxes = result.boxes

                # 1. Kumpulkan posisi pekerja (Worker / Person) untuk validasi spasial posisi APD
                worker_boxes = []
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    cls_name = model.names.get(cls_id, "").lower().strip()
                    conf = float(box.conf[0].item())
                    if cls_name in ("worker", "person") and conf >= 0.35:
                        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                        track_id = int(box.id[0].item()) if box.id is not None else 0
                        # Smooth worker box
                        sx1, sy1, sx2, sy2 = smoother.smooth(f"worker_{track_id}", (x1, y1, x2, y2))
                        worker_boxes.append((sx1, sy1, sx2, sy2))
                        # Tampilkan outline halus posisi pekerja
                        worker_color = (230, 180, 70)  # Cyan-kuning (BGR)
                        w_label = f"Pekerja #{track_id} ({conf:.2f})" if track_id > 0 else f"Pekerja ({conf:.2f})"
                        cv2.rectangle(annotated_frame, (sx1, sy1), (sx2, sy2), worker_color, 1)
                        cv2.putText(annotated_frame, w_label, (sx1, max(14, sy1 - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, worker_color, 1, cv2.LINE_AA)

                # 2. Proses deteksi APD
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    cls_name = model.names.get(cls_id, f"class_{cls_id}")
                    conf = float(box.conf[0].item())
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    track_id = int(box.id[0].item()) if box.id is not None else 0

                    clean_name = cls_name.lower().strip()
                    apd_info = TARGET_APD_MAP.get(clean_name)

                    if apd_info:
                        canonical = apd_info["canonical"]
                        min_conf = PER_CLASS_CONF.get(canonical, args.conf)

                        # Filter ambang batas kepercayaan
                        if conf < min_conf:
                            continue

                        # Filter posisi tubuh (mencegah false positive seperti jempol tangan dikira helm)
                        part = apd_info.get("part", "any")
                        if not is_spatially_valid((x1, y1, x2, y2), worker_boxes, part):
                            continue

                        # Ambil crop area deteksi untuk verifikasi tekstur & warna (skin-tone & fluorescent)
                        crop = frame[max(0, y1):min(frame.shape[0], y2), max(0, x1):min(frame.shape[1], x2)]

                        is_violation = apd_info["type"] == "violation"
                        label_name = apd_info["label"]

                        # --- VERIFIKASI SEPATU BOOT (Skin-tone check) ---
                        if canonical in ("boots", "no_boots"):
                            if is_barefoot(crop):
                                # Terdeteksi warna kulit manusia -> KAKI TELANJANG!
                                is_violation = True
                                canonical = "no_boots"
                                label_name = "TIDAK PAKAI SEPATU BOOT"
                            elif canonical == "boots":
                                is_violation = False
                                label_name = "SEPATU BOOT"

                        # --- VERIFIKASI ROMPI (Responsif & Anti-flicker) ---
                        elif canonical in ("vest", "no_vest"):
                            is_vest_colored = has_fluorescent_vest(crop)
                            # Jika model mendeteksi rompi ATAU warna rompi stabilo K3 terdeteksi
                            if canonical == "vest" or is_vest_colored:
                                is_violation = False
                                canonical = "vest"
                                label_name = "ROMPI SAFETY"
                            else:
                                is_violation = True
                                canonical = "no_vest"
                                label_name = "TIDAK PAKAI ROMPI"

                        # Smooth bounding box untuk visual yang stabil dan tidak jitter
                        smooth_key = f"{canonical}_{track_id}" if track_id > 0 else f"{canonical}_{x1//30}_{y1//30}"
                        sx1, sy1, sx2, sy2 = smoother.smooth(smooth_key, (x1, y1, x2, y2))

                        if is_violation:
                            detected_in_frame.append(canonical)
                            if conf > frame_highest_conf:
                                frame_highest_conf = conf

                            # Bounding box merah untuk Pelanggaran APD
                            box_color = (0, 0, 255)  # Merah (BGR)
                            label = f"X {label_name} ({conf:.2f})"
                        else:
                            # Bounding box hijau untuk APD Lengkap
                            box_color = (0, 255, 0)  # Hijau (BGR)
                            label = f"V {label_name} ({conf:.2f})"

                        cv2.rectangle(annotated_frame, (sx1, sy1), (sx2, sy2), box_color, 2)
                        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                        cv2.rectangle(annotated_frame, (sx1, max(0, sy1 - 20)), (sx1 + w, sy1), box_color, -1)
                        cv2.putText(annotated_frame, label, (sx1, max(14, sy1 - 5)), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

            # ----------------- LOGIKA ANTI-FLICKER & COOLDOWN -----------------
            if len(detected_in_frame) > 0:
                if violation_start_time is None:
                    # Mulai menghitung durasi pelanggaran
                    violation_start_time = current_time
                    active_violations = set(detected_in_frame)
                    highest_conf = frame_highest_conf
                else:
                    # Akumulasi jenis pelanggaran yang terdeteksi selama durasi aktif
                    active_violations.update(detected_in_frame)
                    highest_conf = max(highest_conf, frame_highest_conf)

                duration = current_time - violation_start_time

                # Tampilkan status durasi di frame
                status_text = f"Pelanggaran Terdeteksi: {duration:.1f}s / {PERSISTENCE_THRESHOLD_SEC}s"
                cv2.putText(annotated_frame, status_text, (20, 60), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)

                # Cek apakah durasi telah melewati batas anti-flicker (misal 2 detik)
                if duration >= PERSISTENCE_THRESHOLD_SEC:
                    time_since_last_alert = current_time - last_alert_time

                    if time_since_last_alert >= COOLDOWN_SEC:
                        # Trigger alert baru!
                        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                        snapshot_filename = f"apd_violation_{timestamp_str}.jpg"
                        snapshot_path = SNAPSHOT_DIR / snapshot_filename

                        # Tambahkan watermark waktu dan nama kamera pada file snapshot
                        snapshot_image = annotated_frame.copy()
                        watermark = f"{args.camera_name} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        cv2.putText(snapshot_image, watermark, (20, snapshot_image.shape[0] - 20),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)

                        # Simpan snapshot ke disk
                        cv2.imwrite(str(snapshot_path), snapshot_image)
                        print(f"\n[ALERT TRIGGERED] Pelanggaran konsisten ({duration:.1f}s) terdeteksi!")
                        print(f"Snapshot tersimpan di: {snapshot_path}")

                        # Kirim alert ke backend FastAPI
                        send_alert_to_backend(
                            camera_name=args.camera_name,
                            violations=list(active_violations),
                            snapshot_filename=snapshot_filename,
                            confidence=highest_conf
                        )

                        last_alert_time = current_time
                        # Reset tracking durasi setelah alert terkirim
                        violation_start_time = None
                        active_violations.clear()
                        highest_conf = 0.0
                    else:
                        cooldown_left = COOLDOWN_SEC - time_since_last_alert
                        cd_text = f"Cooldown: {cooldown_left:.1f}s"
                        cv2.putText(annotated_frame, cd_text, (20, 90), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
            else:
                # Jika tidak ada pelanggaran pada frame saat ini, reset timer anti-flicker
                violation_start_time = None
                active_violations.clear()
                highest_conf = 0.0

            # Render info FPS dan Kamera
            cv2.putText(annotated_frame, f"{args.camera_name} | FPS: {fps:.1f}", (20, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)

            # Tampilkan status jika alarm lokal sedang berbunyi
            if is_alarm_playing:
                cv2.putText(annotated_frame, "SIRINE AKTIF (Tekan 's' utk senyap)", (20, annotated_frame.shape[0] - 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)

            # Tampilkan GUI jika tidak dalam mode headless
            if not args.headless:
                cv2.imshow("Monitor Deteksi APD Real-Time", annotated_frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('s'):  # Tekan 's' untuk membisukan sirine
                    stop_local_alarm_loop()
                    print("[INFO] Sirine alarm lokal dimatikan oleh pengguna.")
                elif key == ord('q') or key == 27:  # 'q' atau ESC
                    print("[INFO] Penghentian sistem oleh pengguna...")
                    break

    except KeyboardInterrupt:
        print("\n[INFO] Deteksi dihentikan dengan KeyboardInterrupt.")
    finally:
        stop_local_alarm_loop()
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()
        print("[INFO] Stream video ditutup.")


if __name__ == "__main__":
    main()
