# J722S TIDL TFLite dog-breed classification

This demo runs a 31-breed MobileNetV2 through TI's TFLite TIDL delegate. It
requires all 71 graph operators in one C7x group, disables TFLite's default CPU
delegates, requires the TIDL group to own the output, and rejects missing C7x
execution or DDR counters.

The source model is
[`Jaiking001/Dog_Breed_prediction`](https://huggingface.co/Jaiking001/Dog_Breed_prediction),
revision `b51edc39bd75596cde50e7e888f5d20779aadf9c`, licensed MIT. The
published model is MobileNetV2 plus global average pooling and two dense layers.
The TIDL-compatible export retains the published weights and preserves the
original output exactly while keeping the dense inputs in `1x1xC` layout.

The compiled model directory must contain:

```text
model/mobilenetv2-dog-breeds-31.tflite
artifacts/allowedNode.txt
artifacts/*_tidl_net.bin
artifacts/*_tidl_io_1.bin
artifacts/tidl-tflite-compiler-info.json
test-data/labels.json
```

Example on BeagleY-AI:

```bash
sudo ./classify-dog-breed-tidl.py dachshund.jpg \
  --iterations 100 \
  --expect-label Dachshund \
  --source-title "Dachshund (Short).jpg" \
  --source-url "https://commons.wikimedia.org/wiki/File:닥스훈트(단모종)_(Dachshund_(Short)).jpg" \
  --source-author Katemil94 \
  --source-license "CC BY-SA 4.0" \
  --json dachshund-result.json
```

Render a shareable proof card with the common renderer:

```bash
../tidl-tflite-image-classification/render-inference-proof.py \
  --image dachshund.jpg \
  --result dachshund-result.json \
  --output dachshund-proof.png
```

## Recorded BeagleY-AI proof

- [Rendered proof card](proof/dachshund-tidl-proof.png)
- [Raw 100-iteration result](proof/dachshund-result.json)

The recorded run classified the input as `Dachshund` at 98.69%, with all
71/71 operators delegated in one group and CPU fallback disabled. The input is
[`Dachshund (Short).jpg`](https://commons.wikimedia.org/wiki/File:닥스훈트(단모종)_(Dachshund_(Short)).jpg)
by Katemil94, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). The proof card,
which embeds that photograph, is shared under the same CC BY-SA 4.0 license;
this does not change the repository's license for the demo code.
