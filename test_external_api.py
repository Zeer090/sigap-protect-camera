"""
Skrip Pengujian Koneksi ke API Eksternal SIGAP Protect
======================================================
Gunakan script ini untuk memastikan data deteksi berhasil dikirim
ke server PHP di http://172.26.224.1/sigap-protect/api/ingest_deteksi.php

Jalankan: python test_external_api.py
"""

import json
import requests
from datetime import datetime

EXTERNAL_API_URL = "http://10.218.31.240/sigap-protect/api/ingest_deteksi.php"
TIMEOUT = 5.0

LABEL_MAP = {
    "no_helmet":  "Tidak Pakai Helm",
    "no_vest":    "Tidak Pakai Rompi",
    "no_boots":   "Tidak Pakai Sepatu Boot",
}

SKENARIO = [
    {
        "nama": "Hanya Rompi (tanpa helm & sepatu boot)",
        "camera_id": "Kamera 01 - Area Kerja",
        "violations": ["no_helmet", "no_boots"],
        "confidence": 0.91,
        "snapshot": "apd_violation_test_01.jpg",
    },
    {
        "nama": "Hanya Helm (tanpa rompi)",
        "camera_id": "Kamera 01 - Area Kerja",
        "violations": ["no_vest"],
        "confidence": 0.87,
        "snapshot": "apd_violation_test_02.jpg",
    },
    {
        "nama": "Tidak pakai apa-apa (3 pelanggaran)",
        "camera_id": "Kamera 01 - Area Kerja",
        "violations": ["no_helmet", "no_vest", "no_boots"],
        "confidence": 0.94,
        "snapshot": "apd_violation_test_03.jpg",
    },
    {
        "nama": "Lengkap APD (simulasi no-violation — tidak ada violations)",
        "camera_id": "Kamera 01 - Area Kerja",
        "violations": [],
        "confidence": 0.0,
        "snapshot": "",
    },
]


def test_get():
    """Cek apakah server bisa dijangkau dengan GET request sederhana."""
    print("\n[1] Mengecek koneksi ke server PHP (GET)...")
    try:
        r = requests.get(EXTERNAL_API_URL, timeout=TIMEOUT)
        print(f"    ✅ Server merespons! Status: {r.status_code}")
        print(f"    Response: {r.text[:300]}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"    ❌ Gagal terhubung — server {EXTERNAL_API_URL} tidak bisa dijangkau.")
        print("    Pastikan:")
        print("      - Laptop/PC kamu terhubung ke jaringan yang sama dengan 172.26.224.1")
        print("      - Server PHP SIGAP sedang aktif")
        return False
    except requests.exceptions.Timeout:
        print(f"    ❌ Timeout — server tidak merespons dalam {TIMEOUT} detik.")
        return False


def test_post(skenario: dict):
    """Kirim data simulasi pelanggaran APD ke PHP API."""
    violations = skenario["violations"]
    if not violations:
        print(f"\n  [SKIP] Skenario '{skenario['nama']}' tidak memiliki violations, dilewati.")
        return

    # Tentukan status per APD: 1 = pakai (aman), 0 = tidak pakai (pelanggaran)
    apd_helm   = 0 if "no_helmet" in violations else 1
    apd_rompi  = 0 if "no_vest"   in violations else 1
    apd_sepatu = 0 if "no_boots"  in violations else 1

    # Mapping missing untuk format standar PHP SIGAP
    missing_items = []
    if "no_helmet" in violations:
        missing_items.append("helm")
    if "no_vest" in violations:
        missing_items.append("rompi")
    if "no_boots" in violations:
        missing_items.append("sepatu")

    labels = [LABEL_MAP.get(v, v) for v in violations]
    label_text = " & ".join(labels) if labels else "Lengkap"

    payload = {
        "camera":              skenario["camera_id"],
        "camera_nomor":        skenario["camera_id"],
        "timestamp":           datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "violations":          json.dumps(violations),
        "missing":             missing_items,
        "label":               label_text,
        "apd_helm":            apd_helm,
        "apd_rompi":           apd_rompi,
        "apd_sepatu":          apd_sepatu,
        "confidence":          round(skenario["confidence"], 2),
        "snapshot":            skenario["snapshot"],
        "status":              "PELANGGARAN",
        "jumlah_pelanggaran":  len(violations),
    }

    labels = [LABEL_MAP.get(v, v) for v in violations]
    print(f"\n  Mengirim: {labels}")
    print(f"  Payload : {json.dumps(payload, ensure_ascii=False)}")

    try:
        r = requests.post(EXTERNAL_API_URL, json=payload, timeout=TIMEOUT)
        print(f"  Status  : HTTP {r.status_code}")
        print(f"  Response: {r.text[:300]}")
        if r.status_code in (200, 201):
            print("  ✅ Berhasil dikirim!")
        else:
            print("  ⚠️  Server merespons tapi status bukan 200 — cek PHP API kamu.")
    except requests.exceptions.ConnectionError:
        print("  ❌ Tidak bisa terhubung ke server.")
    except requests.exceptions.Timeout:
        print(f"  ❌ Timeout setelah {TIMEOUT} detik.")
    except Exception as e:
        print(f"  ❌ Error: {e}")


def main():
    print("=" * 60)
    print("   TEST KONEKSI KE API EKSTERNAL SIGAP PROTECT")
    print("=" * 60)
    print(f"Target URL: {EXTERNAL_API_URL}\n")

    # 1. Test GET dulu untuk cek koneksi
    server_ok = test_get()

    # 2. Kirim semua skenario POST (tetap coba meskipun GET gagal)
    print("\n[2] Mengirim data POST simulasi deteksi APD...")
    for idx, sc in enumerate(SKENARIO, 1):
        print(f"\n--- Skenario {idx}: {sc['nama']} ---")
        test_post(sc)

    print("\n" + "=" * 60)
    if server_ok:
        print("Selesai! Cek database / dashboard SIGAP Protect kamu.")
        print("Data yang masuk harus terlihat di tabel deteksi/cctvAI.")
    else:
        print("Server tidak terjangkau dari PC ini sekarang.")
        print("Jalankan script ini saat laptop terhubung ke jaringan")
        print(f"yang sama dengan server 172.26.224.1")
    print("=" * 60)


if __name__ == "__main__":
    main()
