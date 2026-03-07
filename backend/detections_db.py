import os
import sqlite3
import threading


class DetectionsDB:
    """Thread-safe SQLite storage for YOLO detections."""

    def __init__(self, db_path):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_schema(self):
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                track_id INTEGER,
                class_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                x2 REAL NOT NULL,
                y2 REAL NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_det_cam_ts "
            "ON detections (camera_id, timestamp)"
        )
        conn.commit()

    def insert(self, camera_id, timestamp, detections):
        conn = self._conn()
        rows = [
            (camera_id, timestamp.isoformat(), d["track_id"], d["class_name"],
             d["confidence"], d["bbox"][0], d["bbox"][1], d["bbox"][2], d["bbox"][3])
            for d in detections
        ]
        conn.executemany(
            "INSERT INTO detections "
            "(camera_id, timestamp, track_id, class_name, confidence, "
            "x1, y1, x2, y2) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

    def query(self, camera_id, limit=100, from_ts=None, to_ts=None):
        conn = self._conn()
        sql = "SELECT * FROM detections WHERE camera_id = ?"
        params = [camera_id]
        if from_ts:
            sql += " AND timestamp >= ?"
            params.append(from_ts)
        if to_ts:
            sql += " AND timestamp <= ?"
            params.append(to_ts)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
