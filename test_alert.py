"""
Skrip Pengujian / Simulasi Alert APD ke Backend FastAPI
Berguna untuk menguji apakah WebSocket, audio alarm, dan dashboard web berfungsi
tanpa harus menyalakan kamera fisik terlebih dahulu.
"""

import time
import requests
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np

BACKEND_URL = "http://127.0.0.1:8000/api/alert"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

def generate_dummy_snapshot(filename: str, violations: list, camera_name: str):
    """Membuat gambar dummy simulasi pelanggaran APD."""
    # Buat kanvas gambar 640x480 warna abu gelap
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (35, 30, 25)

    # Tambahkan kotak simulasi pelanggar
    cv2.rectangle(img, (180, 100), (460, 420), (0, 0, 255), 3)
    cv2.putText(img, "SIMULASI PELANGGARAN APD", (190, 80), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # Info teks
    y = 150
    for v in violations:
        cv2.putText(img, f"X PELANGGARAN: {v.upper()}", (200, y), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 165, 255), 2)
        y += 40

    # Timestamp & camera tag
    watermark = f"{camera_name} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    cv2.putText(img, watermark, (20, 460), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

    file_path = SNAPSHOT_DIR / filename
    cv2.imwrite(str(file_path), img)
    return filename

def main():
    print("=" * 55)
    print("     PENGUJIAN SIMULASI ALERT APD KE DASHBOARD")
    print("=" * 55)

    scenarios = [
        {
            "camera_id": "Kamera 01 - Gerbang Masuk",
            "violations": ["no_helmet"],
            "conf": 0.91
        },
        {
            "camera_id": "Kamera 02 - Area Perancah",
            "violations": ["no_helmet", "no_vest"],
            "conf": 0.88
        },
        {
            "camera_id": "Kamera 03 - Gudang Logistik",
            "violations": ["no_boots"],
            "conf": 0.85
        }
    ]

    for idx, sc in enumerate(scenarios, 1):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"simulasi_apd_{ts}_{idx}.jpg"
        generate_dummy_snapshot(filename, sc["violations"], sc["camera_id"])

        payload = {
            "camera_id": sc["camera_id"],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "violations": sc["violations"],
            "snapshot": filename,
            "confidence": sc["conf"]
        }

        print(f"\n[Mengirim Skenario {idx}] Pelanggaran: {sc['violations']} di {sc['camera_id']}...")
        try:
            res = requests.post(BACKEND_URL, json=payload, timeout=3.0)
            if res.status_code == 200:
                print(f" -> Sukses! Respon backend: {res.json()}")
            else:
                print(f" -> Gagal. Status: {res.status_code}, Respon: {res.text}")
        except Exception as e:
            print(f" -> Gagal terhubung ke backend: {e}")
            print("    Pastikan backend sudah aktif: 'python backend/main.py'")
            break

        if idx < len(scenarios):
            print("Menunggu 4 detik sebelum alert berikutnya...")
            time.sleep(4)

    print("\n[Pengujian Selesai] Silakan periksa dashboard web di browser Anda!")

if __name__ == "__main__":
    main()
