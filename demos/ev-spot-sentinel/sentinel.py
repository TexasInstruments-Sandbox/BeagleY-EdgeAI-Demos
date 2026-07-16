#!/usr/bin/python3
"""EV Spot Sentinel: local parking occupancy, ALPR, and dwell tracking for J722S."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass, field
import datetime as dt
import glob
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import signal
import sqlite3
import subprocess
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np
import onnxruntime as ort


VEHICLE_MODEL_NAME = "ONR-OD-8200-yolox-nano-lite-mmdet-coco-416x416"
VEHICLE_MODEL_FILE = "yolox_nano_lite_416x416_20220214_model.onnx"
VEHICLE_LABELS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PLATE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
PLATE_REGIONS = (
    "Albania", "Andorra", "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan",
    "Bahrain", "Belarus", "Belgium", "Bosnia and Herzegovina", "Brazil", "Bulgaria",
    "Cambodia", "Canada", "Croatia", "Cyprus", "Czech Republic", "Denmark", "Estonia",
    "Finland", "France", "Georgia", "Germany", "Gibraltar", "Greece", "Guernsey", "Hungary",
    "Iceland", "Indonesia", "Ireland", "Israel", "Italy", "Latvia", "Liechtenstein",
    "Lithuania", "Luxembourg", "Malaysia", "Malta", "Mexico", "Moldova", "Monaco",
    "Montenegro", "Netherlands", "New Zealand", "North Macedonia", "Norway", "Poland",
    "Portugal", "Qatar", "Romania", "San Marino", "Serbia", "Singapore", "Slovakia",
    "Slovenia", "Spain", "Sweden", "Switzerland", "Thailand", "Turkey", "United States",
    "Ukraine", "United Kingdom", "Vietnam", "Unknown",
)
VIDEO_EXTENSIONS = {".avi", ".h264", ".h265", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
DEFAULT_SPOTS = (
    {"id": "EV-A", "name": "EV · A", "polygon": [[0.02, 0.46], [0.32, 0.46], [0.34, 0.98], [0.00, 0.98]]},
    {"id": "EV-B", "name": "EV · B", "polygon": [[0.34, 0.46], [0.66, 0.46], [0.68, 0.98], [0.32, 0.98]]},
    {"id": "EV-C", "name": "EV · C", "polygon": [[0.68, 0.46], [0.98, 0.46], [1.00, 0.98], [0.66, 0.98]]},
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_utc(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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


def remoteproc_evidence() -> list[dict[str, str]]:
    results = []
    for directory in sorted(glob.glob("/sys/class/remoteproc/remoteproc*")):
        try:
            firmware = (Path(directory) / "firmware").read_text(encoding="ascii").strip()
            state = (Path(directory) / "state").read_text(encoding="ascii").strip()
        except OSError:
            continue
        if "c71" in firmware or "main-r5" in firmware:
            results.append({"firmware": firmware, "state": state})
    return results


class CpuSampler:
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = self._read()

    @staticmethod
    def _read() -> tuple[int, int]:
        values = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        return sum(values), values[3] + (values[4] if len(values) > 4 else 0)

    def percent(self) -> float:
        with self.lock:
            current = self._read()
            total = current[0] - self.previous[0]
            idle = current[1] - self.previous[1]
            self.previous = current
        return clamp((total - idle) * 100.0 / total, 0.0, 100.0) if total > 0 else 0.0


@dataclass
class Vehicle:
    box: tuple[int, int, int, int]
    score: float
    label: str
    inference_ms: float


@dataclass
class PlateRead:
    box: tuple[int, int, int, int]
    text: str
    score: float
    detector_score: float
    region: str
    inference_ms: float


@dataclass
class SpotRuntime:
    identifier: str
    name: str
    polygon: list[list[float]]
    occupied: bool = False
    hit_frames: int = 0
    missed_frames: int = 0
    session_id: int | None = None
    started_utc: str | None = None
    vehicle: Vehicle | None = None
    plate: PlateRead | None = None
    plate_votes: deque[tuple[str, float, str, tuple[int, int, int, int]]] = field(
        default_factory=lambda: deque(maxlen=8)
    )
    alpr_attempts: int = 0
    alpr_next_frame: int = 0


class VehicleDetector:
    """TI YOLOX-Nano with its complete 283-node graph locked to TIDL."""

    def __init__(self, model_dir: Path, core: int, threshold: float):
        self.model_dir = model_dir.resolve()
        self.model = self.model_dir / "model" / VEHICLE_MODEL_FILE
        self.artifacts = self.model_dir / "artifacts"
        self.threshold = threshold
        info_path = self.artifacts / "tidl-compiler-info.json"
        required = (
            self.model, info_path, self.artifacts / "allowedNode.txt",
            self.artifacts / "onnxrtMetaData.txt", self.artifacts / "subgraph_0_tidl_net.bin",
            self.artifacts / "subgraph_0_tidl_io_1.bin",
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"vehicle detector assets are missing: {missing}")
        self.info = json.loads(info_path.read_text(encoding="utf-8"))
        if int(self.info.get("graph_nodes_offloaded", 0)) != 283:
            raise RuntimeError("vehicle detector is not one complete 283-node TIDL graph")
        for name, expected in self.info.get("artifact_sha256", {}).items():
            path = self.artifacts / name
            if not path.is_file() or sha256(path) != expected:
                raise RuntimeError(f"vehicle detector artifact hash mismatch: {name}")
        if "TIDLExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError(f"TIDLExecutionProvider unavailable: {ort.get_available_providers()}")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = 1
        options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
        self.session = ort.InferenceSession(
            str(self.model), sess_options=options, providers=["TIDLExecutionProvider"],
            provider_options=[{
                "artifacts_folder": str(self.artifacts), "core_number": str(core), "debug_level": "0",
            }],
        )
        self.session.disable_fallback()
        if not self.session.get_providers() or self.session.get_providers()[0] != "TIDLExecutionProvider":
            raise RuntimeError(f"unexpected detector providers: {self.session.get_providers()}")
        tensor = self.session.get_inputs()[0]
        if tuple(tensor.shape) != (1, 3, 416, 416) or tensor.type != "tensor(uint8)":
            raise RuntimeError(f"unexpected detector input: {tensor.name} {tensor.shape} {tensor.type}")
        self.input_name = tensor.name
        self.output_names = [item.name for item in self.session.get_outputs()]
        if set(self.output_names) != {"dets", "labels"}:
            raise RuntimeError(f"unexpected detector outputs: {self.output_names}")
        self.core = core
        self.invocations = 0
        self.last_ms = 0.0

    @staticmethod
    def _preprocess(frame: np.ndarray) -> tuple[np.ndarray, float]:
        height, width = frame.shape[:2]
        scale = min(416 / width, 416 / height)
        resized = cv2.resize(frame, (round(width * scale), round(height * scale)))
        canvas = np.full((416, 416, 3), 114, dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None]), scale

    def detect(self, frame: np.ndarray) -> list[Vehicle]:
        tensor, scale = self._preprocess(frame)
        started = time.perf_counter()
        values = self.session.run(None, {self.input_name: tensor})
        self.last_ms = (time.perf_counter() - started) * 1000.0
        self.invocations += 1
        outputs = dict(zip(self.output_names, values))
        boxes = np.asarray(outputs["dets"]).reshape(-1, 5)
        labels = np.asarray(outputs["labels"]).reshape(-1)
        height, width = frame.shape[:2]
        vehicles = []
        for box, raw_label in zip(boxes, labels):
            label = VEHICLE_LABELS.get(int(raw_label))
            score = float(box[4])
            if label is None or score < self.threshold:
                continue
            x1 = int(clamp(float(box[0]) / scale, 0, width - 1))
            y1 = int(clamp(float(box[1]) / scale, 0, height - 1))
            x2 = int(clamp(float(box[2]) / scale, x1 + 1, width))
            y2 = int(clamp(float(box[3]) / scale, y1 + 1, height))
            vehicles.append(Vehicle((x1, y1, x2, y2), score, label, self.last_ms))
        return vehicles


class PlateReader:
    """Pinned global plate detector/OCR on ARM CPU, explicitly separate from TIDL."""

    def __init__(self, detector: Path, ocr: Path, threshold: float):
        for path in (detector, ocr):
            if not path.is_file():
                raise RuntimeError(f"plate model is missing: {path}")
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.detector = ort.InferenceSession(
            str(detector), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.ocr = ort.InferenceSession(str(ocr), sess_options=options, providers=["CPUExecutionProvider"])
        if self.detector.get_providers() != ["CPUExecutionProvider"] or self.ocr.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("plate sessions are not pinned to the declared CPU provider")
        if tuple(self.detector.get_inputs()[0].shape) != (1, 3, 384, 384):
            raise RuntimeError("unexpected plate detector input")
        ocr_shape = tuple(self.ocr.get_inputs()[0].shape[1:])
        if ocr_shape != (64, 128, 3):
            raise RuntimeError(f"unexpected plate OCR input: {ocr_shape}")
        self.threshold = threshold
        self.invocations = 0
        self.last_ms = 0.0

    @staticmethod
    def _letterbox(image: np.ndarray) -> tuple[np.ndarray, float, float, float]:
        height, width = image.shape[:2]
        ratio = min(384 / height, 384 / width)
        new_width, new_height = round(width * ratio), round(height * ratio)
        resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
        dw, dh = (384 - new_width) / 2, (384 - new_height) / 2
        padded = cv2.copyMakeBorder(
            resized, round(dh - 0.1), round(dh + 0.1), round(dw - 0.1), round(dw + 0.1),
            cv2.BORDER_CONSTANT, value=(114, 114, 114),
        )
        tensor = padded.transpose((2, 0, 1))[::-1][None].astype(np.float32) / 255.0
        return np.ascontiguousarray(tensor), ratio, dw, dh

    def read(self, frame: np.ndarray, vehicle: Vehicle) -> PlateRead | None:
        x1, y1, x2, y2 = vehicle.box
        margin_x = max(4, int((x2 - x1) * 0.05))
        margin_y = max(4, int((y2 - y1) * 0.05))
        left, top = max(0, x1 - margin_x), max(0, y1 - margin_y)
        right, bottom = min(frame.shape[1], x2 + margin_x), min(frame.shape[0], y2 + margin_y)
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return None
        tensor, ratio, dw, dh = self._letterbox(crop)
        started = time.perf_counter()
        rows = np.asarray(self.detector.run(None, {"images": tensor})[0]).reshape(-1, 7)
        candidates = [row for row in rows if float(row[6]) >= self.threshold]
        if not candidates:
            self.last_ms = (time.perf_counter() - started) * 1000.0
            self.invocations += 1
            return None
        row = max(candidates, key=lambda item: float(item[6]))
        px1 = int(clamp((float(row[1]) - dw) / ratio, 0, crop.shape[1] - 1))
        py1 = int(clamp((float(row[2]) - dh) / ratio, 0, crop.shape[0] - 1))
        px2 = int(clamp((float(row[3]) - dw) / ratio, px1 + 1, crop.shape[1]))
        py2 = int(clamp((float(row[4]) - dh) / ratio, py1 + 1, crop.shape[0]))
        plate_crop = crop[py1:py2, px1:px2]
        if plate_crop.size == 0:
            return None
        rgb = cv2.cvtColor(cv2.resize(plate_crop, (128, 64)), cv2.COLOR_BGR2RGB)[None].astype(np.uint8)
        plate_output, region_output = self.ocr.run(None, {"input": rgb})
        logits = np.asarray(plate_output)[0]
        indices = np.argmax(logits, axis=-1)
        characters = [PLATE_ALPHABET[int(index)] for index in indices]
        text = re.sub(r"[^A-Z0-9]", "", "".join(characters).rstrip("_"))
        character_scores = np.max(logits, axis=-1)
        used_scores = [float(score) for char, score in zip(characters, character_scores) if char != "_"]
        ocr_score = float(np.mean(used_scores)) if used_scores else 0.0
        detector_score = float(row[6])
        score = float((detector_score * ocr_score) ** 0.5)
        region_index = int(np.argmax(region_output[0]))
        region = PLATE_REGIONS[region_index] if region_index < len(PLATE_REGIONS) else "Unknown"
        self.last_ms = (time.perf_counter() - started) * 1000.0
        self.invocations += 1
        if len(text) < 4:
            return None
        return PlateRead(
            (left + px1, top + py1, left + px2, top + py2), text, score,
            detector_score, region, self.last_ms,
        )


class SessionStore:
    def __init__(self, path: Path, retention_days: int):
        self.path = path
        self.lock = threading.Lock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        # This board's writable root is NFSv4.2. WAL uses a shared-memory file and
        # is not safe on network filesystems, so keep the rollback journal local
        # to each transaction and use SQLite's normal POSIX locking path.
        self.connection.execute("PRAGMA journal_mode=DELETE")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY, spot_id TEXT NOT NULL, started_utc TEXT NOT NULL,
                ended_utc TEXT, duration_seconds REAL, plate TEXT, plate_confidence REAL,
                region TEXT, vehicle_type TEXT, overstay INTEGER NOT NULL DEFAULT 0
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS sessions_plate ON sessions(plate)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS sessions_started ON sessions(started_utc)")
        now = dt.datetime.now(dt.timezone.utc)
        with self.lock:
            open_rows = self.connection.execute(
                "SELECT id, started_utc FROM sessions WHERE ended_utc IS NULL"
            ).fetchall()
            for row in open_rows:
                duration = max(0.0, (now - parse_utc(row["started_utc"])).total_seconds())
                self.connection.execute(
                    "UPDATE sessions SET ended_utc=?, duration_seconds=? WHERE id=?",
                    (now.isoformat(), duration, row["id"]),
                )
            cutoff = (now - dt.timedelta(days=retention_days)).isoformat()
            self.connection.execute(
                "DELETE FROM sessions WHERE ended_utc IS NOT NULL AND ended_utc < ?", (cutoff,)
            )
            self.connection.commit()

    def start(self, spot: SpotRuntime, vehicle: Vehicle) -> int:
        with self.lock:
            cursor = self.connection.execute(
                "INSERT INTO sessions(spot_id,started_utc,vehicle_type) VALUES(?,?,?)",
                (spot.identifier, spot.started_utc, vehicle.label),
            )
            self.connection.commit()
            return int(cursor.lastrowid)

    def identify(self, session_id: int, plate: PlateRead) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE sessions SET plate=?,plate_confidence=?,region=? WHERE id=?",
                (plate.text, plate.score, plate.region, session_id),
            )
            self.connection.commit()

    def end(self, spot: SpotRuntime, duration: float, overstay: bool) -> None:
        if spot.session_id is None:
            return
        with self.lock:
            self.connection.execute(
                "UPDATE sessions SET ended_utc=?,duration_seconds=?,overstay=? WHERE id=?",
                (utc_now(), duration, int(overstay), spot.session_id),
            )
            self.connection.commit()

    def recent(self, limit: int = 12) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM sessions WHERE ended_utc IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def leaderboard(self, limit: int = 8) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                """SELECT plate,COUNT(*) AS visits,SUM(duration_seconds) AS total_seconds,
                          MAX(duration_seconds) AS longest_seconds,MAX(ended_utc) AS last_seen_utc
                   FROM sessions WHERE plate IS NOT NULL AND ended_utc IS NOT NULL
                   GROUP BY plate ORDER BY total_seconds DESC LIMIT ?""", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


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
            raise RuntimeError("IMX219/VPAC capture requires root")
        for media_format in self.MEDIA_FORMATS:
            subprocess.run(
                ["media-ctl", "-d", "/dev/media0", "-V", media_format], check=True,
                stdout=subprocess.DEVNULL,
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
            raise RuntimeError("could not start the IMX219 VPAC ISP pipeline")

    def read(self) -> tuple[bool, np.ndarray | None]:
        return self.capture.read()

    def close(self) -> None:
        self.capture.release()


class Sentinel:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.output_dir = Path(args.output_dir).resolve()
        self.upload_dir = self.output_dir / "uploads"
        self.proof_dir = self.output_dir / "proof"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(exist_ok=True)
        self.proof_dir.mkdir(exist_ok=True)
        self.store = SessionStore(self.output_dir / "sessions.sqlite3", args.retention_days)
        self.detector = VehicleDetector(Path(args.vehicle_model_dir), args.tidl_core, args.vehicle_threshold)
        self.plate_reader = PlateReader(
            Path(args.plate_detector), Path(args.plate_ocr), args.plate_detector_threshold
        )
        self.spots = self._load_spots()
        self.lock = threading.RLock()
        self.frame_condition = threading.Condition(self.lock)
        self.stop_event = threading.Event()
        self.source: FrameSource | None = None
        self.source_request: tuple[str, str] | None = (args.source, args.video)
        self.paused = False
        self.latest_raw: np.ndarray | None = None
        self.latest_jpeg = b""
        self.vehicles: list[Vehicle] = []
        self.frame_sequence = 0
        self.frame_times: deque[float] = deque(maxlen=60)
        self.latencies: deque[float] = deque(maxlen=60)
        self.error = ""
        self.started = time.monotonic()
        self.cpu_sampler = CpuSampler()
        self.worker: threading.Thread | None = None
        self.alpr_queue: queue.Queue[tuple[np.ndarray, str, int | None, Vehicle]] = queue.Queue(maxsize=2)
        self.alpr_pending: set[str] = set()
        self.alpr_worker: threading.Thread | None = None

    def _load_spots(self) -> list[SpotRuntime]:
        path = self.output_dir / "spots.json"
        values = json.loads(path.read_text()) if path.is_file() else list(DEFAULT_SPOTS)
        return [SpotRuntime(str(item["id"]), str(item["name"]), item["polygon"]) for item in values]

    def save_spots(self, values: list[dict[str, Any]]) -> None:
        validated = []
        identifiers = set()
        if not 1 <= len(values) <= 8:
            raise ValueError("configure between one and eight spots")
        for item in values:
            identifier = re.sub(r"[^A-Za-z0-9_-]", "", str(item.get("id", "")))[:24]
            name = str(item.get("name", identifier)).strip()[:32]
            polygon = item.get("polygon")
            if not identifier or identifier in identifiers or not isinstance(polygon, list) or len(polygon) < 3:
                raise ValueError("each spot needs a unique ID and at least three polygon vertices")
            points = []
            for point in polygon:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError("polygon points must be [x,y]")
                points.append([clamp(float(point[0]), 0, 1), clamp(float(point[1]), 0, 1)])
            identifiers.add(identifier)
            validated.append({"id": identifier, "name": name, "polygon": points})
        with self.lock:
            if any(spot.occupied for spot in self.spots) and not self.paused:
                raise ValueError("pause inference before changing occupied polygons")
            if any(spot.occupied for spot in self.spots):
                self._reset_runtime(end_sessions=True)
            self.spots = [SpotRuntime(item["id"], item["name"], item["polygon"]) for item in validated]
            temporary = self.output_dir / "spots.json.tmp"
            temporary.write_text(json.dumps(validated, indent=2) + "\n")
            os.replace(temporary, self.output_dir / "spots.json")

    def start(self) -> None:
        self.alpr_worker = threading.Thread(target=self._run_alpr, name="sentinel-alpr", daemon=True)
        self.alpr_worker.start()
        self.worker = threading.Thread(target=self._run, name="sentinel-inference", daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=10)
        if self.alpr_worker:
            self.alpr_worker.join(timeout=10)
        with self.lock:
            if self.source:
                self.source.close()
                self.source = None
            for spot in self.spots:
                if spot.occupied:
                    self.store.end(spot, self._dwell(spot), self._dwell(spot) >= self.args.overstay_seconds)

    def request_source(self, source_type: str, path: str = "") -> None:
        if source_type not in {"camera", "video"}:
            raise ValueError("source type must be camera or video")
        if source_type == "video" and not path:
            raise ValueError("video source requires a path")
        with self.lock:
            self.source_request = (source_type, path)

    def _change_source(self, source_type: str, path: str) -> None:
        with self.lock:
            if source_type == "camera" and self.source and self.source.source_type == "camera":
                return
            previous = self.source
            self.source = None
        # OpenCV's GStreamer backend can tear down newly-created pipelines when
        # an older capture is released. Dispose the previous capture first.
        if previous:
            previous.close()
        candidate: FrameSource = IMX219Source() if source_type == "camera" else VideoSource(Path(path), self.args.loop)
        with self.lock:
            self.source = candidate
            self.error = ""
            self._reset_runtime(end_sessions=True)

    def _reset_runtime(self, end_sessions: bool) -> None:
        for spot in self.spots:
            if end_sessions and spot.occupied:
                duration = self._dwell(spot)
                self.store.end(spot, duration, duration >= self.args.overstay_seconds)
            spot.occupied = False
            spot.hit_frames = spot.missed_frames = 0
            spot.session_id = None
            spot.started_utc = None
            spot.vehicle = None
            spot.plate = None
            spot.plate_votes.clear()
            spot.alpr_attempts = 0
            spot.alpr_next_frame = 0
        self.latest_raw = None
        self.latest_jpeg = b""
        self.vehicles = []
        self.frame_times.clear()
        self.latencies.clear()

    @staticmethod
    def _point_in_spot(vehicle: Vehicle, spot: SpotRuntime, width: int, height: int) -> bool:
        x1, _y1, x2, y2 = vehicle.box
        point = ((x1 + x2) / (2 * width), y2 / height)
        contour = np.asarray(spot.polygon, dtype=np.float32)
        return cv2.pointPolygonTest(contour, point, False) >= 0

    def _dwell(self, spot: SpotRuntime) -> float:
        if not spot.started_utc:
            return 0.0
        return max(0.0, (dt.datetime.now(dt.timezone.utc) - parse_utc(spot.started_utc)).total_seconds())

    def _update_spots(self, vehicles: list[Vehicle], shape: tuple[int, int]) -> dict[str, Vehicle]:
        height, width = shape
        assigned: dict[str, Vehicle] = {}
        for vehicle in sorted(vehicles, key=lambda item: item.score, reverse=True):
            for spot in self.spots:
                if spot.identifier not in assigned and self._point_in_spot(vehicle, spot, width, height):
                    assigned[spot.identifier] = vehicle
                    break
        for spot in self.spots:
            vehicle = assigned.get(spot.identifier)
            if vehicle:
                spot.hit_frames += 1
                spot.missed_frames = 0
                spot.vehicle = vehicle
                if not spot.occupied and spot.hit_frames >= self.args.occupancy_frames:
                    spot.occupied = True
                    spot.started_utc = utc_now()
                    spot.plate = None
                    spot.plate_votes.clear()
                    spot.alpr_attempts = 0
                    spot.alpr_next_frame = self.frame_sequence
                    spot.session_id = self.store.start(spot, vehicle)
            else:
                spot.hit_frames = 0
                spot.missed_frames += 1
                if spot.occupied and spot.missed_frames >= self.args.clear_frames:
                    duration = self._dwell(spot)
                    self.store.end(spot, duration, duration >= self.args.overstay_seconds)
                    spot.occupied = False
                    spot.session_id = None
                    spot.started_utc = None
                    spot.vehicle = None
                    spot.plate = None
                    spot.plate_votes.clear()
                    spot.alpr_attempts = 0
                    spot.alpr_next_frame = 0
        return assigned

    def _update_plate(self, spot: SpotRuntime, read: PlateRead) -> None:
        spot.plate_votes.append((read.text, read.score, read.region, read.box))
        counts = Counter(item[0] for item in spot.plate_votes)
        text, count = counts.most_common(1)[0]
        matches = [item for item in spot.plate_votes if item[0] == text]
        mean_score = float(np.mean([item[1] for item in matches]))
        if count < self.args.plate_votes or mean_score < self.args.plate_confidence:
            return
        best = max(matches, key=lambda item: item[1])
        confirmed = PlateRead(best[3], text, mean_score, read.detector_score, best[2], read.inference_ms)
        if spot.plate is None or spot.plate.text != confirmed.text:
            spot.plate = confirmed
            if spot.session_id is not None:
                self.store.identify(spot.session_id, confirmed)

    def _run_alpr(self) -> None:
        """Keep slow global OCR off the real-time TIDL/streaming path."""
        while not self.stop_event.is_set():
            try:
                frame, spot_id, session_id, vehicle = self.alpr_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                read = self.plate_reader.read(frame, vehicle)
                with self.lock:
                    spot = next((item for item in self.spots if item.identifier == spot_id), None)
                    if read and spot and spot.occupied and spot.session_id == session_id and spot.plate is None:
                        self._update_plate(spot, read)
            except Exception as error:
                with self.lock:
                    self.error = f"ALPR {type(error).__name__}: {error}"
            finally:
                with self.lock:
                    self.alpr_pending.discard(spot_id)
                self.alpr_queue.task_done()

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
            if paused or source is None:
                time.sleep(0.05)
                continue
            ok, frame = source.read()
            if not ok or frame is None:
                with self.lock:
                    self.error = f"Source stopped: {source.label}"
                time.sleep(0.2)
                continue
            started = time.perf_counter()
            try:
                vehicles = self.detector.detect(frame)
                with self.lock:
                    assigned = self._update_spots(vehicles, frame.shape[:2])
                if self.frame_sequence % self.args.alpr_interval == 0:
                    with self.lock:
                        candidates = sorted([
                            (spot, assigned[spot.identifier]) for spot in self.spots
                            if spot.occupied and spot.plate is None and spot.identifier in assigned
                            and spot.identifier not in self.alpr_pending
                            and self.frame_sequence >= spot.alpr_next_frame
                        ], key=lambda item: (item[0].alpr_attempts, item[0].alpr_next_frame, item[0].identifier))[
                            : self.args.alpr_max_vehicles
                        ]
                    for spot, vehicle in candidates:
                        with self.lock:
                            self.alpr_pending.add(spot.identifier)
                            spot.alpr_attempts += 1
                            backoff = min(8, 2 ** max(0, spot.alpr_attempts - 1))
                            spot.alpr_next_frame = self.frame_sequence + self.args.alpr_interval * backoff
                        try:
                            self.alpr_queue.put_nowait((frame.copy(), spot.identifier, spot.session_id, vehicle))
                        except queue.Full:
                            with self.lock:
                                self.alpr_pending.discard(spot.identifier)
                            break
                encode_frame = frame
                if frame.shape[1] > self.args.stream_width:
                    scale = self.args.stream_width / frame.shape[1]
                    encode_frame = cv2.resize(frame, (self.args.stream_width, round(frame.shape[0] * scale)))
                encoded_ok, encoded = cv2.imencode(
                    ".jpg", encode_frame, [cv2.IMWRITE_JPEG_QUALITY, self.args.jpeg_quality]
                )
                if not encoded_ok:
                    raise RuntimeError("JPEG encoding failed")
                now = time.monotonic()
                with self.frame_condition:
                    self.latest_raw = frame.copy()
                    self.latest_jpeg = encoded.tobytes()
                    self.vehicles = vehicles
                    self.frame_sequence += 1
                    self.frame_times.append(now)
                    self.latencies.append((time.perf_counter() - started) * 1000.0)
                    self.error = ""
                    self.frame_condition.notify_all()
            except Exception as error:
                with self.lock:
                    self.error = f"{type(error).__name__}: {error}"
                time.sleep(0.1)

    @staticmethod
    def _box(box: tuple[int, int, int, int] | None, shape: tuple[int, int] | None) -> dict[str, float] | None:
        if box is None or shape is None:
            return None
        height, width = shape
        x1, y1, x2, y2 = box
        return {"left": x1 / width, "top": y1 / height, "width": (x2 - x1) / width, "height": (y2 - y1) / height}

    def status(self) -> dict[str, Any]:
        with self.lock:
            source = self.source
            frame_shape = self.latest_raw.shape[:2] if self.latest_raw is not None else None
            frame_times = list(self.frame_times)
            latencies = list(self.latencies)
            spots = []
            active_by_plate: dict[str, dict[str, Any]] = {}
            active_sessions = []
            for spot in self.spots:
                dwell = self._dwell(spot)
                overstay = spot.occupied and dwell >= self.args.overstay_seconds
                value = {
                    "id": spot.identifier, "name": spot.name, "polygon": spot.polygon,
                    "occupied": spot.occupied, "state": "OVERSTAY" if overstay else ("OCCUPIED" if spot.occupied else "AVAILABLE"),
                    "dwell_seconds": dwell, "overstay": overstay,
                    "vehicle": None if not spot.vehicle else {
                        "label": spot.vehicle.label, "score": spot.vehicle.score,
                        "box": self._box(spot.vehicle.box, frame_shape),
                    },
                    "plate": None if not spot.plate else {
                        "text": spot.plate.text, "score": spot.plate.score, "region": spot.plate.region,
                        "box": self._box(spot.plate.box, frame_shape),
                    },
                }
                spots.append(value)
                if spot.occupied:
                    active_sessions.append({
                        "id": spot.session_id, "spot_id": spot.identifier, "started_utc": spot.started_utc,
                        "ended_utc": None, "duration_seconds": dwell,
                        "plate": spot.plate.text if spot.plate else None,
                        "plate_confidence": spot.plate.score if spot.plate else None,
                        "region": spot.plate.region if spot.plate else None,
                        "vehicle_type": spot.vehicle.label if spot.vehicle else None, "overstay": int(overstay),
                    })
                    if spot.plate:
                        active_by_plate[spot.plate.text] = {
                            "plate": spot.plate.text, "visits": 1, "total_seconds": dwell,
                            "longest_seconds": dwell, "last_seen_utc": utc_now(), "active": True,
                        }
            paused, error, sequence = self.paused, self.error, self.frame_sequence
        fps = 0.0
        if len(frame_times) > 1 and frame_times[-1] > frame_times[0]:
            fps = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
        memory = read_meminfo()
        recent = active_sessions + self.store.recent(max(0, 12 - len(active_sessions)))
        leaderboard = {item["plate"]: item for item in self.store.leaderboard()}
        for plate, active in active_by_plate.items():
            if plate in leaderboard:
                item = leaderboard[plate]
                item["visits"] += 1
                item["total_seconds"] = float(item["total_seconds"] or 0) + active["total_seconds"]
                item["longest_seconds"] = max(float(item["longest_seconds"] or 0), active["longest_seconds"])
                item["last_seen_utc"] = active["last_seen_utc"]
                item["active"] = True
            else:
                leaderboard[plate] = active
        ranked = sorted(leaderboard.values(), key=lambda item: float(item["total_seconds"] or 0), reverse=True)[:8]
        return {
            "version": 1, "captured_utc": utc_now(), "uptime_seconds": time.monotonic() - self.started,
            "paused": paused, "error": error,
            "source": {"type": source.source_type if source else "starting", "label": source.label if source else "Starting…", "isp_active": bool(source and source.isp_active)},
            "spots": spots, "recent_sessions": recent, "leaderboard": ranked,
            "policy": {"overstay_seconds": self.args.overstay_seconds, "retention_days": self.args.retention_days, "local_only": True, "human_review_required": True},
            "performance": {"fps": fps, "frames": sequence, "end_to_end_ms": float(np.mean(latencies[-30:])) if latencies else 0.0, "vehicle_inference_ms": self.detector.last_ms, "plate_inference_ms": self.plate_reader.last_ms},
            "acceleration": {
                "active": self.detector.invocations > 0, "label": "C7x/MMA ACTIVE", "cpu_fallback": 0,
                "vehicle": {"provider": "TIDLExecutionProvider", "core": self.detector.core, "nodes": 283, "invocations": self.detector.invocations, "cpu_fallback": False},
                "plate": {"provider": "CPUExecutionProvider", "reason": "global ALPR transformer is not a stable complete TIDL graph in PSDK 11.02", "invocations": self.plate_reader.invocations},
                "isp": {"active": bool(source and source.isp_active), "pipeline": "IMX219 CSI0 → VPAC VISS → NV12"},
                "remoteprocs": remoteproc_evidence(),
            },
            "memory": {"total_bytes": memory.get("MemTotal", 0), "available_bytes": memory.get("MemAvailable", 0), "used_bytes": memory.get("MemTotal", 0) - memory.get("MemAvailable", 0), "process_rss_bytes": process_rss_bytes()},
            "system": {"cpu_percent": self.cpu_sampler.percent()},
        }

    def capture_proof(self) -> dict[str, str]:
        with self.lock:
            if self.latest_raw is None:
                raise RuntimeError("no frame is available")
            frame = self.latest_raw.copy()
            spots = list(self.spots)
        height, width = frame.shape[:2]
        overlay = frame.copy()
        for spot in spots:
            points = np.asarray([[round(x * width), round(y * height)] for x, y in spot.polygon], np.int32)
            color = (0, 155, 255) if self._dwell(spot) >= self.args.overstay_seconds else ((62, 222, 174) if spot.occupied else (90, 170, 68))
            cv2.fillPoly(overlay, [points], color)
            cv2.polylines(frame, [points], True, color, 3)
            anchor = tuple(points[0])
            cv2.putText(frame, f"{spot.identifier} {('OVERSTAY' if self._dwell(spot) >= self.args.overstay_seconds else ('OCCUPIED' if spot.occupied else 'AVAILABLE'))}", (anchor[0] + 8, anchor[1] + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
            if spot.vehicle:
                x1, y1, x2, y2 = spot.vehicle.box
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            if spot.plate:
                x1, y1, x2, y2 = spot.plate.box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (250, 245, 235), 2)
                cv2.putText(frame, f"{spot.plate.text} {spot.plate.score * 100:.1f}%", (x1, max(26, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (250, 245, 235), 2, cv2.LINE_AA)
        frame = cv2.addWeighted(overlay, 0.16, frame, 0.84, 0)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        image_path = self.proof_dir / f"ev-spot-sentinel-{stamp}.jpg"
        json_path = self.proof_dir / f"ev-spot-sentinel-{stamp}.json"
        if not cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94]):
            raise RuntimeError("proof image write failed")
        result = self.status()
        result["proof_image"] = str(image_path)
        result["proof_image_sha256"] = sha256(image_path)
        json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return {"image": str(image_path), "json": str(json_path)}


class SentinelHandler(BaseHTTPRequestHandler):
    server_version = "EVSpotSentinel/1"
    sentinel: Sentinel
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
        if length <= 0 or length > 128 * 1024:
            raise ValueError("invalid JSON body length")
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._json(self.sentinel.status())
            return
        if parsed.path == "/stream.mjpg":
            self._stream()
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
            while not self.sentinel.stop_event.is_set():
                with self.sentinel.frame_condition:
                    self.sentinel.frame_condition.wait_for(lambda: self.sentinel.frame_sequence != sequence, timeout=2)
                    sequence = self.sentinel.frame_sequence
                    frame = self.sentinel.latest_jpeg
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
                self.sentinel.request_source(str(body.get("type", "")), str(body.get("path", "")))
                self._json({"ok": True}, HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/control":
                action = str(self._read_json().get("action", ""))
                if action in {"pause", "resume"}:
                    with self.sentinel.lock:
                        self.sentinel.paused = action == "pause"
                    result: Any = {"ok": True, "paused": action == "pause"}
                elif action == "capture":
                    result = {"ok": True, "proof": self.sentinel.capture_proof()}
                else:
                    raise ValueError(f"unknown action: {action}")
                self._json(result)
                return
            if parsed.path == "/api/spots":
                body = self._read_json()
                self.sentinel.save_spots(body.get("spots", []))
                self._json({"ok": True})
                return
            if parsed.path == "/api/upload":
                self._upload(parsed)
                return
            self.send_error(HTTPStatus.NOT_FOUND.value)
        except (ValueError, RuntimeError, json.JSONDecodeError) as error:
            self._json({"ok": False, "error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _upload(self, parsed: Any) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > self.sentinel.args.max_upload_bytes:
            raise ValueError("video is empty or exceeds upload limit")
        raw_name = parse_qs(parsed.query).get("filename", [""])[0]
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(raw_name).name)
        if not name or Path(name).suffix.casefold() not in VIDEO_EXTENSIONS:
            raise ValueError(f"unsupported video filename: {raw_name}")
        target = self.sentinel.upload_dir / f"{int(time.time())}-{name}"
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
        self.sentinel.request_source("video", str(target))
        self._json({"ok": True, "path": str(target)}, HTTPStatus.CREATED)


def parse_args() -> argparse.Namespace:
    demo_dir = Path(__file__).resolve().parent
    model_root = demo_dir / "models"
    installed_ui = Path("/usr/share/ti-edgeai-ev-spot-sentinel/ui")
    default_ui = installed_ui if installed_ui.is_dir() else demo_dir / "ui" / "dist"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("camera", "video"), default="video")
    parser.add_argument("--video", default="/usr/share/ti-edgeai-ev-spot-sentinel/ev-spot-demo.mp4")
    parser.add_argument("--vehicle-model-dir", default=str(model_root / VEHICLE_MODEL_NAME))
    parser.add_argument("--plate-detector", default=str(model_root / "plate-detector-384.onnx"))
    parser.add_argument("--plate-ocr", default=str(model_root / "plate-ocr-cct-xs-v2-global.onnx"))
    parser.add_argument("--tidl-core", type=int, choices=(1, 2), default=1)
    parser.add_argument("--vehicle-threshold", type=float, default=0.32)
    parser.add_argument("--plate-detector-threshold", type=float, default=0.28)
    parser.add_argument("--plate-confidence", type=float, default=0.72)
    parser.add_argument("--plate-votes", type=int, default=2)
    parser.add_argument("--alpr-interval", type=int, default=30)
    parser.add_argument("--alpr-max-vehicles", type=int, default=1)
    parser.add_argument("--occupancy-frames", type=int, default=2)
    parser.add_argument("--clear-frames", type=int, default=5)
    parser.add_argument("--overstay-seconds", type=int, default=1800)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--ui-dir", default=str(default_ui))
    parser.add_argument("--output-dir", default="/var/lib/ti-edgeai-ev-spot-sentinel")
    parser.add_argument("--stream-width", type=int, default=1280)
    parser.add_argument("--jpeg-quality", type=int, default=82)
    parser.add_argument("--max-upload-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--no-loop", dest="loop", action="store_false")
    args = parser.parse_args()
    if not Path(args.ui_dir).is_dir():
        parser.error(f"built UI is missing: {args.ui_dir}")
    if not 0 < args.vehicle_threshold <= 1 or not 0 < args.plate_confidence <= 1:
        parser.error("confidence thresholds must be in (0,1]")
    if min(args.alpr_interval, args.plate_votes, args.occupancy_frames, args.clear_frames, args.overstay_seconds, args.retention_days) < 1:
        parser.error("intervals, votes, frames, retention, and overstay must be positive")
    return args


def main() -> int:
    args = parse_args()
    sentinel = Sentinel(args)
    SentinelHandler.sentinel = sentinel
    SentinelHandler.static_dir = Path(args.ui_dir).resolve()
    server = ThreadingHTTPServer((args.host, args.port), SentinelHandler)

    def request_stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    sentinel.start()
    print(f"EV Spot Sentinel listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        sentinel.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
