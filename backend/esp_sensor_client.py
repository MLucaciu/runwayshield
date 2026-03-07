"""MQTT client that subscribes to ESPHome sensor topics and controls actuators.

Listens to the ESP32-S3 device (esp32s3temp) for:
  - AHT20 temperature & humidity
  - BME280 temperature, humidity & pressure
  - Rain sensor (binary)

Can publish commands to:
  - Control LED (switch)
  - Buzzer (switch)
"""

import json
import threading
import uuid

import paho.mqtt.client as mqtt

DEVICE = "esp32s3temp"

SENSOR_TOPICS = {
    f"{DEVICE}/sensor/aht_temperature/state": "aht_temperature",
    f"{DEVICE}/sensor/aht_humidity/state": "aht_humidity",
    f"{DEVICE}/sensor/bme_temperature/state": "bme_temperature",
    f"{DEVICE}/sensor/bme_humidity/state": "bme_humidity",
    f"{DEVICE}/sensor/bme_pressure/state": "bme_pressure",
    f"{DEVICE}/binary_sensor/rain_sensor/state": "rain_sensor",
}

LED_COMMAND_TOPIC = f"{DEVICE}/switch/control_led/command"
BUZZER_COMMAND_TOPIC = f"{DEVICE}/switch/buzzer/command"


class ESPSensorClient:
    """Subscribes to ESPHome sensor MQTT topics and stores latest readings."""

    def __init__(self, broker_host="localhost", broker_port=1883):
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._lock = threading.Lock()
        self._data = {}

        self._client = mqtt.Client(
            client_id=f"runway-shield-esp-{uuid.uuid4().hex[:6]}",
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def start(self):
        try:
            self._client.connect(self._broker_host, self._broker_port, keepalive=60)
            self._client.loop_start()
            print(f"[esp-sensor] connecting to {self._broker_host}:{self._broker_port}")
        except Exception as e:
            print(f"[esp-sensor] failed to connect: {e}")

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            for topic in SENSOR_TOPICS:
                client.subscribe(topic)
            print(f"[esp-sensor] subscribed to {len(SENSOR_TOPICS)} sensor topics")
        else:
            print(f"[esp-sensor] connection failed with code {rc}")

    def _on_message(self, client, userdata, msg):
        key = SENSOR_TOPICS.get(msg.topic)
        if not key:
            return
        try:
            raw = msg.payload.decode().strip()
            if key == "rain_sensor":
                value = raw  # "ON" or "OFF"
            else:
                value = float(raw)
            with self._lock:
                self._data[key] = value
        except Exception as e:
            print(f"[esp-sensor] error parsing {msg.topic}: {e}")

    def get_readings(self):
        """Return a snapshot of the latest sensor readings."""
        with self._lock:
            return dict(self._data)

    def set_led(self, on: bool):
        """Turn the control LED on or off."""
        payload = "ON" if on else "OFF"
        try:
            self._client.publish(LED_COMMAND_TOPIC, payload, qos=1)
            print(f"[esp-sensor] LED -> {payload}")
        except Exception as e:
            print(f"[esp-sensor] LED publish error: {e}")

    def set_buzzer(self, on: bool):
        """Turn the buzzer on or off."""
        payload = "ON" if on else "OFF"
        try:
            self._client.publish(BUZZER_COMMAND_TOPIC, payload, qos=1)
            print(f"[esp-sensor] Buzzer -> {payload}")
        except Exception as e:
            print(f"[esp-sensor] Buzzer publish error: {e}")
