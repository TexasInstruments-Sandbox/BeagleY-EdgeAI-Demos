# EdgeAI demos

These demos run against the Debian packages published with this repository. They
are intentionally separate from package validation so they can evolve into
user-facing examples without weakening the strict installation smoke tests.

| Demo | Purpose |
| --- | --- |
| [`tidl-tflite-image-classification`](tidl-tflite-image-classification/) | Classify an arbitrary image with the packaged MobileNetV1 TFLite model on J722S TIDL/C7x and render an auditable proof image |
| [`tidl-tflite-dog-breed-classification`](tidl-tflite-dog-breed-classification/) | Classify 31 dog breeds with MobileNetV2 and strict, complete TFLite TIDL offload |
| [`dachshund-gatekeeper`](dachshund-gatekeeper/) | Detect dogs, verify Dachshunds, and make stable access decisions from uploaded/existing video or IMX219 CSI0 through a responsive local UI |
| [`omnicode`](omnicode/) | Localize code regions on TIDL and decode QR, Data Matrix, Aztec, PDF417, linear, and retail formats from video or IMX219 CSI0 |
| [`ev-spot-sentinel`](ev-spot-sentinel/) | Track parking occupancy, plates, dwell time, overstays, and a longest-stay leaderboard from video or IMX219 CSI0 |

Each demo directory documents its package requirements, invocation, output,
and the evidence used to distinguish real TI acceleration from CPU fallback.
