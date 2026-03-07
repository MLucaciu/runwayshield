import os
import sqlite3
import threading


class NotificationsDB:
    """Thread-safe SQLite storage for notifications."""

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
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                source_ip TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'low',
                classification TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                type TEXT NOT NULL DEFAULT 'detection',
                timestamp_start TEXT NOT NULL,
                timestamp_end TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notif_ts "
            "ON notifications (timestamp_start)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notif_status "
            "ON notifications (status)"
        )
        conn.commit()

    def insert(self, notification):
        """Insert a notification dict. Uses INSERT OR IGNORE to deduplicate by id."""
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO notifications "
            "(id, source_ip, camera_id, severity, classification, status, type, "
            "timestamp_start, timestamp_end) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                notification["id"],
                notification["source_ip"],
                notification["camera_id"],
                notification.get("severity", "low"),
                notification["classification"],
                notification.get("status", "active"),
                notification.get("type", "detection"),
                notification["timestamp_start"],
                notification.get("timestamp_end"),
            ),
        )
        conn.commit()

    def update_status(self, notif_id, status, timestamp_end=None):
        conn = self._conn()
        if timestamp_end:
            conn.execute(
                "UPDATE notifications SET status = ?, timestamp_end = ? WHERE id = ?",
                (status, timestamp_end, notif_id),
            )
        else:
            conn.execute(
                "UPDATE notifications SET status = ? WHERE id = ?",
                (status, notif_id),
            )
        conn.commit()

    def query_history(self, limit=100, from_ts=None, to_ts=None):
        conn = self._conn()
        sql = "SELECT * FROM notifications WHERE 1=1"
        params = []
        if from_ts:
            sql += " AND timestamp_start >= ?"
            params.append(from_ts)
        if to_ts:
            sql += " AND timestamp_start <= ?"
            params.append(to_ts)
        sql += " ORDER BY timestamp_start DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def query_live(self):
        conn = self._conn()
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM notifications WHERE status = 'active' "
                "ORDER BY timestamp_start DESC"
            ).fetchall()
        ]
