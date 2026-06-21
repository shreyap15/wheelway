# WheelWay hardware — vision_modal obstacle-detection subsystem

Integrates the upstream [`vision_modal`](https://github.com/gurnoorssandhu/vision_modal)
physics-informed obstacle-detection pipeline as WheelWay's Raspberry Pi reactive
collision-avoidance subsystem.

* **Pinned upstream commit:** `7b9d8239af898033d254871f4b6a78ec505303a2`
  (git submodule at `hardware/vision_modal`). **Upstream has no LICENSE file** —
  no license is claimed here on its behalf.
* **Monocular looming is a RELATIVE cue, never metric depth.** No HC-SR04, no
  GPIO, no fabricated meter/centimeter distances.

```
camera → detector → tracker → Kalman → RK4 → collision evaluator
       → avoidance decision → WheelWay event sink → Flask POST /observations
```

The reactive loop keeps working when Flask / Redis / Deepgram / the internet /
OpenAI are unavailable. Publishing is nonblocking and can be disabled
(`WHEELWAY_PUBLISH_ENABLED=false` or `--no-publish`), leaving upstream behavior
unchanged.

## Layout

```
hardware/
├── vision_modal/            # upstream submodule (unchanged, pinned)
├── wheelway_bridge/         # WheelWay-owned integration
│   ├── observation.py       # upstream objects -> canonical observation (adapter)
│   ├── throttler.py         # WHEN to emit (command/risk/TTC/corridor/heartbeat)
│   ├── publisher.py         # bounded queue + nonblocking background HTTP worker
│   ├── status.py            # device liveness + heartbeat
│   ├── sink.py              # DI event sink (WheelwayEventSink / NoOpEventSink)
│   └── tests/               # no camera / Pi / network required
├── run_wheelway_vision.py   # Pi/laptop runner: upstream pipeline + event sink
└── .env.example
```

## Configuration

Copy `hardware/.env.example` to `hardware/.env` (git-ignored). Process env overrides it.
Key vars: `WHEELWAY_BACKEND_URL`, `WHEELWAY_DEVICE_ID`, `WHEELWAY_PUBLISH_ENABLED`,
`WHEELWAY_*_TTC_SECONDS`, `WHEELWAY_HEARTBEAT_SECONDS`, `WHEELWAY_QUEUE_SIZE`,
`WHEELWAY_DEVICE_TOKEN` (never logged). The `OPENAI_API_KEY` stays on the device and
is never sent to the WheelWay backend/frontend.

---

## Laptop smoke test (webcam, before Pi deployment)

```bash
# 1. Initialize the upstream submodule
git submodule update --init hardware/vision_modal

# 2. Virtualenv + deps
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r hardware/vision_modal/requirements.txt requests python-dotenv

# 3. Download the EfficientDet-Lite (LiteRT) detector model
mkdir -p hardware/vision_modal/models
curl -L -o hardware/vision_modal/models/efficientdet_lite0_pp.tflite \
  https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/object_detection/android/lite-model_efficientdet_lite0_detection_metadata_1.tflite

# 4. Point the bridge at the local backend
cp hardware/.env.example hardware/.env
#   set WHEELWAY_BACKEND_URL=http://127.0.0.1:5000   (laptop runs both)

# 5. Run the WheelWay backend (separate terminal)
cd backend && python main.py

# 6. Run the webcam pipeline (no OpenAI needed)
python hardware/run_wheelway_vision.py --no-llm

# 7. Verify observation receipt
curl http://127.0.0.1:5000/observations | python -m json.tool
#   -> entries with "source": "vision_modal" appear on command/risk changes.
```

## Raspberry Pi 4 (64-bit Pi OS, Picamera2)

```bash
sudo apt install -y python3-picamera2 git
git submodule update --init hardware/vision_modal
python3 -m venv --system-site-packages .venv     # system-site for picamera2
source .venv/bin/activate
pip install ai-edge-litert opencv-python openai numpy pillow requests python-dotenv

# EfficientDet-Lite model (same as laptop step 3)
mkdir -p hardware/vision_modal/models
curl -L -o hardware/vision_modal/models/efficientdet_lite0_pp.tflite \
  https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/object_detection/android/lite-model_efficientdet_lite0_detection_metadata_1.tflite

# Point the Pi at the laptop/server backend. DO NOT use localhost on the Pi --
# use the laptop's reachable LAN or Tailscale IP.
cp hardware/.env.example hardware/.env
#   WHEELWAY_BACKEND_URL=http://<laptop-lan-or-tailscale-ip>:5000

# Headless run (serves the annotated MJPEG on :8000), no OpenAI:
python hardware/run_wheelway_vision.py --source picamera --headless --no-llm
```

Optionally show the annotated stream in the WheelWay frontend by setting
`VITE_VISION_STREAM_URL=http://<pi-ip>:8000` (loaded directly from the Pi, behind a
toggle, hidden when unavailable).

## Tests

The bridge tests require no camera, Pi, Redis, Deepgram, or paid API:

```bash
cd hardware && python -m pytest wheelway_bridge/tests -q
```

The upstream pipeline's own smoke test needs the upstream requirements installed
(numpy/opencv/ai-edge-litert) plus the model file:

```bash
cd hardware/vision_modal && python tests/smoke_test.py
```
