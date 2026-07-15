#!/usr/bin/python3
"""Dachshund Gatekeeper: dual-source, strictly accelerated J722S vision demo."""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import datetime as dt
import glob
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np
import onnxruntime as ort
import tflite_runtime.interpreter as tflite


DETECTOR_NAME = "ONR-OD-8200-yolox-nano-lite-mmdet-coco-416x416"
DETECTOR_FILE = "yolox_nano_lite_416x416_20220214_model.onnx"
BREED_NAME = "TFL-CL-DOGBREEDS31-mobileNetV2"
BREED_FILE = "mobilenetv2-dog-breeds-31.tflite"
COCO_DOG_LABEL = 16  # Internal contiguous index; COCO category ID is 18.
VIDEO_EXTENSIONS = {".avi", ".h264", ".h265", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def box_iou(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as stream:
        for line in stream:
            key, value = line.split(":", 1)
            fields = value.split()
            if fields:
                values[key] = int(fields[0]) * 1024
    return values


def process_rss_bytes() -> int:
    with open("/proc/self/status", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


class CpuSampler:
    """Report non-idle system CPU between UI status polls without another dependency."""

    def __init__(self):
        self.lock = threading.Lock()
        self.previous = self._read()

    @staticmethod
    def _read() -> tuple[int, int]:
        fields = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()[1:]
        values = [int(value) for value in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    def percent(self) -> float:
        with self.lock:
            current = self._read()
            total_delta = current[0] - self.previous[0]
            idle_delta = current[1] - self.previous[1]
            self.previous = current
        if total_delta <= 0:
            return 0.0
        return clamp((total_delta - idle_delta) * 100.0 / total_delta, 0.0, 100.0)


def remoteproc_evidence() -> list[dict[str, str]]:
    results = []
    for directory in sorted(glob.glob("/sys/class/remoteproc/remoteproc*")):
        firmware_path = Path(directory) / "firmware"
        state_path = Path(directory) / "state"
        try:
            firmware = firmware_path.read_text(encoding="ascii").strip()
            state = state_path.read_text(encoding="ascii").strip()
        except OSError:
            continue
        if "c71" in firmware or "main-r5" in firmware:
            results.append({"firmware": firmware, "state": state})
    return results


@dataclass
class Detection:
    box: tuple[int, int, int, int]
    score: float
    inference_ms: float


@dataclass
class BreedResult:
    label: str
    score: float
    top5: list[dict[str, Any]]
    inference_ms: float
    tidl_run_ms: float
    ddr_read_bytes: int
    ddr_write_bytes: int


class DogDetector:
    """YOLOX-Nano session with CPU graph execution forbidden."""

    def __init__(self, model_dir: Path, core: int, threshold: float):
        self.model_dir = model_dir.resolve()
        self.model = self.model_dir / "model" / DETECTOR_FILE
        self.artifacts = self.model_dir / "artifacts"
        self.threshold = threshold
        info_path = self.artifacts / "tidl-compiler-info.json"
        required = (
            self.model,
            self.artifacts / "allowedNode.txt",
            self.artifacts / "onnxrtMetaData.txt",
            self.artifacts / "subgraph_0_tidl_net.bin",
            self.artifacts / "subgraph_0_tidl_io_1.bin",
            info_path,
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"detector assets are missing: {missing}")
        info = json.loads(info_path.read_text(encoding="utf-8"))
        self.nodes = int(info.get("graph_nodes_offloaded", 0))
        if self.nodes != 283:
            raise RuntimeError(f"detector is not the complete 283-node TIDL graph: {info}")
        if (self.artifacts / "subgraph_0_tidl_io_1.bin").stat().st_size != 380_952:
            raise RuntimeError("detector TIDL I/O descriptor does not match runtime ABI")
        for name, expected in info.get("artifact_sha256", {}).items():
            path = self.artifacts / name
            if not path.is_file() or sha256(path) != expected:
                raise RuntimeError(f"detector artifact hash mismatch: {name}")
        if "TIDLExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError(f"TIDLExecutionProvider unavailable: {ort.get_available_providers()}")

        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = 1
        options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
        self.session = ort.InferenceSession(
            str(self.model),
            sess_options=options,
            providers=["TIDLExecutionProvider"],
            provider_options=[{
                "artifacts_folder": str(self.artifacts),
                "core_number": str(core),
                "debug_level": "0",
            }],
        )
        self.session.disable_fallback()
        if not self.session.get_providers() or self.session.get_providers()[0] != "TIDLExecutionProvider":
            raise RuntimeError(f"TIDL is not the detector provider: {self.session.get_providers()}")
        tensor = self.session.get_inputs()[0]
        if tuple(tensor.shape) != (1, 3, 416, 416) or tensor.type != "tensor(uint8)":
            raise RuntimeError(f"unexpected detector input: {tensor.name} {tensor.shape} {tensor.type}")
        self.input_name = tensor.name
        self.output_names = [output.name for output in self.session.get_outputs()]
        if set(self.output_names) != {"dets", "labels"}:
            raise RuntimeError(f"unexpected detector outputs: {self.output_names}")
        self.core = core
        self.invocations = 0

    @staticmethod
    def _preprocess(frame: np.ndarray) -> tuple[np.ndarray, float]:
        height, width = frame.shape[:2]
        scale = min(416 / width, 416 / height)
        resized = cv2.resize(
            frame,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_LINEAR,
        )
        canvas = np.full((416, 416, 3), 114, dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None, ...]), scale

    def detect(self, frame: np.ndarray) -> Detection | None:
        tensor, scale = self._preprocess(frame)
        started = time.perf_counter()
        values = self.session.run(None, {self.input_name: tensor})
        inference_ms = (time.perf_counter() - started) * 1000.0
        self.invocations += 1
        outputs = dict(zip(self.output_names, values))
        boxes = np.asarray(outputs["dets"]).reshape(-1, 5)
        labels = np.asarray(outputs["labels"]).reshape(-1)
        height, width = frame.shape[:2]
        candidates = []
        for box, label in zip(boxes, labels):
            score = float(box[4])
            if int(label) != COCO_DOG_LABEL or score < self.threshold:
                continue
            x1 = int(clamp(float(box[0]) / scale, 0, width - 1))
            y1 = int(clamp(float(box[1]) / scale, 0, height - 1))
            x2 = int(clamp(float(box[2]) / scale, x1 + 1, width))
            y2 = int(clamp(float(box[3]) / scale, y1 + 1, height))
            candidates.append(Detection((x1, y1, x2, y2), score, inference_ms))
        return max(candidates, key=lambda candidate: candidate.score, default=None)


class BreedClassifier:
    """MobileNetV2 TFLite session with all 71 operators delegated to TIDL."""

    def __init__(self, model_dir: Path, core: int):
        self.model_dir = model_dir.resolve()
        self.model = self.model_dir / "model" / BREED_FILE
        self.artifacts = self.model_dir / "artifacts"
        labels_path = self.model_dir / "test-data" / "labels.json"
        info_path = self.artifacts / "tidl-tflite-compiler-info.json"
        required = (self.model, labels_path, info_path, self.artifacts / "allowedNode.txt")
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"breed assets are missing: {missing}")
        self.info = json.loads(info_path.read_text(encoding="utf-8"))
        if self.info.get("graph_nodes_offloaded") != 71 or self.info.get("delegate_groups") != 1:
            raise RuntimeError(f"breed model is not one complete TIDL graph: {self.info}")
        for name, expected in self.info.get("artifact_sha256", {}).items():
            path = self.artifacts / name
            if not path.is_file() or sha256(path) != expected:
                raise RuntimeError(f"breed artifact hash mismatch: {name}")
        self.labels = {
            int(index): label for index, label in json.loads(labels_path.read_text()).items()
        }
        resolver = tflite.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES
        original = tflite.Interpreter(
            model_path=str(self.model), num_threads=1, experimental_op_resolver_type=resolver
        )
        original.allocate_tensors()
        original_ops = original._get_ops_details()
        if len(original_ops) != 71 or any(op["op_name"] == "DELEGATE" for op in original_ops):
            raise RuntimeError("breed FlatBuffer is not the expected 71-operator graph")
        del original
        delegate = tflite.load_delegate(
            "libtidl_tfl_delegate.so",
            {"artifacts_folder": str(self.artifacts), "core_number": str(core), "debug_level": "0"},
        )
        self.interpreter = tflite.Interpreter(
            model_path=str(self.model),
            experimental_delegates=[delegate],
            num_threads=1,
            experimental_op_resolver_type=resolver,
        )
        self.interpreter.allocate_tensors()
        runtime_ops = self.interpreter._get_ops_details()
        delegate_ops = [op for op in runtime_ops if op["op_name"] == "DELEGATE"]
        if len(delegate_ops) != 1:
            raise RuntimeError(f"TIDL did not create one breed delegate group: {runtime_ops}")
        self.input = self.interpreter.get_input_details()[0]
        self.output = self.interpreter.get_output_details()[0]
        if delegate_ops[0]["outputs"].tolist() != [int(self.output["index"])]:
            raise RuntimeError("breed TIDL group does not own the model output")
        self.core = core
        self.invocations = 0

    def classify(self, crop: np.ndarray) -> BreedResult:
        resized = cv2.resize(crop, (224, 224), interpolation=cv2.INTER_NEAREST)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        tensor = np.ascontiguousarray(rgb[None, ...], dtype=np.float32) / 255.0
        self.interpreter.set_tensor(self.input["index"], tensor)
        started = time.perf_counter()
        self.interpreter.invoke()
        inference_ms = (time.perf_counter() - started) * 1000.0
        self.invocations += 1
        scores = np.asarray(self.interpreter.get_tensor(self.output["index"])).reshape(-1)
        indices = np.argsort(scores)[-5:][::-1]
        top5 = [
            {"index": int(index), "label": self.labels[int(index)], "score": float(scores[index])}
            for index in indices
        ]
        benchmark = {key: int(value) for key, value in self.interpreter.get_TI_benchmark_data().items()}
        run_ns = benchmark.get("ts:run_end", 0) - benchmark.get("ts:run_start", 0)
        read_bytes = benchmark.get("ddr:read_end", 0) - benchmark.get("ddr:read_start", 0)
        write_bytes = benchmark.get("ddr:write_end", 0) - benchmark.get("ddr:write_start", 0)
        if run_ns <= 0 or read_bytes <= 0 or write_bytes <= 0:
            raise RuntimeError(f"breed TIDL counters are invalid: {benchmark}")
        return BreedResult(
            label=top5[0]["label"],
            score=top5[0]["score"],
            top5=top5,
            inference_ms=inference_ms,
            tidl_run_ms=run_ns / 1_000_000.0,
            ddr_read_bytes=read_bytes,
            ddr_write_bytes=write_bytes,
        )


class DecisionEngine:
    def __init__(self, target_breed: str, threshold: float, stable_frames: int):
        self.target_breed = target_breed
        self.threshold = threshold
        self.stable_frames = stable_frames
        self.last_box: tuple[int, int, int, int] | None = None
        self.track_frames = 0
        self.missed_frames = 0
        self.match_streak = 0
        self.state = "WATCHING"

    def update(self, detection: Detection | None, breed: BreedResult | None) -> tuple[str, bool]:
        previous = self.state
        if detection is None:
            self.missed_frames += 1
            if self.missed_frames >= 3:
                self.last_box = None
                self.track_frames = 0
                self.match_streak = 0
                self.state = "WATCHING"
            return self.state, previous != self.state
        self.missed_frames = 0
        if self.last_box is not None and box_iou(self.last_box, detection.box) >= 0.30:
            self.track_frames += 1
        else:
            self.track_frames = 1
            self.match_streak = 0
        self.last_box = detection.box
        if breed is None:
            self.state = "TRACKING"
        elif breed.label.casefold() == self.target_breed.casefold() and breed.score >= self.threshold:
            self.match_streak += 1
            self.state = "AUTHORIZED" if self.match_streak >= self.stable_frames else "VERIFYING"
        else:
            self.match_streak = 0
            self.state = "HELD" if breed.score >= self.threshold else "VERIFYING"
        return self.state, previous != self.state


class FrameSource:
    source_type = "unknown"
    label = "Unknown"
    isp_active = False

    def read(self) -> tuple[bool, np.ndarray | None]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class VideoSource(FrameSource):
    source_type = "video"
    isp_active = False

    def __init__(self, path: Path, loop: bool):
        self.path = path.resolve()
        if not self.path.is_file():
            raise RuntimeError(f"video does not exist: {self.path}")
        self.capture = cv2.VideoCapture(str(self.path))
        if not self.capture.isOpened():
            raise RuntimeError(f"OpenCV cannot open video: {self.path}")
        self.loop = loop
        self.label = self.path.name

    def read(self) -> tuple[bool, np.ndarray | None]:
        ok, frame = self.capture.read()
        if not ok and self.loop:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        return ok, frame

    def close(self) -> None:
        self.capture.release()


class IMX219Source(FrameSource):
    source_type = "camera"
    label = "IMX219 · CSI0"
    isp_active = True

    MEDIA_FORMATS = (
        '"imx219 4-0010":0[fmt:SRGGB8_1X8/1920x1080 field:none]',
        '"cdns_csi2rx.30101000.csi-bridge":0[fmt:SRGGB8_1X8/1920x1080 field:none]',
        '"cdns_csi2rx.30101000.csi-bridge":1[fmt:SRGGB8_1X8/1920x1080 field:none]',
        '"30102000.ticsi2rx":0[fmt:SRGGB8_1X8/1920x1080 field:none]',
        '"30102000.ticsi2rx":1[fmt:SRGGB8_1X8/1920x1080 field:none]',
    )

    def __init__(self):
        if os.geteuid() != 0:
            raise RuntimeError("IMX219/VPAC capture requires root for Vision Apps memory devices")
        for media_format in self.MEDIA_FORMATS:
            subprocess.run(
                ["media-ctl", "-d", "/dev/media0", "-V", media_format],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        pipeline = (
            "v4l2src device=/dev/video2 io-mode=5 ! "
            "video/x-bayer,width=1920,height=1080,format=rggb,framerate=30/1 ! "
            "tiovxisp sensor-name=SENSOR_SONY_IMX219_RPI "
            "dcc-isp-file=/opt/imaging/imx219/linear/dcc_viss_1920x1080.bin "
            "format-msb=7 "
            "sink_0::dcc-2a-file=/opt/imaging/imx219/linear/dcc_2a_1920x1080.bin "
            "sink_0::device=/dev/v4l-subdev2 ! "
            "video/x-raw,format=NV12 ! queue leaky=downstream max-size-buffers=2 ! "
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink drop=true sync=false max-buffers=1"
        )
        self.capture = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not self.capture.isOpened():
            raise RuntimeError("OpenCV/GStreamer could not start the IMX219 VPAC ISP pipeline")

    def read(self) -> tuple[bool, np.ndarray | None]:
        return self.capture.read()

    def close(self) -> None:
        self.capture.release()


class Gatekeeper:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.detector = DogDetector(Path(args.detector_dir), args.detector_core, args.detector_threshold)
        self.classifier = BreedClassifier(Path(args.breed_dir), args.breed_core)
        self.decision = DecisionEngine(args.target_breed, args.breed_threshold, args.stable_frames)
        self.output_dir = Path(args.output_dir).resolve()
        self.upload_dir = self.output_dir / "uploads"
        self.proof_dir = self.output_dir / "proof"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.proof_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.frame_condition = threading.Condition(self.lock)
        self.stop_event = threading.Event()
        self.paused = False
        self.error = ""
        self.source: FrameSource | None = None
        self.source_request: tuple[str, str] | None = None
        self.latest_jpeg = b""
        self.latest_raw: np.ndarray | None = None
        self.frame_sequence = 0
        self.started = time.monotonic()
        self.frame_times: deque[float] = deque(maxlen=90)
        self.latencies: deque[float] = deque(maxlen=90)
        self.events: deque[dict[str, Any]] = deque(maxlen=50)
        self.cpu_sampler = CpuSampler()
        self.last_detection: Detection | None = None
        self.last_breed: BreedResult | None = None
        self.last_event_state = ""
        self.last_event_at = 0.0
        self.thread = threading.Thread(target=self._run, name="gatekeeper-inference", daemon=True)

    def start(self) -> None:
        source_value = self.args.video if self.args.source == "video" else ""
        self.source_request = (self.args.source, source_value)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=10)
        with self.lock:
            if self.source:
                self.source.close()
                self.source = None

    def request_source(self, source_type: str, value: str = "") -> None:
        if source_type not in ("camera", "video"):
            raise ValueError("source must be camera or video")
        if source_type == "video":
            path = Path(value).expanduser().resolve()
            if not path.is_file() or path.suffix.casefold() not in VIDEO_EXTENSIONS:
                raise ValueError(f"unsupported or missing video: {path}")
            value = str(path)
        with self.lock:
            self.source_request = (source_type, value)
            self.error = ""

    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self.paused = paused

    def _change_source(self, source_type: str, value: str) -> None:
        candidate: FrameSource
        if source_type == "camera":
            candidate = IMX219Source()
        else:
            candidate = VideoSource(Path(value), self.args.loop)
        with self.lock:
            previous = self.source
            self.source = candidate
            self.decision = DecisionEngine(
                self.args.target_breed, self.args.breed_threshold, self.args.stable_frames
            )
            self.last_detection = None
            self.last_breed = None
            self.events.appendleft({
                "timestamp": utc_now(),
                "state": "SOURCE",
                "title": f"Source changed to {candidate.label}",
                "confidence": None,
            })
        if previous:
            previous.close()

    def _event(self, state: str, breed: BreedResult | None) -> None:
        now = time.monotonic()
        if state == self.last_event_state and now - self.last_event_at < 5:
            return
        titles = {
            "AUTHORIZED": f"{self.args.target_breed} admitted",
            "HELD": f"{breed.label if breed else 'Unknown breed'} held",
            "VERIFYING": "Breed verification in progress",
        }
        if state not in titles:
            return
        self.events.appendleft({
            "timestamp": utc_now(),
            "state": state,
            "title": titles[state],
            "confidence": breed.score if breed else None,
        })
        self.last_event_state = state
        self.last_event_at = now

    def _run(self) -> None:
        while not self.stop_event.is_set():
            request = None
            with self.lock:
                if self.source_request:
                    request = self.source_request
                    self.source_request = None
                paused = self.paused
                source = self.source
            if request:
                try:
                    self._change_source(*request)
                except Exception as error:  # Keep HTTP/UI alive for recovery.
                    with self.lock:
                        self.error = f"{type(error).__name__}: {error}"
                    time.sleep(0.5)
                continue
            if paused or source is None:
                time.sleep(0.05)
                continue
            ok, frame = source.read()
            if not ok or frame is None:
                with self.lock:
                    self.error = f"Source stopped: {source.label}"
                time.sleep(0.2)
                continue
            frame_started = time.perf_counter()
            try:
                detection = self.detector.detect(frame)
                breed = None
                if detection:
                    x1, y1, x2, y2 = detection.box
                    # Breed classification needs silhouette and scene context. A tight
                    # detector crop made long-bodied dogs resemble Dobermans; retain a
                    # configurable quarter-box margin while still isolating each dog.
                    margin_x = max(4, int((x2 - x1) * self.args.crop_margin))
                    margin_y = max(4, int((y2 - y1) * self.args.crop_margin))
                    crop = frame[
                        max(0, y1 - margin_y): min(frame.shape[0], y2 + margin_y),
                        max(0, x1 - margin_x): min(frame.shape[1], x2 + margin_x),
                    ]
                    if crop.size:
                        breed = self.classifier.classify(crop)
                state, changed = self.decision.update(detection, breed)
                if changed:
                    self._event(state, breed)
                encode_frame = frame
                if frame.shape[1] > self.args.stream_width:
                    scale = self.args.stream_width / frame.shape[1]
                    encode_frame = cv2.resize(
                        frame,
                        (self.args.stream_width, round(frame.shape[0] * scale)),
                        interpolation=cv2.INTER_AREA,
                    )
                ok, encoded = cv2.imencode(
                    ".jpg", encode_frame, [cv2.IMWRITE_JPEG_QUALITY, self.args.jpeg_quality]
                )
                if not ok:
                    raise RuntimeError("JPEG encoding failed")
                now = time.monotonic()
                with self.frame_condition:
                    self.latest_raw = frame.copy()
                    self.latest_jpeg = encoded.tobytes()
                    self.last_detection = detection
                    self.last_breed = breed
                    self.frame_sequence += 1
                    self.frame_times.append(now)
                    self.latencies.append((time.perf_counter() - frame_started) * 1000.0)
                    self.error = ""
                    self.frame_condition.notify_all()
            except Exception as error:
                with self.lock:
                    self.error = f"{type(error).__name__}: {error}"
                time.sleep(0.1)

    def status(self) -> dict[str, Any]:
        with self.lock:
            source = self.source
            detection = self.last_detection
            breed = self.last_breed
            frame_sequence = self.frame_sequence
            events = list(self.events)[:3]
            error = self.error
            paused = self.paused
            state = self.decision.state
            track_frames = self.decision.track_frames
            frame_times = list(self.frame_times)
            latencies = list(self.latencies)
            frame_shape = self.latest_raw.shape[:2] if self.latest_raw is not None else None
        fps = 0.0
        if len(frame_times) > 1 and frame_times[-1] > frame_times[0]:
            fps = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
        memory = read_meminfo()
        box_normalized = None
        if detection and frame_shape is not None:
            height, width = frame_shape
            x1, y1, x2, y2 = detection.box
            box_normalized = {
                "left": x1 / width,
                "top": y1 / height,
                "width": (x2 - x1) / width,
                "height": (y2 - y1) / height,
            }
        return {
            "version": 1,
            "captured_utc": utc_now(),
            "uptime_seconds": time.monotonic() - self.started,
            "paused": paused,
            "error": error,
            "source": {
                "type": source.source_type if source else "starting",
                "label": source.label if source else "Starting…",
                "isp_active": bool(source and source.isp_active),
            },
            "decision": {
                "state": state,
                "target_breed": self.args.target_breed,
                "threshold": self.args.breed_threshold,
                "stable_frames_required": self.args.stable_frames,
            },
            "detection": {
                "present": detection is not None,
                "score": detection.score if detection else None,
                "box_normalized": box_normalized,
                "inference_ms": detection.inference_ms if detection else None,
            },
            "breed": {
                "label": breed.label if breed else "No subject",
                "score": breed.score if breed else None,
                "top5": breed.top5 if breed else [],
                "inference_ms": breed.inference_ms if breed else None,
                "tidl_run_ms": breed.tidl_run_ms if breed else None,
            },
            "tracker": {
                "state": "LOCKED" if track_frames >= self.args.stable_frames else (
                    "ACQUIRING" if track_frames else "IDLE"
                ),
                "frames": track_frames,
            },
            "performance": {
                "fps": fps,
                "end_to_end_ms": float(np.mean(latencies[-30:])) if latencies else 0.0,
                "frames": frame_sequence,
            },
            "acceleration": {
                "active": self.detector.invocations > 0 and self.classifier.invocations > 0,
                "label": "C7x/MMA ACTIVE",
                "cpu_fallback": 0,
                "detector": {
                    "runtime": "ONNX Runtime",
                    "provider": "TIDLExecutionProvider",
                    "core": self.detector.core,
                    "nodes": self.detector.nodes,
                    "invocations": self.detector.invocations,
                },
                "breed": {
                    "runtime": "TFLite",
                    "delegate": "libtidl_tfl_delegate.so",
                    "core": self.classifier.core,
                    "operators": 71,
                    "delegate_groups": 1,
                    "invocations": self.classifier.invocations,
                    "ddr_read_bytes": breed.ddr_read_bytes if breed else 0,
                    "ddr_write_bytes": breed.ddr_write_bytes if breed else 0,
                },
                "remoteprocs": remoteproc_evidence(),
            },
            "memory": {
                "total_bytes": memory.get("MemTotal", 0),
                "available_bytes": memory.get("MemAvailable", 0),
                "used_bytes": memory.get("MemTotal", 0) - memory.get("MemAvailable", 0),
                "process_rss_bytes": process_rss_bytes(),
            },
            "system": {
                "cpu_percent": self.cpu_sampler.percent(),
            },
            "events": events,
        }

    def capture_proof(self) -> dict[str, str]:
        with self.lock:
            if self.latest_raw is None:
                raise RuntimeError("no frame is available")
            frame = self.latest_raw.copy()
            detection = self.last_detection
            breed = self.last_breed
        if detection:
            x1, y1, x2, y2 = detection.box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (22, 220, 168), 3)
            label = breed.label if breed else "Dog"
            confidence = breed.score if breed else detection.score
            cv2.rectangle(frame, (x1, max(0, y1 - 38)), (min(frame.shape[1], x1 + 330), y1), (3, 13, 22), -1)
            cv2.putText(
                frame, f"{label} {confidence * 100:.1f}%", (x1 + 8, max(24, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.72, (22, 220, 168), 2, cv2.LINE_AA,
            )
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        image_path = self.proof_dir / f"gatekeeper-{stamp}.jpg"
        json_path = self.proof_dir / f"gatekeeper-{stamp}.json"
        if not cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94]):
            raise RuntimeError("proof image write failed")
        result = self.status()
        result["proof_image"] = str(image_path)
        result["proof_image_sha256"] = sha256(image_path)
        json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"image": str(image_path), "json": str(json_path)}


