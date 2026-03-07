#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

PORT="${MQTT_PORT:-1883}"
CONTAINER_NAME="runway-shield-mqtt"

# Stop existing container if running
if docker inspect "$CONTAINER_NAME" &>/dev/null; then
    echo "Stopping existing $CONTAINER_NAME container..."
    docker rm -f "$CONTAINER_NAME" >/dev/null
fi

echo "Starting Mosquitto MQTT broker on port $PORT (accessible on LAN)..."
exec docker run -d --rm \
    --name "$CONTAINER_NAME" \
    -p "$PORT:$PORT" \
    -v "$(pwd)/mosquitto.conf:/mosquitto/config/mosquitto.conf" \
    eclipse-mosquitto
