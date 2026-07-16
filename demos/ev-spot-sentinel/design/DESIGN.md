# EV Spot Sentinel visual system

The dashboard is an operational instrument: the live parking view and spot
state dominate, while policy and hardware attribution remain visible without
turning the page into a generic admin panel.

## Direction

- Charcoal canvas and instrument panels with precise hairline separators.
- Acid lime denotes available/healthy/accelerated state; amber and coral are
  reserved for attention and overstay.
- Condensed headings and monospaced telemetry make plate strings, durations,
  and accelerator evidence easy to scan.
- Compact controls, restrained radii, no decorative gradients, glass effects,
  or oversized title treatment.

## Layout inventory

1. Quiet header with source, live state, and source/pause/zone controls.
2. Dominant live view with detection boxes and draggable spot polygons.
3. Spot-state rail showing availability, dwell, plate, and confidence.
4. Recent sessions and longest-stay leaderboard.
5. Telemetry strip with FPS, TIDL nodes/core/fallback, ISP, ALPR attribution,
   CPU, and memory.
6. Source and zone-editor dialogs.

Narrow screens stack those regions, keep controls at least 44 px high, wrap
plate/region strings, and never create horizontal overflow.

## Fidelity ledger

The implementation matches the generated concept's dark/lime visual language,
live-view hierarchy, three-spot state rail, alert treatment, session table,
leaderboard, and telemetry block. It intentionally replaces the concept's
illustrative values with live status and labels ALPR as CPU rather than implying
unsupported full acceleration. Enforcement actions were omitted: the UI says
human review is required. The settings control became a functional polygon
editor and the source control supports video path, browser upload, and CSI0.

`ev-spot-sentinel-concept.png` is the accepted desktop reference. The live UI
screenshot is in `../proof/ev-spot-live-ui.png`.
