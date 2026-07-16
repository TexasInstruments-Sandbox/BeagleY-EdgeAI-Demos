#!/usr/bin/python3
"""OmniCode: accelerated, multi-format code reading for BeagleY-AI J722S."""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
from dataclasses import asdict, dataclass
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
import signal
import subprocess
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np
import onnxruntime as ort


MODEL_NAME = "ONR-OD-TI-BARCODE-YOLOX-NANO-416"
MODEL_FILE = "model.onnx"
GRAPH_NODES = 283
J722S_IO_BYTES = 380_952
VIDEO_EXTENSIONS = {".avi", ".h264", ".h265", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS


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


def box_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    if not intersection:
        return 0.0
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    return intersection / (left_area + right_area - intersection)


def process_rss_bytes() -> int:
    with open("/proc/self/status", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    return 0


def memory_status() -> dict[str, int]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as stream:
        for line in stream:
            key, remainder = line.split(":", 1)
            fields = remainder.split()
            if fields:
                values[key] = int(fields[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": total - available,
        "process_rss_bytes": process_rss_bytes(),
    }


def remoteproc_evidence() -> list[dict[str, str]]:
    evidence = []
    for directory in sorted(glob.glob("/sys/class/remoteproc/remoteproc*")):
        try:
            firmware = (Path(directory) / "firmware").read_text(encoding="ascii").strip()
            state = (Path(directory) / "state").read_text(encoding="ascii").strip()
        except OSError:
            continue
        if "c71" in firmware or "main-r5" in firmware:
            evidence.append({"firmware": firmware, "state": state})
    return evidence


class CpuSampler:
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = self._read()

    @staticmethod
    def _read() -> tuple[int, int]:
        values = [int(field) for field in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    def percent(self) -> float:
        with self.lock:
            current = self._read()
            total = current[0] - self.previous[0]
            idle = current[1] - self.previous[1]
            self.previous = current
        return clamp((total - idle) * 100 / total, 0, 100) if total > 0 else 0.0


@dataclass
class Detection:
    box: tuple[int, int, int, int]
    score: float


@dataclass
class Scan:
    id: str
    timestamp: str
    format: str
    text: str
    content_type: str
    symbology_identifier: str
    orientation: int
    detector_score: float
    decode_ms: float
    box: tuple[int, int, int, int]
    count: int = 1


class BarcodeDetector:
    """TI barcode localizer with ONNX CPU execution explicitly forbidden."""

    def __init__(self, model_dir: Path, core: int, threshold: float):
        self.model_dir = model_dir.resolve()
        self.model = self.model_dir / "model" / MODEL_FILE
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
        self.info = json.loads(info_path.read_text(encoding="utf-8"))
        if self.info.get("graph_nodes_offloaded") != GRAPH_NODES:
            raise RuntimeError(f"detector is not the complete {GRAPH_NODES}-node graph")
        if (self.artifacts / "subgraph_0_tidl_io_1.bin").stat().st_size != J722S_IO_BYTES:
            raise RuntimeError("detector descriptor is not the J722S PSDK 11.02 ABI")
        for name, expected in self.info.get("artifact_sha256", {}).items():
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
        self.registered_providers = self.session.get_providers()
        # ORT registers its built-in CPU provider after requested providers on
        # this build. Registration is not graph execution: the fallback path is
        # disabled above, disable_fallback() is called, and the compiler
        # manifest proves that every node belongs to the single TIDL subgraph.
        if not self.registered_providers or self.registered_providers[0] != "TIDLExecutionProvider":
            raise RuntimeError(f"TIDL is not the primary provider: {self.registered_providers}")
        tensor = self.session.get_inputs()[0]
        if tuple(tensor.shape) != (1, 3, 416, 416) or tensor.type != "tensor(uint8)":
            raise RuntimeError(f"unexpected input: {tensor.name} {tensor.shape} {tensor.type}")
        self.input_name = tensor.name
        self.output_names = [output.name for output in self.session.get_outputs()]
        if set(self.output_names) != {"dets", "labels"}:
            raise RuntimeError(f"unexpected outputs: {self.output_names}")
        self.core = core
        self.invocations = 0
        self.last_ms = 0.0

    @staticmethod
    def preprocess(frame: np.ndarray) -> tuple[np.ndarray, float]:
        height, width = frame.shape[:2]
        scale = min(416 / width, 416 / height)
        resized = cv2.resize(
            frame, (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_LINEAR,
        )
        canvas = np.full((416, 416, 3), 114, dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None, ...]), scale

    def detect(self, frame: np.ndarray) -> list[Detection]:
        tensor, scale = self.preprocess(frame)
        started = time.perf_counter()
        values = self.session.run(None, {self.input_name: tensor})
        self.last_ms = (time.perf_counter() - started) * 1000
        self.invocations += 1
        outputs = dict(zip(self.output_names, values))
        boxes = np.asarray(outputs["dets"]).reshape(-1, 5)
        labels = np.asarray(outputs["labels"]).reshape(-1)
        height, width = frame.shape[:2]
        detections = []
        for box, label in zip(boxes, labels):
            score = float(box[4])
            if int(label) != 0 or score < self.threshold:
                continue
            x1 = int(clamp(float(box[0]) / scale, 0, width - 1))
            y1 = int(clamp(float(box[1]) / scale, 0, height - 1))
            x2 = int(clamp(float(box[2]) / scale, x1 + 1, width))
            y2 = int(clamp(float(box[3]) / scale, y1 + 1, height))
            detections.append(Detection((x1, y1, x2, y2), score))
        return detections


class ZxingDecoder:
    """Thin ctypes binding; it is intentionally invoked only on TIDL ROIs."""

    def __init__(self, library: Path, formats: str):
        self.library_path = library.resolve()
        self.library = ctypes.CDLL(str(self.library_path))
        self.library.omnicode_decode_luma.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t,
        ]
        self.library.omnicode_decode_luma.restype = ctypes.c_int
        self.library.omnicode_decoder_version.argtypes = []
        self.library.omnicode_decoder_version.restype = ctypes.c_char_p
        self.version = self.library.omnicode_decoder_version().decode("ascii")
        self.formats = formats.encode("ascii") if formats else None
        self.lock = threading.Lock()
        self.invocations = 0
        self.last_ms = 0.0

    def decode(self, crop: np.ndarray) -> tuple[list[dict[str, Any]], float]:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        gray = np.ascontiguousarray(gray, dtype=np.uint8)
        output = ctypes.create_string_buffer(256 * 1024)
        started = time.perf_counter()
        count = self.library.omnicode_decode_luma(
            gray.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            gray.shape[1], gray.shape[0], gray.strides[0], self.formats,
            output, len(output),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        with self.lock:
            self.last_ms = elapsed_ms
            self.invocations += 1
        if count < 0:
            raise RuntimeError(f"ZXing decoder returned {count}")
        values = json.loads(output.value.decode("utf-8"))
        if count != len(values):
            raise RuntimeError("ZXing result count does not match its JSON payload")
        return values, elapsed_ms


class FrameSource:
    source_type = "unknown"
    label = "Unknown"
    isp_active = False

    def read(self) -> tuple[bool, np.ndarray | None]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class MediaSource(FrameSource):
    def __init__(self, path: Path, loop: bool, image_fps: float):
        self.path = path.resolve()
        if not self.path.is_file() or self.path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise RuntimeError(f"unsupported or missing media: {self.path}")
        self.label = self.path.name
        self.loop = loop
        self.image = None
        self.next_frame = 0.0
        self.image_period = 1 / image_fps
        if self.path.suffix.casefold() in IMAGE_EXTENSIONS:
            self.source_type = "image"
            self.image = cv2.imread(str(self.path), cv2.IMREAD_COLOR)
            if self.image is None:
                raise RuntimeError(f"OpenCV cannot read image: {self.path}")
            self.capture = None
        else:
            self.source_type = "video"
            self.capture = cv2.VideoCapture(str(self.path))
            if not self.capture.isOpened():
                raise RuntimeError(f"OpenCV cannot open video: {self.path}")

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.image is not None:
            remaining = self.next_frame - time.monotonic()
            if remaining > 0:
                time.sleep(min(remaining, self.image_period))
            self.next_frame = time.monotonic() + self.image_period
            return True, self.image.copy()
        ok, frame = self.capture.read()
        if not ok and self.loop:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        return ok, frame

    def close(self) -> None:
        if self.capture is not None:
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
            raise RuntimeError("IMX219/VPAC capture requires root for Vision Apps devices")
        for media_format in self.MEDIA_FORMATS:
            subprocess.run(
                ["media-ctl", "-d", "/dev/media0", "-V", media_format],
                check=True, stdout=subprocess.DEVNULL,
            )
        pipeline = (
            "v4l2src device=/dev/video2 io-mode=5 ! "
            "video/x-bayer,width=1920,height=1080,format=rggb,framerate=30/1 ! "
            "tiovxisp sensor-name=SENSOR_SONY_IMX219_RPI "
            "dcc-isp-file=/opt/imaging/imx219/linear/dcc_viss_1920x1080.bin format-msb=7 "
            "sink_0::dcc-2a-file=/opt/imaging/imx219/linear/dcc_2a_1920x1080.bin "
            "sink_0::device=/dev/v4l-subdev2 ! video/x-raw,format=NV12 ! "
            "queue leaky=downstream max-size-buffers=2 ! videoconvert ! "
            "video/x-raw,format=BGR ! appsink drop=true sync=false max-buffers=1"
        )
        self.capture = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
        if not self.capture.isOpened():
            raise RuntimeError("GStreamer could not start IMX219 through the VPAC ISP")

    def read(self) -> tuple[bool, np.ndarray | None]:
        return self.capture.read()

    def close(self) -> None:
        self.capture.release()


class OmniCode:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.detector = BarcodeDetector(Path(args.model_dir), args.core, args.detector_threshold)
        self.decoder = ZxingDecoder(Path(args.decoder_library), args.formats)
        self.output_dir = Path(args.output_dir).resolve()
        self.upload_dir = self.output_dir / "uploads"
        self.proof_dir = self.output_dir / "proof"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.proof_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.frame_condition = threading.Condition(self.lock)
        self.stop_event = threading.Event()
        self.source: FrameSource | None = None
        self.source_request: tuple[str, str] | None = None
        self.paused = False
        self.error = ""
        self.latest_jpeg = b""
        self.latest_raw: np.ndarray | None = None
        self.latest_detections: list[Detection] = []
        self.decoded_tracks: list[tuple[tuple[int, int, int, int], int]] = []
        self.decode_attempts: list[tuple[tuple[int, int, int, int], int]] = []
        self.frame_sequence = 0
        self.jpeg_sequence = 0
        self.next_jpeg_at = 0.0
        self.encoder_pending = False
        self.encoder_skips = 0
        self.source_generation = 0
        self.started = time.monotonic()
        self.frame_times: deque[float] = deque(maxlen=90)
        self.latencies: deque[float] = deque(maxlen=90)
        self.compute_times: deque[float] = deque(maxlen=90)
        self.source_times: deque[float] = deque(maxlen=90)
        self.decoder_wall_times: deque[float] = deque(maxlen=90)
        self.decoder_cpu_times: deque[float] = deque(maxlen=90)
        self.decoder_jobs: deque[int] = deque(maxlen=90)
        self.encoder_times: deque[float] = deque(maxlen=90)
        self.jpeg_times: deque[float] = deque(maxlen=90)
        self.scans: deque[Scan] = deque(maxlen=50)
        self.scan_index: dict[tuple[str, str], Scan] = {}
        self.selected: Scan | None = None
        self.cpu_sampler = CpuSampler()
        self.decoder_pool = ThreadPoolExecutor(
            max_workers=args.decoder_workers, thread_name_prefix="omnicode-zxing"
        )
        self.encoder_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="omnicode-jpeg")
        self.thread = threading.Thread(target=self._run, name="omnicode-inference", daemon=True)

    def start(self) -> None:
        value = self.args.media if self.args.source == "media" else ""
        self.source_request = (self.args.source, value)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=10)
        self.decoder_pool.shutdown(wait=True, cancel_futures=True)
        self.encoder_pool.shutdown(wait=True, cancel_futures=True)
        with self.lock:
            if self.source:
                self.source.close()
                self.source = None

    def request_source(self, source_type: str, value: str = "") -> None:
        if source_type not in ("camera", "media"):
            raise ValueError("source must be camera or media")
        if source_type == "media":
            path = Path(value).expanduser().resolve()
            if not path.is_file() or path.suffix.casefold() not in SUPPORTED_EXTENSIONS:
                raise ValueError(f"unsupported or missing media: {path}")
            value = str(path)
        with self.lock:
            self.source_request = (source_type, value)
            self.error = ""

    def clear(self) -> None:
        with self.lock:
            self.scans.clear()
            self.scan_index.clear()
            self.selected = None

    def _change_source(self, source_type: str, value: str) -> None:
        candidate: FrameSource = (
            IMX219Source() if source_type == "camera"
            else MediaSource(Path(value), self.args.loop, self.args.image_fps)
        )
        with self.lock:
            previous = self.source
            self.source = candidate
            self.latest_jpeg = b""
            self.latest_raw = None
            self.latest_detections = []
            self.decoded_tracks = []
            self.decode_attempts = []
            self.frame_sequence = 0
            self.next_jpeg_at = 0.0
            self.encoder_skips = 0
            self.source_generation += 1
            self.frame_times.clear()
            self.latencies.clear()
            self.compute_times.clear()
            self.source_times.clear()
            self.decoder_wall_times.clear()
            self.decoder_cpu_times.clear()
            self.decoder_jobs.clear()
            self.encoder_times.clear()
            self.jpeg_times.clear()
            self.error = ""
        if previous:
            previous.close()

    def _record_scan(self, decoded: dict[str, Any], detection: Detection, decode_ms: float) -> Scan:
        key = (str(decoded["format"]), str(decoded["text"]))
        existing = self.scan_index.get(key)
        if existing:
            existing.count += 1
            existing.timestamp = utc_now()
            existing.detector_score = detection.score
            existing.decode_ms = decode_ms
            existing.box = detection.box
            self.selected = existing
            return existing
        identity = hashlib.sha256(f"{key[0]}\0{key[1]}".encode()).hexdigest()[:12]
        scan = Scan(
            id=identity, timestamp=utc_now(), format=key[0], text=key[1],
            content_type=str(decoded.get("content_type", "Text")),
            symbology_identifier=str(decoded.get("symbology_identifier", "")),
            orientation=int(decoded.get("orientation", 0)),
            detector_score=detection.score, decode_ms=decode_ms, box=detection.box,
        )
        self.scans.appendleft(scan)
        self.scan_index[key] = scan
        self.selected = scan
        while len(self.scan_index) > self.scans.maxlen:
            keep = {(scan.format, scan.text) for scan in self.scans}
            self.scan_index = {key: value for key, value in self.scan_index.items() if key in keep}
        return scan

    def _decode_detection(
        self, frame: np.ndarray, detection: Detection
    ) -> tuple[list[dict[str, Any]], float]:
        x1, y1, x2, y2 = detection.box
        margin_x = max(8, round((x2 - x1) * self.args.crop_margin))
        margin_y = max(8, round((y2 - y1) * self.args.crop_margin))
        crop = frame[
            max(0, y1 - margin_y): min(frame.shape[0], y2 + margin_y),
            max(0, x1 - margin_x): min(frame.shape[1], x2 + margin_x),
        ]
        if not crop.size:
            return [], 0.0
        shortest = min(crop.shape[:2])
        if shortest < self.args.min_decode_pixels:
            scale = self.args.min_decode_pixels / shortest
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        return self.decoder.decode(crop)

    def _remember_decoded(self, detection: Detection) -> None:
        expires = self.frame_sequence + max(
            2, self.args.decode_interval * 2, self.args.decode_retry_frames
        )
        retained = [
            (box, expiry) for box, expiry in self.decoded_tracks
            if expiry >= self.frame_sequence and box_iou(box, detection.box) < 0.5
        ]
        retained.append((detection.box, expires))
        self.decoded_tracks = retained

    def _claim_decode(self, detection: Detection) -> bool:
        retained = [
            (box, expiry) for box, expiry in self.decode_attempts
            if expiry >= self.frame_sequence
        ]
        if any(box_iou(box, detection.box) >= 0.65 for box, _expiry in retained):
            self.decode_attempts = retained
            return False
        retained.append((detection.box, self.frame_sequence + self.args.decode_retry_frames))
        self.decode_attempts = retained
        return True

    def _encode_frame(self, frame: np.ndarray) -> bytes:
        display = frame
        if frame.shape[1] > self.args.stream_width:
            scale = self.args.stream_width / frame.shape[1]
            display = cv2.resize(
                frame, (self.args.stream_width, round(frame.shape[0] * scale)),
                interpolation=cv2.INTER_AREA,
            )
        ok, encoded = cv2.imencode(".jpg", display, [cv2.IMWRITE_JPEG_QUALITY, self.args.jpeg_quality])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return encoded.tobytes()

    def _finish_encode(
        self, future: Any, frame: np.ndarray, detections: list[Detection],
        generation: int, started: float,
    ) -> None:
        try:
            jpeg = future.result()
            elapsed_ms = (time.perf_counter() - started) * 1000
        except Exception as error:
            with self.lock:
                self.encoder_pending = False
                self.error = f"{type(error).__name__}: {error}"
            return
        with self.frame_condition:
            self.encoder_pending = False
            if generation != self.source_generation:
                return
            self.latest_raw = frame
            self.latest_jpeg = jpeg
            self.latest_detections = detections
            self.encoder_times.append(elapsed_ms)
            self.jpeg_times.append(time.monotonic())
            self.jpeg_sequence += 1
            self.frame_condition.notify_all()

    def _schedule_encode(self, frame: np.ndarray, detections: list[Detection]) -> None:
        now = time.monotonic()
        with self.lock:
            if self.encoder_pending or now < self.next_jpeg_at:
                self.encoder_skips += 1
                return
            self.encoder_pending = True
            self.next_jpeg_at = now + 1 / self.args.stream_fps
            generation = self.source_generation
        started = time.perf_counter()
        future = self.encoder_pool.submit(self._encode_frame, frame)
        future.add_done_callback(
            lambda completed: self._finish_encode(
                completed, frame, detections, generation, started
            )
        )

    def _run(self) -> None:
        while not self.stop_event.is_set():
            with self.lock:
                request = self.source_request
                self.source_request = None
                source = self.source
                paused = self.paused
            if request:
                try:
                    self._change_source(*request)
                except Exception as error:
                    with self.lock:
                        self.error = f"{type(error).__name__}: {error}"
                    time.sleep(0.5)
                continue
            if source is None or paused:
                time.sleep(0.05)
                continue
            loop_started = time.perf_counter()
            ok, frame = source.read()
            source_ms = (time.perf_counter() - loop_started) * 1000
            if not ok or frame is None:
                with self.lock:
                    self.error = f"Source stopped: {source.label}"
                time.sleep(0.15)
                continue
            started = time.perf_counter()
            try:
                detections = self.detector.detect(frame)
                decode_wall_ms = 0.0
                decode_cpu_ms = 0.0
                decode_count = 0
                if detections and self.frame_sequence % self.args.decode_interval == 0:
                    decode_started = time.perf_counter()
                    eligible = [
                        detection for detection in detections if self._claim_decode(detection)
                    ]
                    futures = [
                        (detection, self.decoder_pool.submit(self._decode_detection, frame, detection))
                        for detection in eligible
                    ]
                    decode_count = len(futures)
                    for detection, future in futures:
                        decoded_values, decode_ms = future.result()
                        decode_cpu_ms += decode_ms
                        with self.lock:
                            if decoded_values:
                                self._remember_decoded(detection)
                            for decoded in decoded_values:
                                self._record_scan(decoded, detection, decode_ms)
                    decode_wall_ms = (time.perf_counter() - decode_started) * 1000

                self._schedule_encode(frame, detections)
                now = time.monotonic()
                compute_ms = (time.perf_counter() - started) * 1000
                total_ms = (time.perf_counter() - loop_started) * 1000
                with self.frame_condition:
                    self.frame_sequence += 1
                    self.frame_times.append(now)
                    self.latencies.append(total_ms)
                    self.compute_times.append(compute_ms)
                    self.source_times.append(source_ms)
                    self.decoder_wall_times.append(decode_wall_ms)
                    self.decoder_cpu_times.append(decode_cpu_ms)
                    self.decoder_jobs.append(decode_count)
                    self.error = ""
            except Exception as error:
                with self.lock:
                    self.error = f"{type(error).__name__}: {error}"
                time.sleep(0.1)

    def status(self) -> dict[str, Any]:
        with self.lock:
            source = self.source
            detections = list(self.latest_detections)
            shape = self.latest_raw.shape[:2] if self.latest_raw is not None else None
            frame_times = list(self.frame_times)
            latencies = list(self.latencies)
            compute_times = list(self.compute_times)
            source_times = list(self.source_times)
            decoder_wall_times = list(self.decoder_wall_times)
            decoder_cpu_times = list(self.decoder_cpu_times)
            decoder_jobs = list(self.decoder_jobs)
            encoder_times = list(self.encoder_times)
            jpeg_times = list(self.jpeg_times)
            encoder_pending = self.encoder_pending
            encoder_skips = self.encoder_skips
            scans = [asdict(scan) for scan in list(self.scans)[:20]]
            selected = asdict(self.selected) if self.selected else None
            decoded_tracks = [
                box for box, expiry in self.decoded_tracks if expiry >= self.frame_sequence
            ]
            state = {
                "paused": self.paused, "error": self.error, "frames": self.frame_sequence,
            }
        fps = 0.0
        if len(frame_times) > 1 and frame_times[-1] > frame_times[0]:
            fps = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
        encoder_fps = 0.0
        if len(jpeg_times) > 1 and jpeg_times[-1] > jpeg_times[0]:
            encoder_fps = (len(jpeg_times) - 1) / (jpeg_times[-1] - jpeg_times[0])
        boxes = []
        if shape:
            height, width = shape
            for detection in detections:
                x1, y1, x2, y2 = detection.box
                boxes.append({
                    "left": x1 / width, "top": y1 / height,
                    "width": (x2 - x1) / width, "height": (y2 - y1) / height,
                    "score": detection.score,
                    "decoded": any(box_iou(detection.box, box) >= 0.5 for box in decoded_tracks),
                })
        return {
            "version": 1,
            "captured_utc": utc_now(),
            "uptime_seconds": time.monotonic() - self.started,
            **state,
            "source": {
                "type": source.source_type if source else "starting",
                "label": source.label if source else "Starting…",
                "isp_active": bool(source and source.isp_active),
            },
            "detections": boxes,
            "selected": selected,
            "scans": scans,
            "performance": {
                "fps": fps,
                "end_to_end_ms": float(np.mean(latencies[-30:])) if latencies else 0.0,
                "compute_ms": float(np.mean(compute_times[-30:])) if compute_times else 0.0,
                "source_ms": float(np.mean(source_times[-30:])) if source_times else 0.0,
                "detector_ms": self.detector.last_ms,
                "decoder_ms": float(np.mean(decoder_wall_times[-30:])) if decoder_wall_times else 0.0,
                "decoder_cpu_ms": float(np.mean(decoder_cpu_times[-30:])) if decoder_cpu_times else 0.0,
                "decoder_rois_per_frame": float(np.mean(decoder_jobs[-30:])) if decoder_jobs else 0.0,
                "encoder_ms": float(np.mean(encoder_times[-30:])) if encoder_times else 0.0,
                "encoder_fps": encoder_fps,
                "encoder_async": True,
                "encoder_pending": encoder_pending,
                "encoder_skips": encoder_skips,
                "decode_interval": self.args.decode_interval,
                "decode_retry_frames": self.args.decode_retry_frames,
                "decoder_workers": self.args.decoder_workers,
                "stream_fps_limit": self.args.stream_fps,
            },
            "acceleration": {
                "active": self.detector.invocations > 0,
                "label": "TIDL · C7x/MMA",
                "cpu_fallback": 0,
                "cpu_fallback_policy": "forbidden by ONNX session and single-provider assertion",
                "detector": {
                    "runtime": "ONNX Runtime", "provider": "TIDLExecutionProvider",
                    "registered_providers": self.detector.registered_providers,
                    "core": self.detector.core, "nodes": GRAPH_NODES,
                    "invocations": self.detector.invocations,
                },
                "decoder": {
                    "runtime": "ZXing-C++", "version": self.decoder.version,
                    "processor": "A53 CPU, TIDL-localized crops only",
                    "invocations": self.decoder.invocations,
                    "full_frame_cpu_localization": False,
                },
                "remoteprocs": remoteproc_evidence(),
            },
            "memory": memory_status(),
            "system": {"cpu_percent": self.cpu_sampler.percent()},
            "formats": self.args.formats or "All ZXing 2.2 formats",
        }

    def capture_proof(self) -> dict[str, str]:
        with self.lock:
            if self.latest_raw is None:
                raise RuntimeError("no frame is available")
            frame = self.latest_raw.copy()
            detections = list(self.latest_detections)
        for detection in detections:
            x1, y1, x2, y2 = detection.box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (108, 241, 164), 3)
            cv2.putText(
                frame, f"CODE {detection.score * 100:.1f}%", (x1 + 4, max(24, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (108, 241, 164), 2, cv2.LINE_AA,
            )
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        image_path = self.proof_dir / f"omnicode-{stamp}.jpg"
        json_path = self.proof_dir / f"omnicode-{stamp}.json"
        if not cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94]):
            raise RuntimeError("proof image write failed")
        result = self.status()
        result["proof_image"] = str(image_path)
        result["proof_image_sha256"] = sha256(image_path)
        json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"image": str(image_path), "json": str(json_path)}


