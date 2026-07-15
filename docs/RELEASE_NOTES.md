# BeagleY-AI EdgeAI demos — v11.2.1-beagley.1

Initial public demo release for the 4 GB BeagleY-AI (AM67A/J722S).

- PSDK `11.02.01.03`, TIDL/OSRT `11.02.16.00`, Vision Apps `11.02.03`
- 28 validated EdgeAI Debian packages plus two matching Armbian kernel/DTB
  packages in one standard `tar.xz` archive
- optional regular-SD-boot Armbian Noble Minimal base image in standard
  `.img.xz` form; EdgeAI packages remain a separate, explicit installation
- guarded normal-Armbian Noble installer with dry-run, checksum, state record,
  camera-DTB selection, audit, and rollback information
- strict TFLite image classification, TFLite dog-breed classification, and
  dual-C7x Dachshund Gatekeeper demos
- uploaded/existing video and IMX219 CSI0/VPAC ISP Gatekeeper sources
- recorded hardware proof with CPU fallback disabled

The package set previously passed installation, cold boot, TIDL, TFLite,
IMX219 raw capture, VPAC ISP, package ownership/dependency, and release
checksum validation on the 4 GB board.
