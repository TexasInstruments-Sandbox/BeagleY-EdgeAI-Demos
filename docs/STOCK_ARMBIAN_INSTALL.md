# Install on a normal Armbian BeagleY-AI

This release targets the **4 GB BeagleY-AI (AM67A/J722S)** running 64-bit
**Armbian Ubuntu Noble**. It is not intended for J721E, J721S2, J784S4, AM62A,
an 8 GB J722S EVM, Debian Bookworm, or a 32-bit userspace. The J722S firmware
and Linux reserved-memory DTB are a matched pair.

The installer does not disable UHS/SD modes. Back up important data and make
sure the board has working networking and at least 2 GB of free storage.

## Download and verify

On the board:

```bash
TAG=v11.2.1-beagley.1
BASE="https://github.com/TexasInstruments-Sandbox/BeagleY-EdgeAI-Demos/releases/download/${TAG}"
ASSET="beagley-edgeai-all-debs-j722s-psdk-11.02.01.03.tar.xz"

curl -fLO "${BASE}/${ASSET}"
curl -fLO "${BASE}/SHA256SUMS"
grep " ${ASSET}$" SHA256SUMS | sha256sum -c -
tar -xJf "${ASSET}"
cd beagley-edgeai-j722s-psdk-11.02.01.03
sha256sum -c CONTENTS.SHA256
```

`debs/` contains the complete 30-package EdgeAI release and apt metadata.
`kernel/` contains the two ABI-matched Armbian kernel image and DTB packages.
All 32 Debian archives are covered by inner and outer checksum manifests.
The standard Armbian BeagleY profile owns the PowerVR stack; this archive and
installer do not bundle, reinstall, downgrade, or depend on GPU packages.

## Optional fresh Armbian SD images

The release includes normal SD-boot Armbian Noble Minimal and GNOME desktop
images. Both have the matching kernel and DTBs but no EdgeAI packages
preinstalled. The GNOME image is a standard Armbian `mid` profile with GNOME 46
and GDM/Wayland; it has no custom Weston session or other secondary compositor.
Choose one image and write it from a Linux workstation:

```bash
TAG=v11.2.1-beagley.1
BASE="https://github.com/TexasInstruments-Sandbox/BeagleY-EdgeAI-Demos/releases/download/${TAG}"
IMAGE="armbian-beagley-ai-noble-vendor-6.12.49-minimal-base-20260715.img.xz"
# Or:
# IMAGE="armbian-beagley-ai-noble-vendor-6.12.49-gnome-wayland-mid-v11.2.1-beagley.1.img.xz"

curl -fLO "${BASE}/${IMAGE}"
curl -fLO "${BASE}/SHA256SUMS"
grep " ${IMAGE}$" SHA256SUMS | sha256sum -c -
xz -t "${IMAGE}"
lsblk
xzcat "${IMAGE}" | sudo dd of=/dev/sdX bs=4M iflag=fullblock \
  oflag=direct status=progress conv=fsync
sync
```

Replace `/dev/sdX` with the whole SD device, not a partition. The command
destroys that device's existing contents, so confirm it with `lsblk` before
writing. Boot the BeagleY-AI from the card, finish Armbian's first-login setup,
then follow the package download, dry-run, and installation steps in this
document. The image uses normal SD boot and does not contain the lab's
TFTP/NFS configuration.

## Validate without changing the board

Choose the intended camera policy and run a dry run first:

```bash
sudo ./install-j722s-release.sh \
  --debs debs --kernel kernel --camera none --dry-run

# For an IMX219 physically attached to CSI0:
sudo ./install-j722s-release.sh \
  --debs debs --kernel kernel --camera imx219 --dry-run
```

The dry run verifies the board model, Noble userspace, `arm64` architecture,
all package and kernel checksums, package count, BeagleY 4 GB firmware marker,
kernel ABI, and both EdgeAI DTBs. It makes no system
changes.

## Install

Run the same command without `--dry-run`. A reboot is required:

```bash
sudo ./install-j722s-release.sh \
  --debs debs --kernel kernel --camera none --reboot
```

For the IMX219 on CSI0, use:

```bash
sudo ./install-j722s-release.sh \
  --debs debs --kernel kernel --camera imx219 --reboot
```

The installer:

1. saves the package inventory and `/boot/armbianEnv.txt`;
2. installs the matching kernel image and DTB packages;
3. selects the 4 GB EdgeAI DTB, with the CSI0/IMX219 composition when asked;
4. installs all EdgeAI packages through apt/dpkg;
5. runs dependency and dpkg audits;
6. retains the complete manifest and install log under
   `/var/lib/ti-edgeai-release/<UTC timestamp>/`.

