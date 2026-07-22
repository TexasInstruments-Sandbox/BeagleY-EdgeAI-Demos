# BeagleY-AI EdgeAI demos — v11.2.1-beagley.1

Initial public demo release for the 4 GB BeagleY-AI (AM67A/J722S).

- PSDK `11.02.01.03`, TIDL/OSRT `11.02.16.00`, Vision Apps `11.02.03`
- 30 validated EdgeAI Debian packages, 10 pinned TI PowerVR packages, and three
  matching Armbian kernel/DTB/header packages in one standard `tar.xz` archive
- PowerVR DKMS is built against the archived kernel headers, and install fails
  closed if the exact ABI is not reported installed
- optional regular-SD-boot Armbian Noble Minimal base image in standard
  `.img.xz` form; EdgeAI packages remain a separate, explicit installation
- optional GNOME 46/Wayland Armbian Noble `mid` image built through the same
  standard fork-based Armbian path, without a custom secondary compositor
- release-hosted, checksum-pinned copy/paste bootstrap installer
- guarded normal-Armbian Noble installer with dry-run, checksum, state record,
  camera-DTB selection, audit, and rollback information
- strict TFLite image classification, TFLite dog-breed classification, and
  dual-C7x Dachshund Gatekeeper demos
- uploaded/existing video and IMX219 CSI0/VPAC ISP Gatekeeper sources
- OmniCode QR/barcode reader with a J722S-recompiled 283-node TIDL detector,
  localized-crop ZXing-C++ decode, video/upload/board-path/IMX219 sources, and
  a live acceleration-proof UI
- verified QR Code, Data Matrix, Code 128, and EAN-13 payloads with CPU
  fallback disabled
- EV Spot Sentinel with 283-node TIDL vehicle occupancy, explicit asynchronous
  CPU ALPR, configurable parking zones, dwell/overstay history, leaderboard,
  bundled video, and IMX219 CSI0/VPAC ISP input
- recorded hardware proof with CPU fallback disabled

The package set previously passed installation, cold boot, TIDL, TFLite,
IMX219 raw capture, VPAC ISP, package ownership/dependency, and release
checksum validation on the 4 GB board.
