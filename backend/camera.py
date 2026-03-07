import cv2
import threading
import subprocess
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
    slot_start_sec = (s // segment_seconds) * segment_seconds
    boundary_sec = slot_start_sec + segment_seconds
    boundary = now.replace(microsecond=0)
    if boundary_sec >= 60:
        boundary = boundary.replace(second=0)
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
    """Captures from an IP camera, maintains a ring buffer, writes MP4 segments,
    and optionally runs YOLO detection with annotated output."""

    def __init__(self, camera_id, url, video_dir="videos",
                 buffer_seconds=30, segment_seconds=30,
                 detector=None, detections_db=None):
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
        self._frame_cond = threading.Condition()
        self._frame_seq = 0

        # Video writer state (raw)
        self._writer = None
        self._segment_boundary = None  # next rotation time
        self._segment_path = None
        self._frame_size = None

        # Directories (raw)
        self._raw_dir = os.path.join(video_dir, camera_id, "raw")
        os.makedirs(self._raw_dir, exist_ok=True)

        # ── Detection ──────────────────────────────────────────
        self._detector = detector
        self._detections_db = detections_db

        # Raw frame handoff to detection thread
        self._latest_raw_frame = None
        self._raw_frame_seq = 0
        self._raw_frame_lock = threading.Lock()

        # Annotated frame for live MJPEG stream
        self._annotated_jpeg = None
        self._annotated_cond = threading.Condition()
        self._annotated_seq = 0

        # Annotated frame (numpy) for segment writer
        self._latest_annotated_frame = None
        self._annotated_frame_lock = threading.Lock()

        # Annotated segment writer
        self._ann_writer = None
        self._ann_segment_boundary = None
        self._ann_segment_path = None
        self._ann_raw_dir = os.path.join(video_dir, camera_id, "annotated")
        if self._detector:
            os.makedirs(self._ann_raw_dir, exist_ok=True)

        # State
        self._cap = None
        self._running = False
        self._thread = None
        self._det_thread = None
        self.connected = False

    @property
    def has_detector(self):
        return self._detector is not None

    def start(self, retries=3, retry_delay=2):
        source = int(self.url) if self.url.isdigit() else self.url
        for attempt in range(retries):
            self._cap = cv2.VideoCapture(source)
            if self._cap.isOpened():
                # Minimize internal buffer so read() returns the latest frame,
                # not stale queued frames (critical for network cameras).
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                break
            self._cap.release()
            if attempt < retries - 1:
                print(f"[camera] {self.camera_id} open failed, retrying in {retry_delay}s… ({attempt + 1}/{retries})")
                time.sleep(retry_delay)
        else:
            raise ConnectionError(f"Cannot open camera {self.camera_id} at {self.url}")

        # Measure real fps and size the ring buffer accordingly
        self.fps = _measure_fps(self._cap)
        self.ring_buffer = deque(maxlen=self.buffer_seconds * self.fps)
        print(f"[camera] {self.camera_id} measured fps: {self.fps}")

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        if self._detector:
            self._det_thread = threading.Thread(target=self._detection_loop, daemon=True)
            self._det_thread.start()
            print(f"[camera] {self.camera_id} detection thread started")

    def _set_connected(self, value):
        self.connected = value

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._det_thread:
            self._det_thread.join(timeout=5)
        self._finalize_segment()
        self._finalize_annotated_segment()
        if self._cap:
            self._cap.release()

    # ------------------------------------------------------------------
    # Capture loop
    # ------------------------------------------------------------------

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
                    self._finalize_annotated_segment()
                    self._set_connected(False)
                if fail_count >= max_failures:
                    # Back off: try to reconnect every 2 seconds
                    time.sleep(2.0)
                    source = int(self.url) if self.url.isdigit() else self.url
                    self._cap.release()
                    self._cap = cv2.VideoCapture(source)
                    self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
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

            # Update latest frame and notify all waiting consumers
            with self._frame_cond:
                self._latest_jpeg = jpeg_bytes
                self._frame_seq += 1
                self._frame_cond.notify_all()

            # Push to ring buffer
            with self._buffer_lock:
                self.ring_buffer.append((now, jpeg_bytes))

            # Write raw frame to disk segment
            self._write_frame(frame, now)

            # Feed detection thread and write annotated segment
            if self._detector:
                with self._raw_frame_lock:
                    self._latest_raw_frame = frame
                    self._raw_frame_seq += 1

                with self._annotated_frame_lock:
                    ann_frame = self._latest_annotated_frame
                if ann_frame is not None:
                    self._write_annotated_frame(ann_frame, now)

    # ------------------------------------------------------------------
    # Detection loop (runs in separate thread)
    # ------------------------------------------------------------------

    def _detection_loop(self):
        last_seq = -1
        while self._running:
            frame = None
            with self._raw_frame_lock:
                if self._raw_frame_seq != last_seq and self._latest_raw_frame is not None:
                    frame = self._latest_raw_frame
                    last_seq = self._raw_frame_seq

            if frame is None:
                time.sleep(0.03)
                continue

            try:
                annotated, detections = self._detector.process(frame)
            except Exception as e:
                print(f"[detector] {self.camera_id} error: {e}")
                time.sleep(1.0)
                continue

            # Store annotated numpy frame for segment writer
            with self._annotated_frame_lock:
                self._latest_annotated_frame = annotated

            # Encode JPEG for live annotated stream
            _, jpeg = cv2.imencode(".jpg", annotated)
            jpeg_bytes = jpeg.tobytes()

            with self._annotated_cond:
                self._annotated_jpeg = jpeg_bytes
                self._annotated_seq += 1
                self._annotated_cond.notify_all()

            # Persist detections to DB
            if detections and self._detections_db:
                try:
                    self._detections_db.insert(
                        self.camera_id, datetime.now(timezone.utc), detections
                    )
                except Exception as e:
                    print(f"[detector] {self.camera_id} DB error: {e}")

    # ------------------------------------------------------------------
    # Live stream access
    # ------------------------------------------------------------------

    def get_latest_jpeg(self):
        with self._frame_cond:
            return self._latest_jpeg

    def wait_for_frame(self, timeout=1.0):
        """Block until a new frame arrives (or timeout). Returns jpeg bytes or None.
        Each caller independently waits — multiple consumers get every frame."""
        with self._frame_cond:
            seq = self._frame_seq
            self._frame_cond.wait_for(lambda: self._frame_seq != seq, timeout=timeout)
            return self._latest_jpeg

    def wait_for_annotated_frame(self, timeout=1.0):
        """Block until a new annotated frame arrives (or timeout). Returns jpeg bytes or None."""
        with self._annotated_cond:
            seq = self._annotated_seq
            self._annotated_cond.wait_for(lambda: self._annotated_seq != seq, timeout=timeout)
            return self._annotated_jpeg

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

    def list_segments(self, annotated=False):
        """Return sorted list of segment filenames."""
        dir_path = self._ann_raw_dir if annotated else self._raw_dir
        if not os.path.isdir(dir_path):
            return []
        files = [f for f in os.listdir(dir_path) if f.endswith(".mp4")]
        files.sort()
        return files

    def segment_path(self, filename, annotated=False):
        dir_path = self._ann_raw_dir if annotated else self._raw_dir
        return os.path.join(dir_path, filename)

    # ------------------------------------------------------------------
    # Video writer internals (raw)
    # ------------------------------------------------------------------

    def _write_frame(self, frame, timestamp):
        if self._writer is None or self._should_rotate(timestamp):
            self._finalize_segment()
            self._start_segment(frame, timestamp)
        try:
            self._writer.stdin.write(frame.tobytes())
        except BrokenPipeError:
            print(f"[camera] {self.camera_id} ffmpeg pipe broken, will restart segment")
            self._writer = None

    def _should_rotate(self, timestamp):
        if self._segment_boundary is None:
            return True
        return timestamp >= self._segment_boundary

    def _start_segment(self, frame, timestamp):
        slot_start = _segment_boundary_for(timestamp, self.segment_seconds)
        self._segment_boundary = _next_segment_boundary(timestamp, self.segment_seconds)

        filename = slot_start.strftime("%Y%m%dT%H%M%SZ") + ".mp4"
        self._segment_path = os.path.join(self._raw_dir, filename)

        h, w = frame.shape[:2]
        self._frame_size = (w, h)

        self._writer = subprocess.Popen(
            ["ffmpeg", "-y",
             "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{w}x{h}", "-r", str(self.fps),
             "-i", "pipe:0",
             "-c:v", "libx264", "-preset", "ultrafast",
             "-movflags", "+faststart",
             self._segment_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"[camera] {self.camera_id} started segment {filename}")

    def _finalize_segment(self):
        if self._writer is not None:
            try:
                self._writer.stdin.close()
                self._writer.wait(timeout=10)
            except Exception as e:
                print(f"[camera] {self.camera_id} segment finalize error: {e}")
                self._writer.kill()
            self._writer = None
            self._segment_boundary = None
            self._segment_path = None

    # ------------------------------------------------------------------
    # Video writer internals (annotated)
    # ------------------------------------------------------------------

    def _write_annotated_frame(self, frame, timestamp):
        if self._ann_writer is None or self._ann_should_rotate(timestamp):
            self._finalize_annotated_segment()
            self._start_annotated_segment(frame, timestamp)
        try:
            self._ann_writer.stdin.write(frame.tobytes())
        except BrokenPipeError:
            print(f"[camera] {self.camera_id} annotated ffmpeg pipe broken")
            self._ann_writer = None

    def _ann_should_rotate(self, timestamp):
        if self._ann_segment_boundary is None:
            return True
        return timestamp >= self._ann_segment_boundary

    def _start_annotated_segment(self, frame, timestamp):
        slot_start = _segment_boundary_for(timestamp, self.segment_seconds)
        self._ann_segment_boundary = _next_segment_boundary(timestamp, self.segment_seconds)

        filename = slot_start.strftime("%Y%m%dT%H%M%SZ") + ".mp4"
        self._ann_segment_path = os.path.join(self._ann_raw_dir, filename)

        h, w = frame.shape[:2]

        self._ann_writer = subprocess.Popen(
            ["ffmpeg", "-y",
             "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{w}x{h}", "-r", str(self.fps),
             "-i", "pipe:0",
             "-c:v", "libx264", "-preset", "ultrafast",
             "-movflags", "+faststart",
             self._ann_segment_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"[camera] {self.camera_id} started annotated segment {filename}")

    def _finalize_annotated_segment(self):
        if self._ann_writer is not None:
            try:
                self._ann_writer.stdin.close()
                self._ann_writer.wait(timeout=10)
            except Exception as e:
                print(f"[camera] {self.camera_id} annotated segment finalize error: {e}")
                self._ann_writer.kill()
            self._ann_writer = None
            self._ann_segment_boundary = None
            self._ann_segment_path = None
