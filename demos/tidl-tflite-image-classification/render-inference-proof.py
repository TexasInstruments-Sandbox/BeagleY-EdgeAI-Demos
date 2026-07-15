#!/usr/bin/python3
"""Render an auditable proof image from a TIDL classification JSON result."""

import argparse
import json
import os

import cv2
import numpy as np


def put_text(image, value, position, scale=0.6, color=(220, 225, 232), thickness=1):
    cv2.putText(
        image,
        value,
        position,
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def shorten(value, limit):
    return value if len(value) <= limit else value[: limit - 3] + "..."


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="same source image used for inference")
    parser.add_argument("--result", required=True, help="classifier JSON result")
    parser.add_argument("--output", required=True, help="output PNG path")
    parser.add_argument("--title", help="override proof-card title")
    parser.add_argument("--input-title", help="override displayed source title")
    parser.add_argument("--attribution", help="override author/license line")
    return parser.parse_args()


def validate_result(result):
    required = (
        "result",
        "delegate",
        "delegate_groups",
        "graph_operators",
        "operators_delegated",
        "cpu_fallback",
        "iterations",
        "mean_inference_ms",
        "tidl_last_run_ns",
        "tidl_ddr_read_bytes",
        "tidl_ddr_write_bytes",
        "max_rss_kib",
        "hostname",
        "kernel",
    )
    missing = [key for key in required if key not in result]
    if missing:
        raise RuntimeError(f"result JSON lacks proof fields: {missing}")
    top_results = result.get("top_results", result.get("top5", []))
    if not top_results:
        raise RuntimeError("result JSON has no classifications")
    if (
        result["result"] != "PASS"
        or result["delegate_groups"] != 1
        or result["operators_delegated"] != result["graph_operators"]
        or not str(result["cpu_fallback"]).startswith("disabled")
        or result["tidl_last_run_ns"] <= 0
        or result["tidl_ddr_read_bytes"] <= 0
        or result["tidl_ddr_write_bytes"] <= 0
    ):
        raise RuntimeError("result does not prove complete TIDL acceleration")
    return top_results


