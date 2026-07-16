# OmniCode visual system

OmniCode is a local-first code reader presented as a precision instrument, not
as a generic admin dashboard. The accepted desktop and mobile concepts in this
directory are the visual source of truth.

## Direction

- Dark graphite canvas (`#070907`) with subtly lighter instrument surfaces.
- Signal green (`#a4f16c`) means active, decoded, or hardware-accelerated.
- Amber (`#f0b45c`) is reserved for attention and undecoded detections.
- Hairline borders, compact spacing, modest 2-6 px radii, and square telemetry.
- Condensed grotesk headings plus a monospace face for payloads and metrics.
- No decorative gradients, glass effects, oversized title text, or pill-heavy UI.

## Layout inventory

1. Quiet header with OmniCode wordmark, live source, and Source/Pause/Clear.
2. Dominant 16:9 live viewport with format-colored boxes and direct labels.
3. Selected result rail with format, payload, confidence, time, and copy action.
4. Recent scans list that preserves the latest unique decoded payloads.
5. Bottom telemetry strip showing FPS, TIDL provider/core, detector and decoder
   latency, VPAC ISP state, CPU fallback count, CPU, and memory.
6. Source dialog for CSI0 camera, a board-local path, or browser upload.

On narrow screens these regions stack in that order. Controls remain at least
44 px high, long payloads wrap, and telemetry becomes a two-column grid.

## Reference assets

- `omnicode-desktop-concept.png`: 1586 x 992 desktop reference.
- `omnicode-mobile-concept.png`: 853 x 1844 mobile reference.

The live camera/video image is the only photographic element. Icons are small
inline SVGs so the interface remains crisp and distributable without a font or
icon CDN.
