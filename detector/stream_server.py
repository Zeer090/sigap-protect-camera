"""
Modul Streaming MJPEG HTTP Real-Time untuk CCTV / Deteksi APD
=============================================================
Menyediakan server streaming video HTTP berbasis MJPEG (Motion JPEG).
Dapat diakses melalui browser web, VLC, OpenCV, atau dashboard web
dari perangkat mana pun di jaringan Wi-Fi/LAN yang sama.
"""

import sys
import time
import socket
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import cv2


def get_local_ip():
    """Mendapatkan alamat IPv4 lokal yang terhubung ke jaringan Wi-Fi / LAN."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Menghubungkan ke alamat dummy untuk mendeteksi antarmuka jaringan yang aktif
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class StreamBuffer:
    """Buffer thread-safe untuk menyimpan dan mendistribusikan frame JPEG ke client."""

    def __init__(self):
        self.frame_bytes = None
        self.condition = threading.Condition()
        self.client_count = 0
        self._lock = threading.Lock()

    def update(self, frame_bgr, quality=80):
        """Encode frame OpenCV (BGR) ke JPEG dan broadcast ke semua client penonton."""
        if frame_bgr is None or frame_bgr.size == 0:
            return

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        success, encoded_img = cv2.imencode(".jpg", frame_bgr, encode_param)
        if not success:
            return

        with self.condition:
            self.frame_bytes = encoded_img.tobytes()
            self.condition.notify_all()

    def get_frame(self, timeout=1.0):
        """Mengambil frame JPEG terbaru. Menunggu frame baru jika belum ada."""
        with self.condition:
            if self.frame_bytes is None:
                self.condition.wait(timeout=timeout)
            return self.frame_bytes

    def add_client(self):
        with self._lock:
            self.client_count += 1

    def remove_client(self):
        with self._lock:
            self.client_count = max(0, self.client_count - 1)


class MJPEGHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler untuk melayani video feed MJPEG dan antarmuka web sederhana."""

    server_buffer: StreamBuffer = None
    camera_name: str = "Kamera 01 - Area Kerja"

    # Matikan log default stdout http.server agar tidak memenuhi terminal YOLO
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.serve_index()
        elif self.path in ("/video_feed", "/stream", "/live"):
            self.serve_mjpeg()
        elif self.path in ("/snapshot", "/current.jpg"):
            self.serve_snapshot()
        else:
            self.send_error(404, "Halaman tidak ditemukan. Gunakan / atau /video_feed")

    def serve_index(self):
        """Menyajikan halaman HTML preview stream untuk dibuka langsung di browser."""
        html = f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SIGAP Protect - Live CCTV APD</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            background: #0f172a;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .header {{
            text-align: center;
            margin-bottom: 20px;
        }}
        h1 {{
            color: #22c55e;
            margin: 0 0 8px 0;
            font-size: 26px;
        }}
        .badge {{
            display: inline-block;
            background: rgba(34, 197, 94, 0.2);
            border: 1px solid #22c55e;
            color: #22c55e;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
        }}
        .video-box {{
            background: #000;
            border: 2px solid #334155;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            max-width: 900px;
            width: 100%;
        }}
        img {{
            display: block;
            width: 100%;
            height: auto;
        }}
        .info {{
            margin-top: 16px;
            font-size: 14px;
            color: #94a3b8;
            text-align: center;
        }}
        code {{
            background: #1e293b;
            color: #38bdf8;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎥 SIGAP Protect - Live CCTV</h1>
        <div class="badge">● LIVE STREAMING</div>
        <p style="margin: 8px 0 0 0; color: #cbd5e1;">{self.camera_name}</p>
    </div>
    <div class="video-box">
        <img src="/video_feed" alt="Live CCTV Stream APD">
    </div>
    <div class="info">
        URL Streaming MJPEG Langsung: <code>http://{self.headers.get('Host', 'IP_SERVER')}/video_feed</code>
    </div>
</body>
</html>"""
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-cache, private")
        self.end_headers()
        self.wfile.write(encoded)

    def serve_snapshot(self):
        """Menyajikan satu frame JPEG tunggal."""
        if not self.server_buffer:
            self.send_error(503, "Buffer belum siap")
            return
        frame = self.server_buffer.get_frame(timeout=2.0)
        if frame is None:
            self.send_error(503, "Tidak ada frame")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(frame)

    def serve_mjpeg(self):
        """Streaming kontinyu MJPEG dengan boundary frame multipart."""
        if not self.server_buffer:
            self.send_error(503, "Stream buffer belum siap")
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        self.server_buffer.add_client()
        try:
            while True:
                frame = self.server_buffer.get_frame(timeout=1.0)
                if frame is None:
                    continue

                header = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                )
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                # Batasi sedikit interval pengiriman per frame untuk stabilitas bandwidth
                time.sleep(0.01)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:
            pass
        finally:
            self.server_buffer.remove_client()


class LiveStreamServer:
    """Manajer server streaming MJPEG HTTP."""

    def __init__(self, host="0.0.0.0", port=5000, camera_name="Kamera 01 - Area Kerja"):
        self.host = host
        self.port = port
        self.camera_name = camera_name
        self.buffer = StreamBuffer()
        self.server = None
        self.thread = None
        self.is_running = False

    def start(self):
        """Memulai HTTP streaming server di thread terpisah (daemon)."""
        if self.is_running:
            return True

        # Inisialisasi handler dengan referensi buffer bersama
        class CustomHandler(MJPEGHandler):
            server_buffer = self.buffer
            camera_name = self.camera_name

        try:
            # Menggunakan ThreadingHTTPServer agar dapat melayani banyak penonton secara paralel
            self.server = ThreadingHTTPServer((self.host, self.port), CustomHandler)
            self.server.daemon_threads = True
            self.is_running = True

            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()

            local_ip = get_local_ip()
            print(f"[STREAMING] Server CCTV Live aktif di port {self.port}!")
            print(f"            - Akses Lokal : http://127.0.0.1:{self.port}/video_feed")
            print(f"            - Akses Wi-Fi : http://{local_ip}:{self.port}/video_feed")
            print(f"            - Web Viewer  : http://{local_ip}:{self.port}/\n")
            return True
        except OSError as e:
            print(f"[STREAMING ERROR] Gagal memulai server di port {self.port}: {e}")
            print("                  Pastikan port tidak sedang digunakan oleh aplikasi lain.")
            self.is_running = False
            return False

    def update_frame(self, frame_bgr, quality=80):
        """Kirim frame hasil pemrosesan YOLO (dengan bounding box) ke streaming buffer."""
        if self.is_running and frame_bgr is not None:
            self.buffer.update(frame_bgr, quality=quality)

    def stop(self):
        """Menghentikan HTTP streaming server secara aman."""
        if self.is_running and self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
            self.is_running = False
            print("[STREAMING] Server live CCTV dihentikan.")
