# Dachshund Gatekeeper

The Gatekeeper is a dual-stage, dual-source AM67A/J722S demo with a browser UI:

1. TI's recommended YOLOX-Nano COCO detector finds a dog through ONNX Runtime
   and `TIDLExecutionProvider` on C7x-1.
2. A 31-breed MobileNetV2 classifies the detector crop through TFLite and
   `libtidl_tfl_delegate.so` on C7x-2.
3. Three consecutive high-confidence Dachshund matches authorize the subject.

CPU graph execution is not a fallback. The server disables ONNX Runtime CPU EP
fallback, constructs TFLite with `BUILTIN_WITHOUT_DEFAULT_DELEGATES`, requires
the one TIDL group to own the breed output, verifies all 283 detector nodes and
all 71 breed operators, and rejects missing TIDL execution/DDR counters.

![Real J722S inference UI](proof/gatekeeper-ui-real-inference.jpg)

That screenshot is from the service running on the 4 GB BeagleY-AI, not UI
mock data. The recorded frame was `AUTHORIZED` as Dachshund at 98.7%, 13.5 FPS,
11.2 ms detector time and 8.0 ms breed time. It reported C7x/MMA active on both
cores, 26.4% system CPU, 251 MB process RSS, and CPU fallback `0`.

## Inputs

- **Video:** open a path already on the board or upload MP4/MOV/MKV/WebM/AVI
  from the source dialog. The package ships a known-good ten-second MP4.
- **Camera:** select `IMX219 · CSI0`. The service configures the 1920x1080
  SRGGB8 media graph, captures `/dev/video2`, and sends Bayer frames through
  `tiovxisp` with the J722S IMX219 VISS/2A DCC data before inference.

The service must run as root for Vision Apps `/dev/mem` and DMA-heap access.
The UI is available at `http://BOARD-IP:8088/`. `?snapshot` freezes one real
frame and one status response for deterministic screenshot capture; ordinary
use continues to update frames and telemetry.

## Install the ARM64 package

Install this repository's J722S EdgeAI release first on Armbian Noble, following
[`docs/STOCK_ARMBIAN_INSTALL.md`](../../docs/STOCK_ARMBIAN_INSTALL.md). Then:

```bash
sudo apt install ./ti-edgeai-dachshund-gatekeeper_1.0.0-1_arm64.deb
sudo systemctl enable --now ti-edgeai-dachshund-gatekeeper
curl -fsS http://127.0.0.1:8088/api/status | python3 -m json.tool
```

The package deliberately does not start the service during installation. Its
conffile is `/etc/default/ti-edgeai-dachshund-gatekeeper`; upgrades preserve
local choices. To start directly in camera mode, set `GATEKEEPER_SOURCE=camera`
and restart the unit. The default bundled video works without a camera.

Rollback is package-owned and does not touch other EdgeAI files:

```bash
sudo systemctl disable --now ti-edgeai-dachshund-gatekeeper
sudo apt remove ti-edgeai-dachshund-gatekeeper  # preserves config and proofs
sudo apt purge ti-edgeai-dachshund-gatekeeper  # also removes /var/lib proof/upload data
```

## Reproduce the package

The checksum-pinned model export, TIDL compilation, and Debian packaging source
lives in
[`ti-edgeai-armbian-build`](https://github.com/TexasInstruments-Sandbox/ti-edgeai-armbian-build/tree/agent/j722s-beagley-edgeai-release/packages/edgeai/ti-edgeai-dachshund-gatekeeper).
This demo repository intentionally publishes the runnable application and
precompiled package without duplicating TI compiler SDK and calibration trees.

The package owns `/opt/ti-edgeai-gatekeeper`, avoiding collisions with the
general `/opt/model_zoo`. Model input revisions, compiler output hashes, full
offload counts, and the final payload tree digest are embedded in the package.
The pinned TensorFlow 2.16.1 exporter freezes its inference
`ConcreteFunction` before TFLite conversion; this avoids resource-variable
MLIR failures under amd64 emulation and reproducibly produces model SHA-256
`1c4a7cb1c7d7a7165c76a7a3fd2bd27c538820ff71e6caabe8894c9d1dcc0442`.
Do not add `tf-keras` to the exporter image: pip replaces the pinned
TensorFlow build and changes or breaks conversion. A complete build must report
283 detector nodes and 71 breed operators on C7x with zero CPU nodes.

The UI uses exact npm versions plus `package-lock.json`; build it alone with:

```bash
cd demos/dachshund-gatekeeper/ui
npm ci
npm run build
```

## Direct development run

```bash
sudo ./gatekeeper.py \
  --source video \
  --video assets/dachshund-demo.mp4 \
  --detector-dir /path/to/ONR-OD-8200-yolox-nano-lite-mmdet-coco-416x416 \
  --breed-dir /path/to/TFL-CL-DOGBREEDS31-mobileNetV2 \
  --ui-dir ui/dist \
  --output-dir /var/lib/ti-edgeai-gatekeeper
```

Useful HTTP endpoints are `GET /api/status`, `GET /frame.jpg`,
`GET /stream.mjpg`, `POST /api/source`, `POST /api/upload`, and
`POST /api/control` (`pause`, `resume`, or `capture`). A capture writes an
annotated JPEG and matching JSON, including model offload, remoteproc, DDR,
latency, CPU, memory, and fallback evidence.

## Source and media licenses

- YOLOX-Nano is the official TI model-zoo entry
  `ONR-OD-8200-yolox-nano-lite-mmdet-coco-416x416`.
- The breed source is `Jaiking001/Dog_Breed_prediction`, pinned at revision
  `b51edc39bd75596cde50e7e888f5d20779aadf9c`, licensed MIT.
- The bundled photograph and derived MP4 are
  [Dachshund (Short).jpg](https://commons.wikimedia.org/wiki/File:%EB%8B%A5%EC%8A%A4%ED%9B%88%ED%8A%B8(%EB%8B%A8%EB%AA%A8%EC%A2%85)_(Dachshund_(Short)).jpg)
  by Katemil94, licensed
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
  This share-alike license applies to the media and derived proof images, not
  to the Gatekeeper source code.
