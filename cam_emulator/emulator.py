#!/usr/bin/env python3
"""
Camera Emulator — serves MJPEG streams from video files, looping forever.

Standalone service, no dependency on the backend.

Starts two camera feeds:
    - Port 8554: video from video_cam_1/
    - Port 8555: video from videos_cam_2/

Usage:
    python emulator.py

The MJPEG streams are available at:
    http://localhost:8554/video
    http://localhost:8555/video
"""

import glob
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure print output is not buffered
sys.stdout.reconfigure(line_buffering=True)

import cv2


def make_handler(camera, lock, fps):
    """Create a request handler class bound to a specific camera."""

    class MJPEGStreamHandler(BaseHTTPRequestHandler):
        _camera = camera
        _lock = lock
        _fps = fps

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path == "/video":
                self._stream()
            elif self.path == "/snapshot":
                self._snapshot()
            else:
                self._index()

        def _index(self):
            html = (
                "<html><body>"
                "<h2>Camera Emulator</h2>"
                '<img src="/video" style="max-width:100%;" /><br/>'
                '<p><a href="/snapshot">Snapshot (single JPEG)</a></p>'
                "</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())

        def _snapshot(self):
            frame = self._read_frame()
            if frame is None:
                self.send_error(503, "No frame available")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(frame)

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            interval = 1.0 / self._fps
            next_frame_time = time.monotonic()
            try:
                while True:
                    frame = self._read_frame()
                    if frame is None:
                        time.sleep(0.1)
                        continue
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    next_frame_time += interval
                    sleep_dur = next_frame_time - time.monotonic()
                    if sleep_dur > 0:
                        time.sleep(sleep_dur)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _read_frame(self):
            with self._lock:
                ret, frame = self._camera.read()
                if not ret:
                    self._camera.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self._camera.read()
                if not ret:
                    return None
                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                return jpeg.tobytes()

    return MJPEGStreamHandler


def find_video(directory):
    """Find the first .mp4 file in a directory."""
    matches = sorted(glob.glob(os.path.join(directory, "*.mp4")))
    return matches[0] if matches else None


def start_camera(video_path, port):
    """Open a video file and serve it as MJPEG on the given port."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  ERROR: Cannot open video: {video_path}", file=sys.stderr)
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"  Video:  {os.path.basename(video_path)}  ({total_frames} frames, {fps:.0f} fps)")
    print(f"  Stream: http://0.0.0.0:{port}/video")
    print()

    handler = make_handler(cap, threading.Lock(), fps)
    server = HTTPServer(("0.0.0.0", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, cap


def main():
    base = os.path.dirname(os.path.abspath(__file__))

    cameras = [
        {"name": "Camera 1", "dir": os.path.join(base, "video_cam_1"), "port": 8554},
        {"name": "Camera 2", "dir": os.path.join(base, "videos_cam_2"), "port": 8555},
    ]

    print("=" * 50)
    print("  Runway Shield — Camera Emulator")
    print("=" * 50)
    print()

    servers = []
    for cam in cameras:
        video = find_video(cam["dir"])
        if not video:
            print(f"[{cam['name']}] No .mp4 file found in {cam['dir']}", file=sys.stderr)
            sys.exit(1)

        print(f"[{cam['name']}] port {cam['port']}")
        result = start_camera(video, cam["port"])
        if result is None:
            sys.exit(1)
        servers.append(result)

    print("Both cameras running. Press Ctrl+C to stop.")
    print()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        for server, cap in servers:
            server.shutdown()
            cap.release()


if __name__ == "__main__":
    main()