class GatekeeperHandler(BaseHTTPRequestHandler):
    server_version = "DachshundGatekeeper/1"
    gatekeeper: Gatekeeper
    static_dir: Path

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"HTTP {self.address_string()} {format_string % args}")

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 64 * 1024:
            raise ValueError("invalid JSON body length")
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._json(self.gatekeeper.status())
            return
        if parsed.path == "/stream.mjpg":
            self._stream()
            return
        if parsed.path == "/frame.jpg":
            with self.gatekeeper.lock:
                frame = self.gatekeeper.latest_jpeg
            if not frame:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE.value, "No frame is available")
                return
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)
            return
        relative = "index.html" if parsed.path == "/" else unquote(parsed.path.lstrip("/"))
        target = (self.static_dir / relative).resolve()
        if self.static_dir not in target.parents and target != self.static_dir:
            self.send_error(HTTPStatus.FORBIDDEN.value)
            return
        if not target.is_file() and "." not in Path(relative).name:
            target = self.static_dir / "index.html"
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last_sequence = -1
        try:
            while not self.gatekeeper.stop_event.is_set():
                with self.gatekeeper.frame_condition:
                    self.gatekeeper.frame_condition.wait_for(
                        lambda: self.gatekeeper.frame_sequence != last_sequence,
                        timeout=2,
                    )
                    sequence = self.gatekeeper.frame_sequence
                    frame = self.gatekeeper.latest_jpeg
                if not frame or sequence == last_sequence:
                    continue
                last_sequence = sequence
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/source":
                body = self._read_json()
                self.gatekeeper.request_source(str(body.get("type", "")), str(body.get("path", "")))
                self._json({"ok": True}, HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/control":
                action = str(self._read_json().get("action", ""))
                if action == "pause":
                    self.gatekeeper.set_paused(True)
                    result: Any = {"ok": True, "paused": True}
                elif action == "resume":
                    self.gatekeeper.set_paused(False)
                    result = {"ok": True, "paused": False}
                elif action == "capture":
                    result = {"ok": True, "proof": self.gatekeeper.capture_proof()}
                else:
                    raise ValueError(f"unknown action: {action}")
                self._json(result)
                return
            if parsed.path == "/api/upload":
                self._upload(parsed)
                return
            self.send_error(HTTPStatus.NOT_FOUND.value)
        except (ValueError, RuntimeError, json.JSONDecodeError) as error:
            self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _upload(self, parsed: Any) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > self.gatekeeper.args.max_upload_bytes:
            raise ValueError("video is empty or exceeds upload limit")
        raw_name = parse_qs(parsed.query).get("filename", [""])[0]
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_name).name)
        extension = Path(name).suffix.casefold()
        if not name or extension not in VIDEO_EXTENSIONS:
            raise ValueError(f"unsupported video filename: {raw_name}")
        target = self.gatekeeper.upload_dir / f"{int(time.time())}-{name}"
        temporary = target.with_suffix(target.suffix + ".part")
        remaining = length
        with temporary.open("wb") as stream:
            while remaining:
                block = self.rfile.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("upload ended early")
                stream.write(block)
                remaining -= len(block)
        os.replace(temporary, target)
        self.gatekeeper.request_source("video", str(target))
        self._json({"ok": True, "path": str(target)}, HTTPStatus.CREATED)