def main():
    args = parse_args()
    with open(args.result, encoding="utf-8") as stream:
        result = json.load(stream)
    top_results = validate_result(result)

    source = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if source is None:
        raise RuntimeError(f"cannot decode source image: {args.image}")

    canvas = np.zeros((900, 1600, 3), dtype=np.uint8)
    canvas[:] = (22, 25, 32)
    canvas[:, :820] = (17, 20, 26)

    top1 = top_results[0]["label"].split(",")[0]
    title = args.title or f"LIVE {top1.upper()} CLASSIFICATION - PASS"
    cv2.rectangle(canvas, (0, 0), (1600, 92), (35, 40, 50), -1)
    cv2.rectangle(canvas, (0, 88), (1600, 92), (64, 204, 124), -1)
    put_text(canvas, shorten(title, 43), (42, 57), 0.92, (86, 224, 145), 2)
    put_text(
        canvas,
        f"BeagleY-AI  |  TI {result.get('soc', 'AM67A/J722S')}  |  "
        f"{result.get('runtime', 'TFLite')}",
        (915, 55),
        0.62,
        (220, 225, 232),
        1,
    )

    box_x, box_y, box_size = 65, 139, 690
    image_scale = max(box_size / source.shape[1], box_size / source.shape[0])
    resized = cv2.resize(
        source,
        (
            int(round(source.shape[1] * image_scale)),
            int(round(source.shape[0] * image_scale)),
        ),
        interpolation=cv2.INTER_AREA,
    )
    x0 = (resized.shape[1] - box_size) // 2
    y0 = (resized.shape[0] - box_size) // 2
    canvas[box_y : box_y + box_size, box_x : box_x + box_size] = resized[
        y0 : y0 + box_size, x0 : x0 + box_size
    ]
    cv2.rectangle(canvas, (64, 138), (756, 830), (104, 112, 128), 2)
    cv2.rectangle(canvas, (65, 747), (755, 829), (10, 12, 16), -1)
    source_title = args.input_title or result.get("source_title") or os.path.basename(
        args.image
    )
    put_text(
        canvas,
        f"ACTUAL INPUT: {shorten(source_title, 43)}",
        (88, 779),
        0.61,
        (255, 255, 255),
        2,
    )
    attribution = args.attribution
    if not attribution:
        attribution = " / ".join(
            value
            for value in (
                result.get("source_author", ""),
                result.get("source_license", ""),
            )
            if value
        )
    put_text(canvas, shorten(attribution, 56), (88, 811), 0.46, (177, 186, 199), 1)

    panel_x = 855
    put_text(canvas, "ACCELERATOR EVIDENCE", (panel_x, 136), 0.72, (134, 211, 255), 2)
    cv2.rectangle(canvas, (panel_x, 151), (1540, 153), (70, 79, 93), -1)
    rows = [
        ("TIDL delegate", result["delegate"]),
        (
            "Operators offloaded",
            f'{result["operators_delegated"]}/{result["graph_operators"]} (one group)',
        ),
        ("CPU fallback", "DISABLED"),
        ("Timed runs", str(result["iterations"])),
        ("Mean inference", f'{result["mean_inference_ms"]:.3f} ms'),
        ("C7x last run", f'{result["tidl_last_run_ns"] / 1e6:.3f} ms'),
        (
            "C7x DDR read/write",
            f'{result["tidl_ddr_read_bytes"]:,} / '
            f'{result["tidl_ddr_write_bytes"]:,} bytes',
        ),
        ("Peak RSS", f'{result["max_rss_kib"] / 1024:.1f} MiB'),
    ]
    y = 191
    for label, value in rows:
        put_text(canvas, label.upper(), (panel_x, y), 0.43, (135, 145, 160), 1)
        color = (87, 225, 145) if value == "DISABLED" else (235, 239, 244)
        put_text(canvas, value, (1125, y), 0.51, color, 1)
        y += 42

    put_text(canvas, "CLASSIFICATION", (panel_x, 548), 0.72, (134, 211, 255), 2)
    cv2.rectangle(canvas, (panel_x, 562), (1540, 564), (70, 79, 93), -1)
    bar_left, bar_width, y = 1110, 405, 603
    for rank, item in enumerate(top_results[:5], start=1):
        label = shorten(item["label"].split(",")[0], 22)
        score = float(item["score"])
        put_text(canvas, f"{rank}. {label}", (panel_x, y), 0.48, (232, 235, 240), 1)
        cv2.rectangle(
            canvas,
            (bar_left, y - 15),
            (bar_left + bar_width, y + 2),
            (52, 58, 70),
            -1,
        )
        cv2.rectangle(
            canvas,
            (bar_left, y - 15),
            (bar_left + max(2, int(bar_width * min(max(score, 0.0), 1.0))), y + 2),
            (55, 179, 112) if rank == 1 else (69, 121, 172),
            -1,
        )
        put_text(canvas, f"{score * 100:5.1f}%", (1450, y - 22), 0.42, (190, 198, 210), 1)
        y += 47

    cv2.rectangle(canvas, (0, 862), (1600, 900), (35, 40, 50), -1)
    captured = str(result.get("captured_utc", "unknown time")).replace("+00:00", "Z")
    footer = f"Captured {captured} on {result['hostname']}, kernel {result['kernel']}"
    put_text(canvas, shorten(footer, 97), (42, 887), 0.46, (184, 193, 205), 1)
    put_text(
        canvas,
        "Raw JSON retained with this proof image",
        (1190, 887),
        0.42,
        (134, 211, 255),
        1,
    )

    if not cv2.imwrite(args.output, canvas, [cv2.IMWRITE_PNG_COMPRESSION, 9]):
        raise RuntimeError(f"failed to write proof image: {args.output}")
    print(os.path.abspath(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
