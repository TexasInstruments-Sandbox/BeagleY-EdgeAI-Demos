# Dachshund Gatekeeper design specification

The accepted implementation reference is
[`gatekeeper-concept.png`](gatekeeper-concept.png), generated at 1536×1024.

## System

- Background: true near-black navy `#030d16`; surfaces remain in the same cool
  navy family rather than becoming floating cards.
- Primary text: warm white `#f5f3ed`; secondary text: steel `#95a2b4`;
  dividers: `#263544`.
- Verified/authorized accent: safety lime `#a8dc16`; warning: `#f0b90b`.
- Display typography: condensed, square, uppercase. UI/data typography: neutral
  sans-serif with tabular numerals. Controls use deliberate 14 px type.
- Geometry: open rails and bands, hairline dividers, 10 px media/control radius,
  no glass, glow, gradients, decorative pills, or nested card grid.

## Primary screen inventory

The header contains the line-art dog/gate mark, `Dachshund Gatekeeper`, the
subtitle `Local vision. Verifiable decisions.`, and a two-option source control:
`IMX219 · CSI0` / `Video file`.

The main screen contains:

1. A dominant 16:9 annotated live viewport.
2. A right decision rail with gate state, current subject, breed confidence,
   stable-frame tracker state, and source-change control.
3. A single thin pipeline/performance strip showing CSI/decoder, ISP, detector,
   classifier, FPS, latencies, C7x/MMA state, CPU fallback, and RAM.
4. A compact three-row event timeline and the `Pause` / `Capture proof` actions.

At widths below 920 px, the decision rail moves under the viewport. Below
640 px, source controls and actions stack and telemetry becomes horizontally
scrollable. The media remains first.

## Required interaction states

- Live camera and video-file source selection, including file upload.
- Playing and paused states.
- No dog, tracking, verifying, authorized, and held decisions.
- Capture-proof success and error feedback.
- TIDL-active and explicit fallback/error states based on backend evidence.
