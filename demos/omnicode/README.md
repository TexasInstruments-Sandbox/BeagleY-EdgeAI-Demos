# OmniCode

OmniCode is a multi-format image/video/CSI reader for the 4 GB BeagleY-AI
(AM67A/J722S). It localizes symbols with TI's YOLOX-Nano barcode model on a
C7x/MMA through `TIDLExecutionProvider`, then decodes only those localized
crops with ZXing-C++ 2.2.1 on the Cortex-A53.

That boundary is intentional and visible in the UI: VPAC ISP and neural
localization are hardware-accelerated; payload parsing is a small CPU task.
Full-frame ZXing localization and ONNX CPU fallback are disabled, so a CPU-only
result cannot masquerade as an EdgeAI result.

## How this relates to TI's example

TI publishes `edgeai-gst-apps-barcode-reader` for AM62A. It combines this
one-class detector with ZBar. OmniCode uses the source ONNX model from that
demo, discards its AM62A/PSDK 8.2 compiled binaries, lowers only the detector
confidence metadata from 0.6 to 0.3, and reproducibly compiles all 283 PSDK
11.02 runtime nodes for J722S. The resulting descriptor is checked against the
J722S 380,952-byte ABI at build and runtime.

The model remains under TI's Text File License and is for use only with TI
devices. ZXing-C++ is Apache-2.0.

## Formats

ZXing 2.2.1 supports QR Code, Micro QR, rectangular Micro QR, Data Matrix,
Aztec, PDF417, MaxiCode, Code 39/93/128, Codabar, ITF, EAN-8/13, UPC-A/E,
GS1 DataBar, and GS1 DataBar Expanded. Actual camera range depends on symbol
size, focus, motion, print quality, and the detector's localization training.

OmniCode never opens URLs or executes Wi-Fi/contact payloads. It displays and
copies decoded text only.

## Install and run

Install the BeagleY EdgeAI release using the repository-level stock Armbian
instructions. `ti-edgeai-omnicode` is included in the 29-package archive:

```bash
sudo apt install ./ti-edgeai-omnicode_1.0.0-2_arm64.deb
sudo systemctl enable --now ti-edgeai-omnicode
```

Open `http://BOARD-IP:8090/`. The default source is a bundled multi-format test
video. Use **Source** to select an IMX219 on CSI0, upload media, or open a path
already on the board. Starting OmniCode stops the Gatekeeper service because
both own exclusive TIOVX/TIDL resources; the packages can remain installed
together.

For the camera explicitly:

```bash
sudo sed -i 's/^OMNICODE_SOURCE=.*/OMNICODE_SOURCE=camera/' /etc/default/ti-edgeai-omnicode
sudo systemctl restart ti-edgeai-omnicode
```

Do not add `--formats` unless you want a smaller allow-list. An invalid name
fails closed rather than silently decoding another format.

The default performance policy runs the detector on every frame, decodes each
set of localized crops every third frame using two CPU workers, tries ZXing's
fast path before its compatibility path, and publishes a 960-pixel,
quality-80 browser preview at up to 15 FPS in a single leaky background worker.
This keeps new-code latency low without repeatedly decoding the same static
payload hundreds of times per second or allowing 1080p JPEG preparation to
block TIDL. Override it for measurement or a specialized workload through
`/etc/default/ti-edgeai-omnicode`:

```bash
# Reproduce full-rate, single-worker decoder behavior for comparison:
OMNICODE_EXTRA_ARGS="--decode-interval=1 --decoder-workers=1 --stream-fps=60"

# Restrict decoding when only selected formats are required:
OMNICODE_EXTRA_ARGS="--formats=QRCode,DataMatrix --decode-interval=2"
```

`performance.decoder_ms` is the average wall-clock decoder cost per frame,
including zero-cost skipped frames. `decoder_cpu_ms`, `decoder_rois_per_frame`,
`source_ms`, `compute_ms`, `encoder_ms`, and `encoder_fps` expose the remaining
breakdown. The encoder cost is reported honestly but is no longer part of
inference latency.

An unchanged region is decoded at most every 12 detector frames. A new or
moving region bypasses that short cooldown immediately; use
`--decode-retry-frames` to tune this for a specialized scene.

On the 4 GB BeagleY-AI validation board the optimized pipeline reached 23.43
detector FPS with the conservative preview profile, versus a 6.81 FPS baseline.
The production 960/80/15 live-UI profile sustained 20.71 detector FPS and 11.26
preview FPS on the bundled video. CSI0/IMX219 through VPAC VISS sustained 12.94
detector and preview FPS, versus about 5.0 FPS originally. Every run selected
`TIDLExecutionProvider`, offloaded all 283 detector nodes, and reported
`cpu_fallback: 0`. Actual rates vary with scene and decoded crop count;
ZXing payload parsing remains CPU work by design.

## Verify acceleration

```bash
curl -fsS http://127.0.0.1:8090/api/status | python3 -m json.tool
```

A valid proof has all of the following:

- `acceleration.detector.provider` is `TIDLExecutionProvider`;
- `acceleration.detector.nodes` is `283` and invocations increase;
- `acceleration.cpu_fallback` is `0`;
- at least one `j722s-c71_*` remote processor is `running`;
- `source.isp_active` is `true` when IMX219 is selected;
- decoded records contain a non-empty format and payload.

The **Save proof** action writes an annotated frame and the complete status JSON
under `/var/lib/ti-edgeai-omnicode/proof/`.

## Stop, uninstall, and roll back

```bash
sudo systemctl disable --now ti-edgeai-omnicode
sudo apt remove ti-edgeai-omnicode       # preserves config and proof data
sudo apt purge ti-edgeai-omnicode        # also removes proof/upload data
```

The package never replaces generic GStreamer, OpenCV, ZXing, or camera files.
Its only conffile is `/etc/default/ti-edgeai-omnicode`.
