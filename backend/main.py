"""
Backend Server Sistem Deteksi Kelengkapan APD Real-Time
Menggunakan FastAPI + WebSocket + SQLite (100% On-Premise/LAN)
"""

import os
import json
import sqlite3
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# Inisialisasi Path Direktori
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
DB_PATH = BASE_DIR / "backend" / "apd_alerts.db"

# Pastikan folder snapshots ada
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# ----------------- Database SQLite -----------------
def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        violations TEXT NOT NULL,
        snapshot TEXT NOT NULL,
        confidence REAL DEFAULT 0.0,
        status TEXT DEFAULT 'ACTIVE',
        resolved_at TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

init_db()

# ----------------- FastAPI App -----------------
app = FastAPI(
    title="APD Detection Real-Time Alert System",
    description="Sistem monitoring kepatuhan APD on-premise dengan FastAPI & WebSocket",
    version="1.0.0"
)

# CORS Middleware agar dapat diakses dari IP LAN mana pun
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- WebSocket Connection Manager -----------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)

manager = ConnectionManager()

# ----------------- Pydantic Models -----------------
class AlertCreate(BaseModel):
    camera_id: str = Field(default="Kamera 01", description="Nama/Identitas kamera")
    timestamp: Optional[str] = Field(default=None, description="Waktu kejadian (YYYY-MM-DD HH:MM:SS)")
    violations: List[str] = Field(..., description="Daftar APD yang dilanggar, misal ['no_helmet', 'no_vest']")
    snapshot: str = Field(..., description="Nama file snapshot gambar")
    confidence: Optional[float] = Field(default=0.0, description="Tingkat kepercayaan deteksi")

class AlertResponse(BaseModel):
    id: int
    camera_id: str
    timestamp: str
    violations: List[str]
    snapshot: str
    confidence: float
    status: str
    resolved_at: Optional[str]

# ----------------- API Endpoints -----------------

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "active_clients": len(manager.active_connections)
    }

@app.get("/api/stats")
async def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM alerts")
    total = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) as active FROM alerts WHERE status = 'ACTIVE'")
    active = cursor.fetchone()["active"]
    cursor.execute("SELECT COUNT(*) as resolved FROM alerts WHERE status = 'RESOLVED'")
    resolved = cursor.fetchone()["resolved"]
    conn.close()
    return {
        "total_alerts": total,
        "active_alerts": active,
        "resolved_alerts": resolved
    }

@app.get("/api/alerts")
async def list_alerts(limit: int = 50, status: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM alerts WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status.upper(), limit)
        )
    else:
        cursor.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        try:
            violation_list = json.loads(row["violations"])
        except Exception:
            violation_list = [v.strip() for v in row["violations"].split(",") if v.strip()]
        result.append({
            "id": row["id"],
            "camera_id": row["camera_id"],
            "timestamp": row["timestamp"],
            "violations": violation_list,
            "snapshot": row["snapshot"],
            "confidence": row["confidence"],
            "status": row["status"],
            "resolved_at": row["resolved_at"]
        })
    return result

@app.post("/api/alert")
async def create_alert(payload: AlertCreate):
    event_time = payload.timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    violations_json = json.dumps(payload.violations)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO alerts (camera_id, timestamp, violations, snapshot, confidence, status)
        VALUES (?, ?, ?, ?, ?, 'ACTIVE')
    """, (payload.camera_id, event_time, violations_json, payload.snapshot, payload.confidence))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    alert_data = {
        "id": new_id,
        "camera_id": payload.camera_id,
        "timestamp": event_time,
        "violations": payload.violations,
        "snapshot": payload.snapshot,
        "confidence": payload.confidence,
        "status": "ACTIVE",
        "resolved_at": None
    }

    # Broadcast ke semua dashboard web melalui WebSocket
    await manager.broadcast({
        "type": "NEW_ALERT",
        "data": alert_data
    })

    return {"status": "success", "alert": alert_data}

@app.post("/api/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    resolved_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert tidak ditemukan")

    cursor.execute("""
        UPDATE alerts 
        SET status = 'RESOLVED', resolved_at = ?
        WHERE id = ?
    """, (resolved_time, alert_id))
    conn.commit()
    conn.close()

    # Broadcast update status ke semua client
    await manager.broadcast({
        "type": "ALERT_RESOLVED",
        "data": {
            "id": alert_id,
            "status": "RESOLVED",
            "resolved_at": resolved_time
        }
    })

    return {"status": "success", "id": alert_id, "resolved_at": resolved_time}

@app.post("/api/silence")
async def silence_all_alarms():
    """Mengirim sinyal broadcast ke semua dashboard web untuk mematikan suara sirine."""
    await manager.broadcast({
        "type": "SILENCE_ALARM",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    return {"status": "success", "message": "Sinyal senyap disiarkan ke dashboard web"}

# ----------------- WebSocket Endpoint -----------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Kirim status koneksi awal
        await websocket.send_text(json.dumps({
            "type": "CONNECTED",
            "message": "Terhubung ke Server Notifikasi APD"
        }))
        while True:
            # Jaga koneksi tetap hidup (bisa terima ping dari browser)
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "PING":
                    await websocket.send_text(json.dumps({"type": "PONG"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

# ----------------- Static Files & Frontend -----------------
# Sajikan folder snapshots untuk gambar bukti
app.mount("/snapshots", StaticFiles(directory=str(SNAPSHOTS_DIR)), name="snapshots")

# Sajikan file frontend index.html di root ("/")
@app.get("/")
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(status_code=404, content={"message": "Frontend index.html belum dibuat"})
    return FileResponse(index_file)

# Sajikan aset frontend lainnya jika ada (css/js/ico)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_static")

if __name__ == "__main__":
    import uvicorn
    # Menjalankan server pada 0.0.0.0 agar bisa diakses oleh perangkat lain di LAN
    print("[INFO] Menjalankan APD Alert Server di http://0.0.0.0:8000 ...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
