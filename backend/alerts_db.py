import json
import os
import sqlite3
import threading
from datetime import datetime, timezone


class AlertsDB:
    """Thread-safe SQLite storage for zone-based alerts and their audit logs."""

    def __init__(self, db_path):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def clear_all(self):
        """Finalize stale alerts from a previous run.

        Active (unacknowledged) alerts become 'closed'.
        Acknowledged alerts become 'resolved' (operator handled them).
        """
        conn = self._conn()
        now = self._now_iso()
        conn.execute(
            "UPDATE alerts SET status = 'resolved', closed_at = ?, updated_at = ? "
            "WHERE status = 'acknowledged'",
            (now, now),
        )
        conn.execute(
            "UPDATE alerts SET status = 'closed', closed_at = ?, updated_at = ? "
            "WHERE status = 'active'",
            (now, now),
        )
        conn.commit()

    def _init_schema(self):
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id TEXT NOT NULL,
                zone_id TEXT NOT NULL,
                zone_name TEXT,
                object_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'active',
                gps_lat REAL,
                gps_lng REAL,
                acknowledged_by TEXT,
                acknowledged_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_status "
            "ON alerts (status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_lookup "
            "ON alerts (camera_id, zone_id, object_type, status)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL REFERENCES alerts(id),
                action TEXT NOT NULL,
                details TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alog_alert "
            "ON alert_logs (alert_id)"
        )
        conn.commit()

    def _now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    def _log(self, conn, alert_id, action, details=None):
        conn.execute(
            "INSERT INTO alert_logs (alert_id, action, details, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (alert_id, action, json.dumps(details) if details else None, self._now_iso()),
        )

    # ------------------------------------------------------------------
    # Core upsert: one active alert per (camera_id, zone_id, object_type)
    # ------------------------------------------------------------------

    def upsert(self, camera_id, zone_id, object_type, severity, gps_lat, gps_lng,
               zone_name=None):
        """Create or update an alert. Returns (alert_dict, is_new)."""
        conn = self._conn()
        now = self._now_iso()

        row = conn.execute(
            "SELECT * FROM alerts "
            "WHERE camera_id = ? AND zone_id = ? AND object_type = ? "
            "AND status IN ('active', 'acknowledged') "
            "LIMIT 1",
            (camera_id, zone_id, object_type),
        ).fetchone()

        if row:
            conn.execute(
                "UPDATE alerts SET updated_at = ?, gps_lat = ?, gps_lng = ? "
                "WHERE id = ?",
                (now, gps_lat, gps_lng, row["id"]),
            )
            conn.commit()
            return self._get(conn, row["id"]), False

        cur = conn.execute(
            "INSERT INTO alerts "
            "(camera_id, zone_id, zone_name, object_type, severity, status, "
            "gps_lat, gps_lng, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)",
            (camera_id, zone_id, zone_name, object_type, severity,
             gps_lat, gps_lng, now, now),
        )
        alert_id = cur.lastrowid
        self._log(conn, alert_id, "created", {
            "severity": severity,
            "gps": [gps_lat, gps_lng],
        })
        conn.commit()
        return self._get(conn, alert_id), True

    def close_alert(self, alert_id):
        """Close an alert (object left the zone).

        Acknowledged alerts transition to 'resolved' to preserve the
        acknowledgment; unacknowledged active alerts become 'closed'.
        """
        conn = self._conn()
        now = self._now_iso()
        row = conn.execute(
            "SELECT status FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()
        if not row or row["status"] not in ("active", "acknowledged"):
            return
        new_status = "resolved" if row["status"] == "acknowledged" else "closed"
        conn.execute(
            "UPDATE alerts SET status = ?, closed_at = ?, updated_at = ? "
            "WHERE id = ?",
            (new_status, now, now, alert_id),
        )
        self._log(conn, alert_id, new_status)
        conn.commit()

    def acknowledge(self, alert_id, username):
        """Acknowledge an alert. Returns the updated alert or None."""
        conn = self._conn()
        now = self._now_iso()
        changed = conn.execute(
            "UPDATE alerts SET status = 'acknowledged', "
            "acknowledged_by = ?, acknowledged_at = ?, updated_at = ? "
            "WHERE id = ? AND status = 'active'",
            (username, now, now, alert_id),
        ).rowcount
        if changed:
            self._log(conn, alert_id, "acknowledged", {"by": username})
            conn.commit()
            return self._get(conn, alert_id)
        conn.commit()
        return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def find_open_alerts(self, camera_id):
        """All active/acknowledged alerts for a camera."""
        conn = self._conn()
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM alerts "
                "WHERE camera_id = ? AND status IN ('active', 'acknowledged') "
                "ORDER BY created_at DESC",
                (camera_id,),
            ).fetchall()
        ]

    def query_live(self):
        conn = self._conn()
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM alerts "
                "WHERE status IN ('active', 'acknowledged') "
                "ORDER BY "
                "  CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
                "  created_at DESC"
            ).fetchall()
        ]

    def query_history(self, limit=100, camera_id=None, zone_id=None,
                      object_type=None, severity=None, from_ts=None, to_ts=None):
        conn = self._conn()
        sql = "SELECT * FROM alerts WHERE 1=1"
        params = []
        if camera_id:
            sql += " AND camera_id = ?"
            params.append(camera_id)
        if zone_id:
            sql += " AND zone_id = ?"
            params.append(zone_id)
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if severity:
            sql += " AND severity = ?"
            params.append(severity)
        if from_ts:
            sql += " AND created_at >= ?"
            params.append(from_ts)
        if to_ts:
            sql += " AND created_at <= ?"
            params.append(to_ts)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def query_reports(self, limit=500, camera_id=None, zone_id=None,
                      object_type=None, severity=None, from_ts=None, to_ts=None):
        """Return acknowledged/closed alerts for the reports page."""
        conn = self._conn()
        sql = "SELECT * FROM alerts WHERE status IN ('acknowledged', 'closed', 'resolved')"
        params = []
        if camera_id:
            sql += " AND camera_id = ?"
            params.append(camera_id)
        if zone_id:
            sql += " AND zone_id = ?"
            params.append(zone_id)
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if severity:
            sql += " AND severity = ?"
            params.append(severity)
        if from_ts:
            sql += " AND created_at >= ?"
            params.append(from_ts)
        if to_ts:
            sql += " AND created_at <= ?"
            params.append(to_ts)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def delete_by_ids(self, ids):
        """Delete alerts and their logs by a list of IDs. Returns count deleted."""
        if not ids:
            return 0
        conn = self._conn()
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM alert_logs WHERE alert_id IN ({placeholders})", ids)
        cur = conn.execute(f"DELETE FROM alerts WHERE id IN ({placeholders})", ids)
        conn.commit()
        return cur.rowcount

    def delete_all_reports(self):
        """Delete all non-active alerts (reports). Returns count deleted."""
        conn = self._conn()
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM alerts WHERE status NOT IN ('active', 'acknowledged')"
        ).fetchall()]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM alert_logs WHERE alert_id IN ({placeholders})", ids)
        cur = conn.execute(f"DELETE FROM alerts WHERE id IN ({placeholders})", ids)
        conn.commit()
        return cur.rowcount

    def get_by_id(self, alert_id):
        conn = self._conn()
        return self._get(conn, alert_id)

    def get_logs(self, alert_id):
        conn = self._conn()
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM alert_logs WHERE alert_id = ? ORDER BY timestamp ASC",
                (alert_id,),
            ).fetchall()
        ]

    def _get(self, conn, alert_id):
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        return dict(row) if row else None
