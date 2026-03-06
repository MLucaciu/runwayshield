import cv2
import threading
import time
import os
from collections import deque
from datetime import datetime, timezone


class CameraStream:
    """Captures from an IP camera, maintains a ring buffer, and writes MP4 segments to disk."""

    def __init__(self, camera_id, url, video_dir="videos",
                 buffer_seconds=30, segment_seconds=30, fps=15):
        self.camera_id = camera_id
        self.url = url
        self.fps = fps
        self.buffer_seconds = buffer_seconds
        self.segment_seconds = segment_seconds

        # Ring buffer: (datetime, jpeg_bytes)
        self.ring_buffer = deque(maxlen=buffer_seconds * fps)
        self._buffer_lock = threading.Lock()

        # Latest frame for live MJPEG stream
        self._latest_jpeg = None
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()

        # Video writer state
        self._writer = None
        self._segment_start = None
        self._segment_path = None
        self._frame_size = None

        # Directories
        self._raw_dir = os.path.join(video_dir, camera_id, "raw")
        os.makedirs(self._raw_dir, exist_ok=True)

        # Capture
        self._cap = None
        self._running = False
        self._thread = None

    def start(self, retries=3, retry_delay=2):
        source = int(self.url) if self.url.isdigit() else self.url
        for attempt in range(retries):
            self._cap = cv2.VideoCapture(source)
            if self._cap.isOpened():
                break
            self._cap.release()
            if attempt < retries - 1:
                print(f"[camera] {self.camera_id} open failed, retrying in {retry_delay}s… ({attempt + 1}/{retries})")
                time.sleep(retry_delay)
        else:
            raise ConnectionError(f"Cannot open camera {self.camera_id} at {self.url}")
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._finalize_segment()
        if self._cap:
            self._cap.release()

    def _capture_loop(self):
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            now = datetime.now(timezone.utc)

            # Encode to JPEG
            _, jpeg = cv2.imencode(".jpg", frame)
            jpeg_bytes = jpeg.tobytes()

            # Update latest frame
            with self._frame_lock:
                self._latest_jpeg = jpeg_bytes
            self._frame_event.set()

            # Push to ring buffer
            with self._buffer_lock:
                self.ring_buffer.append((now, jpeg_bytes))

            # Write raw frame to disk segment
            self._write_frame(frame, now)

    # ------------------------------------------------------------------
    # Live stream access
    # ------------------------------------------------------------------

    def get_latest_jpeg(self):
        with self._frame_lock:
            return self._latest_jpeg

    def wait_for_frame(self, timeout=1.0):
        """Block until a new frame arrives (or timeout). Returns jpeg bytes or None."""
        self._frame_event.wait(timeout=timeout)
        self._frame_event.clear()
        return self.get_latest_jpeg()

    # ------------------------------------------------------------------
    # Ring buffer access
    # ------------------------------------------------------------------

    def get_buffer_frames(self, from_ts, to_ts):
        """Return [(datetime, jpeg_bytes), ...] from the ring buffer within the range."""
        with self._buffer_lock:
            return [
                (ts, jpeg) for ts, jpeg in self.ring_buffer
                if from_ts <= ts <= to_ts
            ]

    def buffer_start_time(self):
        """Earliest timestamp available in the ring buffer, or None."""
        with self._buffer_lock:
            if self.ring_buffer:
                return self.ring_buffer[0][0]
        return None

    # ------------------------------------------------------------------
    # Disk segment access
    # ------------------------------------------------------------------

    def list_segments(self):
        """Return sorted list of segment filenames in the raw directory."""
        if not os.path.isdir(self._raw_dir):
            return []
        files = [f for f in os.listdir(self._raw_dir) if f.endswith(".mp4")]
        files.sort()
        return files

    def segment_path(self, filename):
        return os.path.join(self._raw_dir, filename)

    # ------------------------------------------------------------------
    # Video writer internals
    # ------------------------------------------------------------------

    def _write_frame(self, frame, timestamp):
        if self._writer is None or self._should_rotate(timestamp):
            self._finalize_segment()
            self._start_segment(frame, timestamp)
        self._writer.write(frame)

    def _should_rotate(self, timestamp):
        if self._segment_start is None:
            return True
        elapsed = (timestamp - self._segment_start).total_seconds()
        return elapsed >= self.segment_seconds

    def _start_segment(self, frame, timestamp):
        self._segment_start = timestamp
        filename = timestamp.strftime("%Y%m%dT%H%M%SZ") + ".mp4"
        self._segment_path = os.path.join(self._raw_dir, filename)

        h, w = frame.shape[:2]
        self._frame_size = (w, h)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(self._segment_path, fourcc, self.fps, (w, h))

    def _finalize_segment(self):
        if self._writer is not None:
            self._writer.release()
            self._writer = None
            self._segment_start = None
            self._segment_path = None
