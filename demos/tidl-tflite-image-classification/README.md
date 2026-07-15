# J722S TIDL TFLite image classification

This demo classifies any JPEG or PNG with the MobileNetV1 TFLite model from
`edgeai-tidl-models`. It deliberately disables TFLite's default CPU delegates,
requires one TIDL group to own the complete model output, and rejects missing
or non-positive TI execution and DDR counters.

The optional renderer combines the actual input image with the saved result;
it does not perform or alter inference.

## Requirements

- BeagleY-AI / TI AM67A (J722S)
- the J722S EdgeAI packages from this repository, including `ti-edgeai`,
  `ti-tidl-osrt`, and `edgeai-tidl-models`
- `python3-opencv` and `python3-numpy`
- root access to the Vision Apps DMA heap and remote services

## Example

Run these commands on the board from this directory:

```bash
curl -fL \
  https://upload.wikimedia.org/wikipedia/commons/3/34/Beagle_Dog_female.jpg \
  -o beagle.jpg

sudo ./classify-image-tidl.py beagle.jpg \
  --iterations 100 \
  --expect-label beagle \
  --source-title "Beagle Dog female.jpg" \
  --source-url "https://commons.wikimedia.org/wiki/File:Beagle_Dog_female.jpg" \
  --source-author Floodmfx \
  --source-license "CC BY-SA 4.0" \
  --json beagle-result.json

./render-inference-proof.py \
  --image beagle.jpg \
  --result beagle-result.json \
  --output beagle-proof.png
```

The referenced photograph is by Floodmfx and is licensed CC BY-SA 4.0. The
demo does not redistribute it.

Successful console output must include `34 nodes delegated out of 34 nodes`.
The JSON additionally records:

- one TIDL delegate group owning the model output;
- CPU fallback disabled;
- positive C7x execution time and DDR read/write deltas;
- source, preprocessed tensor, model, and output hashes;
- wall time, CPU time, memory use, and top classifications.

`--expect-label` is optional. When supplied, a different top-1 result makes the
command fail, which is useful for scripted demonstrations.

The default `--resize-mode stretch` matches the packaged square reference
input and remains reproducible with earlier results. For rectangular images,
`--resize-mode letterbox` preserves the complete subject and its proportions;
`--resize-mode center-crop` preserves proportions when the important subject
is centered and can safely be cropped. Letterboxing uses black padding by
default; select another uniform value with `--pad-color 0..255`.
