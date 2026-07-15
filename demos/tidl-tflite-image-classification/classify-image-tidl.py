#!/usr/bin/python3
"""Classify an image with MobileNetV1 on the AM67A/J722S TIDL delegate."""

import argparse
import datetime
import hashlib
import json
import os
import resource
import time

import cv2
import numpy as np
import tflite_runtime
import tflite_runtime.interpreter as tflite


DEFAULT_MODEL_DIR = "/opt/model_zoo/TFL-CL-0000-mobileNetV1-ti-example"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def memory_available_bytes():
    with open("/proc/meminfo", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable is absent from /proc/meminfo")


def preprocess_image(source_bgr, width, height, mode, pad_color):
    if mode == "stretch":
        resized = cv2.resize(
            source_bgr, (width, height), interpolation=cv2.INTER_LINEAR
        )
        description = f"OpenCV bilinear stretch to {width}x{height}"
    elif mode == "letterbox":
        scale = min(width / source_bgr.shape[1], height / source_bgr.shape[0])
        resized_width = max(1, int(round(source_bgr.shape[1] * scale)))
        resized_height = max(1, int(round(source_bgr.shape[0] * scale)))
        fitted = cv2.resize(
            source_bgr,
            (resized_width, resized_height),
            interpolation=cv2.INTER_LINEAR,
        )
        resized = np.full((height, width, 3), pad_color, dtype=np.uint8)
        x = (width - resized_width) // 2
        y = (height - resized_height) // 2
        resized[y : y + resized_height, x : x + resized_width] = fitted
        description = (
            f"OpenCV aspect-preserving letterbox to {width}x{height}; "
            f"pad color {pad_color}"
        )
    else:
        scale = max(width / source_bgr.shape[1], height / source_bgr.shape[0])
        resized_width = max(1, int(round(source_bgr.shape[1] * scale)))
        resized_height = max(1, int(round(source_bgr.shape[0] * scale)))
        fitted = cv2.resize(
            source_bgr,
            (resized_width, resized_height),
            interpolation=cv2.INTER_LINEAR,
        )
        x = (resized_width - width) // 2
        y = (resized_height - height) // 2
        resized = fitted[y : y + height, x : x + width]
        description = f"OpenCV aspect-preserving center crop to {width}x{height}"

    input_rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(input_rgb[np.newaxis, ...], dtype=np.uint8), description


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="JPEG or PNG to classify")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup-iterations", type=int, default=3)
    parser.add_argument("--core", type=int, choices=(1, 2), default=1)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--resize-mode",
        choices=("stretch", "letterbox", "center-crop"),
        default="stretch",
        help="how to fit a non-square source into the model input",
    )
    parser.add_argument(
        "--pad-color",
        type=int,
        default=0,
        help="0-255 BGR pad value used by letterbox mode",
    )
    parser.add_argument("--expect-label", help="required substring in top-1 label")
    parser.add_argument("--source-title", default="")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--source-author", default="")
    parser.add_argument("--source-license", default="")
    parser.add_argument("--json", required=True, help="result JSON path")
    args = parser.parse_args()
    if args.iterations < 1 or args.warmup_iterations < 0 or args.top_k < 1:
        parser.error("iterations and top-k must be positive; warmups cannot be negative")
    if not 0 <= args.pad_color <= 255:
        parser.error("pad-color must be in the range 0-255")
    return args


