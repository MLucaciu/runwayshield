#!/usr/bin/env python3
"""
Camera Emulator — serves an MJPEG stream from a video file, looping forever.

Standalone service, no dependency on the backend.

Usage:
    python emulator.py [OPTIONS]

Options:
    --video   Path to video file (default: first .mp4 found in videos/)
    --port    Port to serve on (default: 8554)
    --fps     Override playback FPS (default: use video's native FPS)

The MJPEG stream is available at:
    http://localhost:<port>/video
A simple status page is at:
    http://localhost:<port>/
"""

import argparse
import glob
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import cv2


class MJPEGStreamHandler(BaseHTTPRequestHandler):
    """Serves MJPEG stream over HTTP."""

    camera = None  # set by main before starting server
    lock = None
    fps = 25

    def log_message(self, format, *args):
        # suppress per-request logs to keep output clean
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
        interval = 1.0 / self.fps
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
                time.sleep(interval)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_frame(self):
        with self.lock:
            ret, frame = self.camera.read()
            if not ret:
                # loop: rewind to start
                self.camera.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self.camera.read()
            if not ret:
                return None
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return jpeg.tobytes()


def find_default_video():
    """Find a video file to use as default."""
    base = os.path.dirname(os.path.abspath(__file__))
    # look in local videos/ subfolder first
    for pattern in ["videos/*.mp4", "videos/**/*.mp4"]:
        matches = glob.glob(os.path.join(base, pattern), recursive=True)
        if matches:
            return sorted(matches)[0]
    # then look in backend/videos/
    project_root = os.path.dirname(base)
    matches = glob.glob(os.path.join(project_root, "backend/videos/**/raw/*.mp4"), recursive=True)
    if matches:
        return sorted(matches)[0]
    return None


def main():
    parser = argparse.ArgumentParser(description="Camera Emulator — MJPEG stream from video file")
    parser.add_argument("--video", type=str, default=None, help="Path to video file")
    parser.add_argument("--port", type=int, default=8554, help="Port to serve on (default: 8554)")
    parser.add_argument("--fps", type=float, default=None, help="Override playback FPS")
    args = parser.parse_args()

    video_path = args.video or find_default_video()
    if not video_path or not os.path.isfile(video_path):
        print(f"Error: No video file found. Provide one with --video <path>", file=sys.stderr)
        sys.exit(1)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video: {video_path}", file=sys.stderr)
        sys.exit(1)

    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25
    fps = args.fps or native_fps
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"Video:  {video_path}")
    print(f"Frames: {total_frames}  |  FPS: {fps:.1f}")
    print(f"Serving MJPEG stream on http://0.0.0.0:{args.port}/video")
    print(f"Status page: http://0.0.0.0:{args.port}/")

    MJPEGStreamHandler.camera = cap
    MJPEGStreamHandler.lock = threading.Lock()
    MJPEGStreamHandler.fps = fps

    server = HTTPServer(("0.0.0.0", args.port), MJPEGStreamHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        cap.release()
        server.server_close()


if __name__ == "__main__":
    main()