class OmniCodeHandler(BaseHTTPRequestHandler):
    server_version = "OmniCode/1"
    app: OmniCode
    static_dir: Path

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"HTTP {self.address_string()} {format_string % args}")

    def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
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
            self._json(self.app.status())
            return
        if parsed.path == "/stream.mjpg":
            self._stream()
            return
        if parsed.path == "/frame.jpg":
            with self.app.lock:
                frame = self.app.latest_jpeg
            if not frame:
                self.send_error(HTTPStatus.SERVICE_UNAVAILABLE.value, "No frame available")
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
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if target.name == "index.html" else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        sequence = -1
        try:
            while not self.app.stop_event.is_set():
                with self.app.frame_condition:
                    self.app.frame_condition.wait_for(
                        lambda: self.app.jpeg_sequence != sequence, timeout=2
                    )
                    sequence = self.app.jpeg_sequence
                    frame = self.app.latest_jpeg
                if not frame:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame + b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/source":
                body = self._read_json()
                self.app.request_source(str(body.get("type", "")), str(body.get("path", "")))
                self._json({"ok": True}, HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/control":
                action = str(self._read_json().get("action", ""))
                if action == "pause":
                    with self.app.lock:
                        self.app.paused = True
                    result: Any = {"ok": True, "paused": True}
                elif action == "resume":
                    with self.app.lock:
                        self.app.paused = False
                    result = {"ok": True, "paused": False}
                elif action == "clear":
                    self.app.clear()
                    result = {"ok": True}
                elif action == "capture":
                    result = {"ok": True, "proof": self.app.capture_proof()}
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
        if length <= 0 or length > self.app.args.max_upload_bytes:
            raise ValueError("media is empty or exceeds upload limit")
        raw_name = parse_qs(parsed.query).get("filename", [""])[0]
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_name).name)
        if not name or Path(name).suffix.casefold() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"unsupported media filename: {raw_name}")
        target = self.app.upload_dir / f"{int(time.time())}-{name}"
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
        self.app.request_source("media", str(target))
        self._json({"ok": True, "path": str(target)}, HTTPStatus.CREATED)


