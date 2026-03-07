import json
import socket
import threading
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt


TOPIC = "runway-shield/notifications"


def _get_local_ip():
    """Best-effort local IP detection."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class MQTTNotificationClient:
    """Publishes and subscribes to notification messages over MQTT."""

    def __init__(self, notifications_db, broker_host="localhost", broker_port=1883,
                 source_ip=None):
        self._db = notifications_db
        self._broker_host = broker_host
        self._broker_port = broker_port
        self.source_ip = source_ip or _get_local_ip()

        self._client = mqtt.Client(
            client_id=f"runway-shield-{self.source_ip}-{uuid.uuid4().hex[:6]}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._connected = False

    def start(self):
        """Connect to broker and start the network loop in a background thread."""
        try:
            self._client.connect(self._broker_host, self._broker_port, keepalive=60)
            self._client.loop_start()
            print(f"[mqtt] connecting to {self._broker_host}:{self._broker_port} "
                  f"(source_ip={self.source_ip})")
        except Exception as e:
            print(f"[mqtt] failed to connect to broker: {e}")

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            client.subscribe(TOPIC)
            print(f"[mqtt] connected, subscribed to {TOPIC}")
        else:
            print(f"[mqtt] connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            notification = json.loads(msg.payload.decode())
            self._db.insert(notification)
        except Exception as e:
            print(f"[mqtt] error processing message: {e}")

    def publish_notification(self, camera_id, classification, severity="low",
                             notif_type="detection", status="active"):
        """Create a notification, insert locally, and broadcast via MQTT.

        Returns the notification dict.
        """
        notification = {
            "id": uuid.uuid4().hex,
            "source_ip": self.source_ip,
            "camera_id": camera_id,
            "severity": severity,
            "classification": classification,
            "status": status,
            "type": notif_type,
            "timestamp_start": datetime.now(timezone.utc).isoformat(),
            "timestamp_end": None,
        }

        # Insert locally first
        self._db.insert(notification)

        # Broadcast
        try:
            self._client.publish(TOPIC, json.dumps(notification), qos=1)
        except Exception as e:
            print(f"[mqtt] publish error: {e}")

        return notification

    def resolve_notification(self, notif_id):
        """Mark a notification as resolved locally and broadcast the update."""
        now = datetime.now(timezone.utc).isoformat()
        self._db.update_status(notif_id, "resolved", timestamp_end=now)

        try:
            self._client.publish(TOPIC, json.dumps({
                "id": notif_id,
                "source_ip": self.source_ip,
                "camera_id": "",
                "severity": "low",
                "classification": "",
                "status": "resolved",
                "type": "status_update",
                "timestamp_start": now,
                "timestamp_end": now,
            }), qos=1)
        except Exception as e:
            print(f"[mqtt] publish error: {e}")
