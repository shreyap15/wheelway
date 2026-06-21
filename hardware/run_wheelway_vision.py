#!/usr/bin/env python
"""WheelWay Pi runner: upstream vision_modal pipeline + WheelWay event sink.

Runs the EXACT upstream reactive pipeline (camera -> detect -> track -> Kalman ->
RK4 -> collision -> avoidance -> annotated MJPEG) and attaches the WheelWay
bridge at the final risk/planning boundary. The bridge is dependency-injected and
nonblocking; with it disabled this behaves like ``python vision_modal/app.py``.

The reactive loop keeps working when Flask/Redis/Deepgram/internet are down and
when OpenAI scene reasoning is disabled (``--no-llm``). Publishing never blocks
the camera/physics loop.

Examples:
    # Laptop webcam validation (windowed):
    python hardware/run_wheelway_vision.py --no-llm
    # Raspberry Pi, headless MJPEG, no OpenAI:
    python hardware/run_wheelway_vision.py --source picamera --headless --no-llm
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# --- Make the upstream submodule importable (top-level packages: config,
#     perception, physics, planning, viz, reasoning). ---
_HERE = Path(__file__).resolve().parent
_UPSTREAM = _HERE / "vision_modal"
if str(_UPSTREAM) not in sys.path:
    sys.path.insert(0, str(_UPSTREAM))
# WheelWay bridge package (hardware/ on path).
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _load_dotenv() -> None:
    """Load hardware/.env (if python-dotenv is present); process env still wins."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(_HERE / ".env", override=False)


def parse_args(cfg):
    p = argparse.ArgumentParser(description="WheelWay vision_modal runner")
    p.add_argument("--source", choices=["webcam", "picamera"], default=cfg.source)
    p.add_argument("--headless", action="store_true", help="serve MJPEG instead of a window")
    p.add_argument("--no-llm", action="store_true", help="disable OpenAI scene reasoning")
    p.add_argument("--backend", choices=["litert", "mediapipe"], default=cfg.detector_backend)
    p.add_argument("--model", default=None, help="override detector model path")
    p.add_argument("--threads", type=int, default=cfg.num_threads)
    p.add_argument("--width", type=int, default=cfg.width)
    p.add_argument("--height", type=int, default=cfg.height)
    p.add_argument("--flip", action="store_true", default=cfg.flip)
    p.add_argument("--no-publish", action="store_true", help="disable WheelWay publishing")
    a = p.parse_args()
    cfg.source = a.source
    cfg.headless = a.headless
    cfg.detector_backend = a.backend
    if a.model:
        cfg.model_path = a.model
        cfg.mediapipe_model_path = a.model
    cfg.num_threads = a.threads
    cfg.width, cfg.height, cfg.flip = a.width, a.height, a.flip
    if a.no_llm:
        cfg.llm_enabled = False
    return cfg, a