def main():
    args = parse_args()
    model = os.path.join(args.model_dir, "model/mobilenet_v1_1.0_224.tflite")
    artifacts = os.path.join(args.model_dir, "artifacts")
    labels_path = os.path.join(args.model_dir, "test-data/labels.txt")
    info_path = os.path.join(artifacts, "tidl-tflite-compiler-info.json")
    required = (
        model,
        labels_path,
        info_path,
        os.path.join(artifacts, "allowedNode.txt"),
        os.path.join(artifacts, "86_tidl_net.bin"),
        os.path.join(artifacts, "86_tidl_io_1.bin"),
    )
    missing = [path for path in required if not os.path.isfile(path)]
    if missing:
        raise RuntimeError(f"missing packaged TFLite assets: {missing}")

    with open(info_path, encoding="utf-8") as stream:
        compiler_info = json.load(stream)
    expected_ops = int(compiler_info.get("graph_nodes_offloaded", 0))
    if expected_ops < 1:
        raise RuntimeError(f"invalid TIDL compiler metadata: {compiler_info}")

    resolver = tflite.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES
    original = tflite.Interpreter(
        model_path=model,
        num_threads=1,
        experimental_op_resolver_type=resolver,
    )
    original.allocate_tensors()
    original_ops = original._get_ops_details()
    input_detail = original.get_input_details()[0]
    if len(original_ops) != expected_ops or any(
        op["op_name"] == "DELEGATE" for op in original_ops
    ):
        raise RuntimeError(
            f"compiled/offline graph mismatch: {expected_ops=} runtime={original_ops}"
        )
    input_shape = tuple(int(value) for value in input_detail["shape"])
    if len(input_shape) != 4 or input_shape[0] != 1 or input_shape[3] != 3:
        raise RuntimeError(f"expected an NHWC image model, got {input_shape}")
    if input_detail["dtype"] != np.uint8:
        raise RuntimeError(f"expected uint8 model input, got {input_detail['dtype']}")
    del original

    source_bgr = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if source_bgr is None:
        raise RuntimeError(f"cannot decode input image: {args.image}")
    sample, preprocessing = preprocess_image(
        source_bgr,
        input_shape[2],
        input_shape[1],
        args.resize_mode,
        args.pad_color,
    )

    memory_before = memory_available_bytes()
    delegate = tflite.load_delegate(
        "libtidl_tfl_delegate.so",
        {
            "artifacts_folder": artifacts,
            "core_number": str(args.core),
            "debug_level": "0",
        },
    )
    interpreter = tflite.Interpreter(
        model_path=model,
        experimental_delegates=[delegate],
        num_threads=1,
        experimental_op_resolver_type=resolver,
    )
    interpreter.allocate_tensors()
    runtime_ops = interpreter._get_ops_details()
    delegate_ops = [op for op in runtime_ops if op["op_name"] == "DELEGATE"]
    if len(delegate_ops) != 1:
        raise RuntimeError(f"TIDL did not create one all-node group: {runtime_ops}")

    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    if delegate_ops[0]["outputs"].tolist() != [int(output_detail["index"])]:
        raise RuntimeError("TIDL delegate does not own the model output")
    interpreter.set_tensor(input_detail["index"], sample)

    for _ in range(args.warmup_iterations):
        interpreter.invoke()
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter()
    for _ in range(args.iterations):
        interpreter.invoke()
    wall_seconds = time.perf_counter() - started
    usage_after = resource.getrusage(resource.RUSAGE_SELF)

    output = np.asarray(interpreter.get_tensor(output_detail["index"]))
    flat = output.reshape(-1)
    with open(labels_path, encoding="utf-8") as stream:
        labels = stream.read().splitlines()
    top_indices = np.argsort(flat)[-args.top_k :][::-1].tolist()
    top_results = [
        {
            "index": int(index),
            "label": labels[index] if index < len(labels) else "<missing>",
            "score": float(flat[index]),
        }
        for index in top_indices
    ]
    if args.expect_label and args.expect_label.casefold() not in top_results[0][
        "label"
    ].casefold():
        raise RuntimeError(
            f"top-1 {top_results[0]['label']!r} does not contain "
            f"{args.expect_label!r}"
        )

    benchmark = {
        key: int(value) for key, value in interpreter.get_TI_benchmark_data().items()
    }
    required_counters = (
        "ts:run_start",
        "ts:run_end",
        "ddr:read_start",
        "ddr:read_end",
        "ddr:write_start",
        "ddr:write_end",
    )
    absent = [key for key in required_counters if key not in benchmark]
    if absent:
        raise RuntimeError(f"TI accelerator counters are absent: {absent}")
    run_ns = benchmark["ts:run_end"] - benchmark["ts:run_start"]
    read_bytes = benchmark["ddr:read_end"] - benchmark["ddr:read_start"]
    write_bytes = benchmark["ddr:write_end"] - benchmark["ddr:write_start"]
    if run_ns <= 0 or read_bytes <= 0 or write_bytes <= 0:
        raise RuntimeError(f"TIDL accelerator counters are invalid: {benchmark}")

    cpu_seconds = (
        usage_after.ru_utime
        + usage_after.ru_stime
        - usage_before.ru_utime
        - usage_before.ru_stime
    )
    result = {
        "result": "PASS",
        "captured_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "soc": "AM67A/J722S",
        "hostname": os.uname().nodename,
        "kernel": os.uname().release,
        "runtime": "TFLite",
        "delegate": "libtidl_tfl_delegate.so",
        "delegate_groups": len(delegate_ops),
        "graph_operators": len(original_ops),
        "operators_delegated": expected_ops,
        "cpu_fallback": "disabled (no default delegates; one all-node TIDL group)",
        "iterations": args.iterations,
        "warmup_iterations": args.warmup_iterations,
        "mean_inference_ms": wall_seconds * 1000 / args.iterations,
        "wall_seconds": wall_seconds,
        "process_cpu_seconds": cpu_seconds,
        "max_rss_kib": usage_after.ru_maxrss,
        "mem_available_before_bytes": memory_before,
        "mem_available_after_bytes": memory_available_bytes(),
        "tidl_last_run_ns": run_ns,
        "tidl_ddr_read_bytes": read_bytes,
        "tidl_ddr_write_bytes": write_bytes,
        "tidl_benchmark": benchmark,
        "core_number": args.core,
        "top_results": top_results,
        "top5": top_results[:5],
        "source_image": os.path.abspath(args.image),
        "source_title": args.source_title or os.path.basename(args.image),
        "source_image_sha256": sha256(args.image),
        "preprocessed_tensor_sha256": hashlib.sha256(sample.tobytes()).hexdigest(),
        "resize_mode": args.resize_mode,
        "preprocessing": f"{preprocessing}; BGR to RGB; uint8 NHWC",
        "source_url": args.source_url,
        "source_author": args.source_author,
        "source_license": args.source_license,
        "model": model,
        "model_sha256": sha256(model),
        "output_sha256": hashlib.sha256(output.tobytes()).hexdigest(),
        "tflite_runtime_version": tflite_runtime.__version__,
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    with open(args.json, "w", encoding="utf-8") as stream:
        stream.write(rendered + "\n")
    print("J722S TIDL IMAGE CLASSIFICATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
