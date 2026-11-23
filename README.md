# Sistem Deteksi Kelengkapan APD Real-Time (100% On-Premise / LAN)

Sistem pemantauan kepatuhan Alat Pelindung Diri (APD / PPE - *Personal Protective Equipment*) meliputi **Helm Keselamatan** (*Safety Helmet*), **Rompi Reflektif** (*Safety Vest*), dan **Sepatu Boot** (*Safety Boots*) berbasis Computer Vision (**Ultralytics YOLOv8 + ByteTrack**) secara *real-time* dari input Webcam maupun RTSP IP Camera, dengan notifikasi otomatis ke dashboard web melalui WebSocket di jaringan lokal (on-premise).

---

## 📁 Struktur Direktori

```text
apd-local-system/
├── audio/
│   └── alarm.mp3          # File sirine untuk speaker lokal komputer
├── backend/
│   ├── main.py            # Server lokal FastAPI + WebSocket + SQLite + static server
│   └── apd_alerts.db      # Database lokal SQLite (otomatis terbuat saat server start)
├── detector/
│   └── detect_apd.py      # Skrip inferensi YOLO, ByteTrack, anti-flicker, cooldown, & auto-alert
├── frontend/
│   ├── alarm.mp3          # File sirine MP3 looping untuk dashboard browser
│   └── index.html         # Dashboard web real-time (HTML5, CSS modern, Vanilla JS)
├── models/
│   └── best.pt            # Bobot model YOLOv8 APD terlatih
├── snapshots/             # Penyimpanan gambar bukti snapshot pelanggaran (JPG)
├── test_alert.py          # Skrip simulasi pengujian notifikasi tanpa kamera
└── requirements.txt       # Daftar dependensi Python
```

---

## ⚡ Fitur Utama

1. **Deteksi 3 APD Utama (Helm, Rompi, Sepatu Boot)**:
   - Verifikasi warna fluorescent untuk rompi K3 (hijau stabilo / oranye).
   - Analisis warna kulit (*skin-tone detection*) pada kaki untuk membedakan kaki telanjang vs sepatu safety boot asli.
   - Filter spasial anatomi tubuh untuk mencegah salah deteksi (misal: jempol dikira helm).

2. **ByteTrack Multi-Object Tracking & EMA Smoothing**:
   - Menjaga pelacakan rompi dan pekerja tetap stabil antar-frame tanpa kedipan (*no flicker*).
   - Pergerakan bounding box mengalir halus (*smooth*) mengikuti gerakan tubuh.

3. **Notifikasi Sirine MP3 Looping**:
   - Begitu pelanggaran terkonfirmasi, sirine berbunyi berulang-ulang (*looping*) di dashboard web dan speaker lokal.
   - Dilengkapi tombol kendali **"Matikan Suara Sirine"** dan auto-stop saat pelanggaran diselesaikan.

4. **Logika Anti-Flicker & Cooldown**:
   - **Anti-Flicker**: Pelanggaran harus bertahan minimal **2 detik** berturut-turut sebelum alert dipicu.
   - **Cooldown 10 Detik**: Mengatur jeda minimal antar alert agar tidak membanjiri sistem.

5. **Backend On-Premise FastAPI + WebSocket**:
   - Berjalan pada host `0.0.0.0:8000` (aksesibel dari semua perangkat di LAN/WiFi).
   - WebSocket (`/ws`) untuk *push notification* instan ke semua dashboard pengawas.
   - Riwayat pelanggaran tersimpan otomatis di database SQLite lokal (`apd_alerts.db`).

---

## 🚀 Panduan Instalasi & Menjalankan Sistem

### 1. Prasyarat
- Python versi 3.9 ke atas
- Webcam atau IP Camera RTSP yang terhubung ke jaringan

### 2. Instalasi Dependensi
Buka terminal/PowerShell di direktori proyek `apd-local-system`:

```bash
pip install -r requirements.txt
```

---

### 3. Urutan Menjalankan Sistem

#### Langkah 1: Jalankan Backend Server (Terminal 1)
Masuk ke folder backend dan jalankan FastAPI:

```bash
cd backend
python main.py
```
*Server akan berjalan di `http://0.0.0.0:8000`.*

#### Langkah 2: Buka Dashboard di Browser
- Akses melalui PC server: [http://localhost:8000](http://localhost:8000)
- Akses dari perangkat lain di LAN: `http://<IP_KOMPUTER_SERVER>:8000` (contoh: `http://192.168.1.50:8000`)
- **Catatan Audio**: Klik di sembarang area halaman atau klik tombol **"🔊 Audio Alarm: Aktif"** satu kali untuk mengaktifkan izin suara di peramban Anda.

#### Langkah 3: Jalankan Detektor Kamera (Terminal 2)
Buka terminal baru di direktori proyek:

- **Menggunakan Webcam bawaan (GUI Aktif):**
  ```bash
  python detector/detect_apd.py --source 0
  ```

- **Menggunakan IP Camera RTSP:**
  ```bash
  python detector/detect_apd.py --source "rtsp://admin:password123@192.168.1.100:554/stream1" --camera-name "Kamera Gerbang Masuk"
  ```

- **Mode Headless (Server tanpa Monitor / Background Service):**
  ```bash
  python detector/detect_apd.py --source 0 --headless
  ```

---

## 🧪 Menguji Notifikasi Tanpa Kamera (Opsional)

Jika Anda ingin menguji respon dashboard, bunyi sirine, dan WebSocket tanpa mengaktifkan kamera fisik:

1. Pastikan server backend sedang menyala (`python backend/main.py`).
2. Buka dashboard di browser (`http://localhost:8000`).
3. Di terminal terpisah, jalankan skrip simulasi:
   ```bash
   python test_alert.py
   ```
4. Dashboard web akan langsung membunyikan sirine darurat, menampilkan banner merah peringatan, dan menambahkan kartu insiden lengkap dengan foto snapshot.

---

## ⚙️ Menambahkan Model Kustom (.pt)

Jika Anda memiliki model bobot YOLO terlatih khusus APD:
1. Simpan file model tersebut dengan nama `best.pt` di folder `models/`:
   ```text
   apd-local-system/models/best.pt
   ```
2. Detektor otomatis akan mendeteksi dan memuat file tersebut saat dijalankan.
3. Anda juga dapat menentukan file model kustom via flag CLI:
   ```bash
   python detector/detect_apd.py --model path/to/your_model.pt
   ```
