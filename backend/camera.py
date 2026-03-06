import cv2
import threading
import time
import os
from collections import deque
from datetime import datetime, timezone


def _measure_fps(cap, sample_frames=30):
    """Measure actual camera fps by timing a burst of frames."""
    start = time.monotonic()
    count = 0
    for _ in range(sample_frames):
        ret, _ = cap.read()
        if ret:
            count += 1
    elapsed = time.monotonic() - start
    if elapsed > 0 and count > 0:
        return round(count / elapsed)
    return 30  # fallback


def _next_segment_boundary(now, segment_seconds=30):
    """Return the next wall-clock boundary aligned to :00 or :30."""
    s = now.second
    # Which slot are we in? 0-29 → boundary at :30, 30-59 → boundary at :00 next minute
    slot_start_sec = (s // segment_seconds) * segment_seconds
    boundary_sec = slot_start_sec + segment_seconds
    boundary = now.replace(microsecond=0)
    if boundary_sec >= 60:
        boundary = boundary.replace(second=0)
        # advance one minute
        boundary = boundary.replace(minute=boundary.minute + 1) if boundary.minute < 59 \
            else boundary.replace(minute=0, hour=boundary.hour + 1)
    else:
        boundary = boundary.replace(second=boundary_sec)
    return boundary


def _segment_boundary_for(now, segment_seconds=30):
    """Return the wall-clock boundary (start of slot) for a given timestamp."""
    slot_start_sec = (now.second // segment_seconds) * segment_seconds
    return now.replace(second=slot_start_sec, microsecond=0)


class CameraStream:
    """Captures from an IP camera, maintains a ring buffer, and writes MP4 segments to disk."""

    def __init__(self, camera_id, url, video_dir="videos",
                 buffer_seconds=30, segment_seconds=30):
        self.camera_id = camera_id
        self.url = url
        self.fps = None  # measured on start
        self.buffer_seconds = buffer_seconds
        self.segment_seconds = segment_seconds

        # Ring buffer: (datetime, jpeg_bytes) — sized after fps is measured
        self.ring_buffer = deque(maxlen=1)
        self._buffer_lock = threading.Lock()

        # Latest frame for live MJPEG stream
        self._latest_jpeg = None
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()

        # Video writer state
        self._writer = None
        self._segment_boundary = None  # next rotation time
        self._segment_path = None
        self._frame_size = None

        # Directories
        self._raw_dir = os.path.join(video_dir, camera_id, "raw")
        os.makedirs(self._raw_dir, exist_ok=True)

        # State
        self._cap = None
        self._running = False
        self._thread = None
        self.connected = False

    def start(self):
        # Support integer device index (e.g. "0" for local webcam)
        source = int(self.url) if self.url.isdigit() else self.url
        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            raise ConnectionError(f"Cannot open camera {self.camera_id} at {self.url}")

        # Measure real fps and size the ring buffer accordingly
        self.fps = _measure_fps(self._cap)
        self.ring_buffer = deque(maxlen=self.buffer_seconds * self.fps)
        print(f"[camera] {self.camera_id} measured fps: {self.fps}")

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _set_connected(self, value):
        self.connected = value

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._finalize_segment()
        if self._cap:
            self._cap.release()

    def _capture_loop(self):
        fail_count = 0
        max_failures = 50  # ~0.5s of consecutive failures before considering camera down

        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                fail_count += 1
                if fail_count == max_failures:
                    print(f"[camera] {self.camera_id} lost connection, finalizing segment")
                    self._finalize_segment()
                    self._set_connected(False)
                if fail_count >= max_failures:
                    # Back off: try to reconnect every 2 seconds
                    time.sleep(2.0)
                    source = int(self.url) if self.url.isdigit() else self.url
                    self._cap.release()
                    self._cap = cv2.VideoCapture(source)
                else:
                    time.sleep(0.01)
                continue

            if fail_count >= max_failures:
                print(f"[camera] {self.camera_id} reconnected")
            fail_count = 0
            self._set_connected(True)

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

    def get_frame_at(self, target_ts):
        """Return the jpeg_bytes of the frame closest to target_ts, or None."""
        with self._buffer_lock:
            best = None
            best_diff = None
            for ts, jpeg in self.ring_buffer:
                diff = abs((ts - target_ts).total_seconds())
                if best_diff is None or diff < best_diff:
                    best = jpeg
                    best_diff = diff
                elif diff > best_diff:
                    break  # buffer is sorted, we've passed the closest
            return best

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
        if self._segment_boundary is None:
            return True
        return timestamp >= self._segment_boundary

    def _start_segment(self, frame, timestamp):
        # Name segment by its wall-clock slot (aligned to :00 or :30)
        slot_start = _segment_boundary_for(timestamp, self.segment_seconds)
        self._segment_boundary = _next_segment_boundary(timestamp, self.segment_seconds)

        filename = slot_start.strftime("%Y%m%dT%H%M%SZ") + ".mp4"
        self._segment_path = os.path.join(self._raw_dir, filename)

        h, w = frame.shape[:2]
        self._frame_size = (w, h)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(self._segment_path, fourcc, self.fps, (w, h))

    def _finalize_segment(self):
        if self._writer is not None:
            self._writer.release()
            self._writer = None
            self._segment_boundary = None
            self._segment_path = None
