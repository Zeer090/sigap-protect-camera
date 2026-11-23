# Sistem Deteksi Kelengkapan APD Real-Time (100% On-Premise / LAN)

Sistem pemantauan kepatuhan Alat Pelindung Diri (APD / PPE - *Personal Protective Equipment*) seperti **Helm Keselamatan** (*Safety Helmet*) dan **Rompi Reflektif** (*Safety Vest*) berbasis Computer Vision (**Ultralytics YOLO**) secara *real-time* dari input Webcam maupun RTSP IP Camera, dengan notifikasi otomatis ke dashboard web melalui WebSocket di jaringan lokal (on-premise).

---

## 📁 Struktur Direktori

```text
apd-local-system/
├── models/              # Tempat menyimpan bobot model YOLO (.pt), misal: best.pt
├── snapshots/           # Penyimpanan gambar bukti pelanggaran APD (JPG)
├── backend/
│   ├── main.py          # Server lokal FastAPI + WebSocket + SQLite + static server
│   └── apd_alerts.db    # Database lokal SQLite (otomatis terbuat saat server start)
├── frontend/
│   └── index.html       # Dashboard web real-time (HTML5, modern CSS, Vanilla JS, Web Audio API)
├── detector/
│   └── detect_apd.py    # Skrip inferensi YOLO, anti-flicker, cooldown, & auto-alert
├── test_alert.py        # Skrip simulasi pengujian notifikasi tanpa kamera
└── requirements.txt     # Daftar dependensi Python
```

---

## ⚡ Fitur Utama

1. **Inferensi YOLO Real-Time**:
   - Mendukung input kamera webcam (indeks `0`) atau stream IP Camera melalui protokol `rtsp://username:password@ip:port/stream`.
   - Menggunakan bobot model `models/best.pt` (jika belum ada, otomatis menggunakan fallback `yolov8n.pt` untuk uji coba awal).

2. **Logika Anti-Flicker & Cooldown**:
   - **Anti-Flicker**: Pelanggaran harus terdeteksi secara konsisten minimal **2 detik** berturut-turut sebelum memicu alert (mencegah *false alarm* akibat bayangan atau objek bergerak sekilas).
   - **Cooldown 10 Detik**: Mengatur jeda minimal antar notifikasi agar tidak membanjiri (*spam*) sistem.

3. **Backend On-Premise FastAPI**:
   - Berjalan pada host `0.0.0.0:8000` sehingga dapat diakses oleh semua perangkat (PC K3/HSE, laptop pengawas, tablet) dalam satu jaringan Wi-Fi/LAN yang sama.
   - Menggunakan WebSocket (`/ws`) untuk *push notification* instan ke semua dashboard yang sedang terbuka.
   - Riwayat pelanggaran tersimpan otomatis di database SQLite lokal (`apd_alerts.db`).

4. **Dashboard Web Real-Time**:
   - Desain responsif bertema *Industrial Safety* tanpa dependensi *build tools* rumit.
   - **Audio Alarm Mandiri**: Menggunakan **Web Audio API** bawaan browser untuk menghasilkan sirine darurat frekuensi ganda tanpa butuh file MP3 eksternal.
   - Menampilkan status koneksi WebSocket (auto-reconnect jika koneksi LAN terputus).
   - Galeri kartu insiden dengan foto bukti beranotasi bounding box, waktu kejadian, tingkat akurasi (*confidence*), serta tombol interaktif **"Tandai Selesai"**.
   - Fitur klik pada foto untuk zoom gambar bukti pelanggaran.

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