def parse_args() -> argparse.Namespace:
    demo_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("camera", "video"), default="video")
    parser.add_argument("--video", default="/opt/edgeai-test-data/videos/video0_1280_768_h264.mp4")
    parser.add_argument("--detector-dir", default=f"/opt/model_zoo/{DETECTOR_NAME}")
    parser.add_argument("--breed-dir", default=f"/opt/model_zoo/{BREED_NAME}")
    parser.add_argument("--detector-core", type=int, choices=(1, 2), default=1)
    parser.add_argument("--breed-core", type=int, choices=(1, 2), default=2)
    parser.add_argument("--detector-threshold", type=float, default=0.35)
    parser.add_argument("--breed-threshold", type=float, default=0.72)
    parser.add_argument("--crop-margin", type=float, default=0.25)
    parser.add_argument("--stable-frames", type=int, default=3)
    parser.add_argument("--target-breed", default="Dachshund")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--ui-dir", default=str(demo_dir / "ui" / "dist"))
    parser.add_argument("--output-dir", default="/var/lib/ti-edgeai-gatekeeper")
    parser.add_argument("--stream-width", type=int, default=1280)
    parser.add_argument("--jpeg-quality", type=int, default=84)
    parser.add_argument("--max-upload-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-loop", dest="loop", action="store_false")
    args = parser.parse_args()
    if args.detector_core == args.breed_core:
        parser.error("detector and breed classifier must use different C7x cores")
    if not 0 < args.detector_threshold <= 1 or not 0 < args.breed_threshold <= 1:
        parser.error("thresholds must be in (0, 1]")
    if not 0 <= args.crop_margin <= 1:
        parser.error("crop margin must be in [0, 1]")
    if args.stable_frames < 1 or not 1 <= args.jpeg_quality <= 100:
        parser.error("stable frames and JPEG quality are invalid")
    if not Path(args.ui_dir).is_dir():
        parser.error(f"built UI is missing: {args.ui_dir}; run ui/build-ui.sh")
    return args


def main() -> int:
    args = parse_args()
    gatekeeper = Gatekeeper(args)
    GatekeeperHandler.gatekeeper = gatekeeper
    GatekeeperHandler.static_dir = Path(args.ui_dir).resolve()
    server = ThreadingHTTPServer((args.host, args.port), GatekeeperHandler)

    def request_stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    gatekeeper.start()
    print(f"Dachshund Gatekeeper listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        gatekeeper.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