It never runs `apt autoremove` and does not overwrite unrelated files outside
the declared Debian package ownership and boot-policy update.

The transaction permits the two version-pinned TI `+ti1` GStreamer packages
to replace a newer Ubuntu revision. This is required for the packaged Bayer
caps fix on IMX219; no unpinned package downgrade is requested.

## Validate after reboot

```bash
uname -r
find /sys/class/remoteproc -maxdepth 2 -name state -print -exec cat {} \;
sudo validate-j722s-edgeai
```

The strict smoke test must report full TIDL delegation and CPU fallback
disabled. A workload that silently executes only on Cortex-A is not a passing
result. For GNOME graphics validation, separately use the Armbian-provided
`eglinfo -B` and `vulkaninfo --summary`; the reports must name PowerVR BXS, not
llvmpipe or lavapipe. More image and desktop detail is in
[ARMBIAN_GNOME_IMAGE.md](ARMBIAN_GNOME_IMAGE.md). GPU validation is a base-OS
check and is not part of the EdgeAI package transaction.

For the Gatekeeper:

```bash
sudo systemctl enable --now ti-edgeai-dachshund-gatekeeper
curl -fsS http://127.0.0.1:8088/api/status | python3 -m json.tool
```

Open `http://BOARD-IP:8088/`. The bundled video should reach `AUTHORIZED`,
report `C7x/MMA ACTIVE`, detector node count `283`, breed operator count `71`,
positive TIDL counters, and CPU fallback `0`.

For IMX219, select `IMX219 · CSI0` in the UI. Require `isp_active: true`, an
increasing frame/detector count, and no pipeline error. A scene without a dog
will correctly remain `WATCHING`.

For OmniCode:

```bash
sudo systemctl enable --now ti-edgeai-omnicode
curl -fsS http://127.0.0.1:8090/api/status | python3 -m json.tool
```

Open `http://BOARD-IP:8090/`. The bundled clip should decode QR Code, Data
Matrix, Code 128, and EAN-13 while reporting `TIDLExecutionProvider`, detector
node count `283`, increasing detector invocations, running C7x remote
processors, and CPU fallback `0`. ZXing-C++ runs on the Cortex-A53 only after
TIDL has localized a crop; full-frame CPU localization is disabled and shown
as such in the status response.

Select `IMX219 · CSI0` to use the camera. Require `source.isp_active: true`, an
increasing frame count, and successful raw-to-video conversion through VPAC
ISP. Camera decode range depends on focus, lighting, motion, print quality,
and symbol size.

For EV Spot Sentinel:

```bash
sudo systemctl enable --now ti-edgeai-ev-spot-sentinel
curl -fsS http://127.0.0.1:8090/api/status | python3 -m json.tool
```

Open `http://BOARD-IP:8090/`. Require `acceleration.active: true`, vehicle
provider `TIDLExecutionProvider`, node count `283`, an increasing invocation
count, and vehicle CPU fallback `false`. The bundled clip should identify plate
`5AU5341`, populate per-spot dwell time, and add it to the leaderboard. Global
ALPR is intentionally and visibly CPU-attributed; it is asynchronous and does
not weaken the fully accelerated vehicle path.

For IMX219, select `IMX219 · CSI0` and require both ISP-active fields plus an
increasing frame count. Edit and save the normalized polygons before using a
real parking view. Overstay output is for human review, not automatic
enforcement.

## Demo-only rollback

Removing the Gatekeeper does not remove the base EdgeAI stack:

```bash
sudo systemctl disable --now ti-edgeai-dachshund-gatekeeper
sudo apt remove ti-edgeai-dachshund-gatekeeper
# Use purge only to remove its conffile and /var/lib proof/upload data.
```

OmniCode has the same package-scoped rollback:

```bash
sudo systemctl disable --now ti-edgeai-omnicode
sudo apt remove ti-edgeai-omnicode
# Use purge only to remove its conffile and /var/lib proof/upload data.
```

EV Spot Sentinel also has package-scoped rollback:

```bash
sudo systemctl disable --now ti-edgeai-ev-spot-sentinel
sudo apt remove ti-edgeai-ev-spot-sentinel
# Use purge only to remove its conffile and /var/lib session/proof/upload data.
```

## Full rollback

Find the relevant install record:

```bash
sudo ls -1 /var/lib/ti-edgeai-release
```

Restore `armbianEnv.txt.before` from that record before rebooting into the
previous boot policy. The record also contains `packages-before.tsv`,
`packages-after.tsv`, the exact release manifest, checksums, and install log.
Review those files before removing or downgrading packages; do not use
`apt autoremove` because it can remove unrelated Armbian dependencies.