def main() -> int:
    _load_dotenv()

    import config as cfg_mod
    from perception.async_detector import AsyncDetector
    from perception.tracker import Tracker
    from perception.depth import MonoLoomingDepth
    from physics import rk4, collision
    from physics.motion_models import get_model
    from planning import avoidance
    from reasoning.scene_llm import SceneReasoner
    from viz import overlay

    from wheelway_bridge.sink import build_sink_from_env

    cfg, args = parse_args(cfg_mod.load())

    model_path = cfg.mediapipe_model_path if cfg.detector_backend == "mediapipe" else cfg.model_path
    if not os.path.exists(model_path):
        print(f"ERROR: detector model not found at {model_path}. See hardware/README "
              f"(or vision_modal/README) for the EfficientDet-Lite download.", file=sys.stderr)
        return 1

    if cfg.llm_enabled and not os.environ.get("OPENAI_API_KEY"):
        print("note: OPENAI_API_KEY not set -> scene reasoning disabled (reactive loop unaffected).")
        cfg.llm_enabled = False

    if cfg.detector_backend == "mediapipe":
        from perception.detector import ObjectDetector
        detector = ObjectDetector(model_path, cfg.score_threshold, cfg.max_results,
                                  cfg.detect_size, cfg.allowed_labels)
    else:
        from perception.litert_detector import LiteRTDetector
        detector = LiteRTDetector(model_path, cfg.score_threshold, cfg.max_results,
                                  cfg.allowed_labels, cfg.num_threads)

    async_det = AsyncDetector(detector)
    async_det.start()
    tracker = Tracker(cfg.iou_match_threshold, cfg.max_age, cfg.min_hits)
    depth = MonoLoomingDepth()
    model_f = get_model(cfg.motion_model, cfg.drag_coeff)
    smoother = avoidance.CommandSmoother(cfg.command_hold_s)

    scene = SceneReasoner(cfg.llm_model, cfg.llm_interval_s, cfg.llm_jpeg_quality, cfg.llm_max_tokens)
    if cfg.llm_enabled:
        scene.start()

    streamer = None
    if cfg.headless:
        from viz.mjpeg import AnnotatedMJPEGServer
        streamer = AnnotatedMJPEGServer(cfg.stream_port, cfg.stream_jpeg_quality)
        streamer.start()
        print(f"serving annotated stream on http://<host>:{cfg.stream_port}")

    # --- WheelWay bridge (dependency-injected, nonblocking) ---
    env = dict(os.environ)
    if args.no_publish:
        env["WHEELWAY_PUBLISH_ENABLED"] = "false"
    # Keep the bridge's risk threshold / horizon in sync with the upstream config.
    sink = build_sink_from_env(env)
    for attr, val in (("risk_threshold", cfg.risk_threshold), ("predict_horizon_s", cfg.predict_horizon_s)):
        if hasattr(sink, attr):
            setattr(sink, attr, val)
    sink.start()
    publishing = getattr(getattr(sink, "publisher", None), "enabled", False)
    print(f"WheelWay publishing: {'on' if publishing else 'off'}")

    if cfg.source == "picamera":
        from camera.picamera import PiCameraSource
        cam = PiCameraSource(cfg.width, cfg.height, cfg.flip)
    else:
        from camera.webcam import WebcamSource
        cam = WebcamSource(cfg.cam_index, cfg.width, cfg.height, cfg.flip)

    import cv2

    prev_ts = 0.0
    fps = 0.0
    last_action = None
    last_seq = -1
    print("running. press 'q' in the window to quit (or Ctrl-C if headless).")
    try:
        while True:
            frame, ts = cam.read()
            if frame is None or ts == prev_ts:
                time.sleep(0.003)
                continue
            dt = (ts - prev_ts) if prev_ts else 1.0 / 30.0
            prev_ts = ts
            h, w = frame.shape[:2]
            status = getattr(sink, "status", None)
            if status:
                status.mark_frame()

            async_det.set_frame(frame)
            dets, seq = async_det.get()
            fresh = seq != last_seq
            if fresh and status:
                status.mark_detector()
            last_seq = seq

            tracks = tracker.update(dets if fresh else [], dt)
            risks, trajectories = [], []
            items = []
            for t in tracks:
                traj = rk4.rollout(t.state, cfg.predict_horizon_s, cfg.predict_steps, model_f)
                _ = depth.estimate(t.state)
                r = collision.evaluate(t.state, traj, w, h, cfg.corridor_frac,
                                       cfg.ttc_warn_s, cfg.ttc_stop_s)
                risks.append(r)
                trajectories.append(traj)
                items.append({"track": t, "risk": r, "traj": traj})

            command = smoother.update(
                avoidance.decide(risks, cfg.risk_threshold, cfg.ttc_stop_s), ts)
            if command.action != last_action:
                print(f"[{time.strftime('%H:%M:%S')}] {command.action:5s} | {command.reason}")
                last_action = command.action

            scene.set_frame(frame)

            # --- WheelWay integration hook (nonblocking; never overrides command) ---
            sink.publish(
                command=command,
                tracks=tracks,
                risks=risks,
                trajectories=trajectories,
                frame_width=w,
                frame_height=h,
                timestamp=None,
                scene_reasoning=scene.get(),
            )

            overlay.annotate(frame, items, command, scene.get(), fps, cfg.corridor_frac, async_det.fps)
            inst = 1.0 / dt if dt > 0 else 0.0
            fps = inst if fps == 0 else 0.9 * fps + 0.1 * inst

            if streamer is not None:
                streamer.set_frame(frame)
            else:
                cv2.imshow("wheelway_vision", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        sink.stop()
        scene.stop()
        if streamer is not None:
            streamer.stop()
        async_det.stop()
        cam.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
