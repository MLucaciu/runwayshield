# Camera Emulator

Standalone MJPEG stream server that plays a video file in a loop, emulating a live camera feed. Useful for development and demos when no physical camera is available.

Completely independent from the backend — runs as its own process.

## Setup

```bash
cd cam_emulator
pip install -r requirements.txt
```

Only dependency is `opencv-python-headless`.

## Usage

```bash
./run.sh                                # serve default sample video on :8554
./run.sh --video path/to/video.mp4      # use a specific video
./run.sh --port 9000                    # change port
./run.sh --fps 30                       # override playback FPS
```

Or directly:

```bash
python emulator.py --video videos/sample.mp4 --port 8554
```

## Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Preview page with embedded stream |
| `GET /video` | MJPEG stream (use as camera URL) |
| `GET /snapshot` | Single JPEG frame |

## Connecting to the backend

Point a backend camera source to the emulator stream:

```bash
CAMERA_1_URL=http://localhost:8554/video ./run.sh   # from backend/
```

## Videos

Place `.mp4` files in `cam_emulator/videos/`. A `sample.mp4` is included by default. Replace it with any video you want to loop.

The emulator auto-discovers videos in this order:
1. `cam_emulator/videos/*.mp4`
2. `backend/videos/**/raw/*.mp4` (fallback)

## Options

| Flag | Default | Description |
|---|---|---|
| `--video` | auto-discover | Path to video file |
| `--port` | `8554` | HTTP server port |
| `--fps` | video native | Override playback frame rate |