def parse_args() -> argparse.Namespace:
    demo_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("camera", "media"), default="media")
    parser.add_argument("--media", default=str(demo_dir / "assets" / "omnicode-sample.mp4"))
    parser.add_argument("--model-dir", default=f"/opt/ti-edgeai-omnicode/models/{MODEL_NAME}")
    parser.add_argument("--decoder-library", default="/usr/lib/aarch64-linux-gnu/libomnicode-decoder.so.1")
    parser.add_argument("--formats", default="")
    parser.add_argument("--core", type=int, choices=(1, 2), default=1)
    parser.add_argument("--detector-threshold", type=float, default=0.30)
    parser.add_argument("--crop-margin", type=float, default=0.18)
    parser.add_argument("--min-decode-pixels", type=int, default=240)
    parser.add_argument("--decode-interval", type=int, default=3)
    parser.add_argument("--decode-retry-frames", type=int, default=12)
    parser.add_argument("--decoder-workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--ui-dir", default=str(demo_dir / "ui" / "dist"))
    parser.add_argument("--output-dir", default="/var/lib/ti-edgeai-omnicode")
    parser.add_argument("--stream-width", type=int, default=960)
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument("--stream-fps", type=float, default=15)
    parser.add_argument("--image-fps", type=float, default=5)
    parser.add_argument("--max-upload-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-loop", dest="loop", action="store_false")
    args = parser.parse_args()
    if not 0 < args.detector_threshold <= 1 or not 0 <= args.crop_margin <= 1:
        parser.error("threshold or crop margin is invalid")
    if (args.min_decode_pixels < 32 or args.decode_interval < 1 or args.decode_retry_frames < 1
            or not 1 <= args.jpeg_quality <= 100 or args.image_fps <= 0
            or args.stream_fps <= 0):
        parser.error("decode size/interval, JPEG quality, image FPS, or stream FPS is invalid")
    if not Path(args.ui_dir).is_dir():
        parser.error(f"built UI is missing: {args.ui_dir}")
    return args


def main() -> int:
    args = parse_args()
    app = OmniCode(args)
    OmniCodeHandler.app = app
    OmniCodeHandler.static_dir = Path(args.ui_dir).resolve()
    server = ThreadingHTTPServer((args.host, args.port), OmniCodeHandler)

    def request_stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    app.start()
    print(f"OmniCode listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        app.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
