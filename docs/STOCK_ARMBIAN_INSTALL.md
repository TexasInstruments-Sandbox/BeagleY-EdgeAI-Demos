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
sha256sum -c SHA256SUMS
tar -xJf "${ASSET}"
cd beagley-edgeai-j722s-psdk-11.02.01.03
sha256sum -c CONTENTS.SHA256
```

`debs/` contains the complete 28-package EdgeAI release and apt metadata.
`kernel/` contains the two ABI-matched Armbian kernel/DTB packages. All 30
Debian archives are covered by the inner and outer checksum manifests.

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
kernel metadata, and both EdgeAI DTBs. It makes no system changes.

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
2. installs the matching kernel and DTB packages;
3. selects the 4 GB EdgeAI DTB, with the CSI0/IMX219 composition when asked;
4. installs all EdgeAI packages through apt/dpkg;
5. runs dependency and dpkg audits;
6. retains the complete manifest and install log under
   `/var/lib/ti-edgeai-release/<UTC timestamp>/`.

It never runs `apt autoremove` and does not overwrite unrelated files outside
the declared Debian package ownership and boot-policy update.

## Validate after reboot

```bash
uname -r
find /sys/class/remoteproc -maxdepth 2 -name state -print -exec cat {} \;
sudo validate-j722s-edgeai
```

The strict smoke test must report full TIDL delegation and CPU fallback
disabled. A workload that silently executes only on Cortex-A is not a passing
result.

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

## Demo-only rollback

Removing the Gatekeeper does not remove the base EdgeAI stack:

```bash
sudo systemctl disable --now ti-edgeai-dachshund-gatekeeper
sudo apt remove ti-edgeai-dachshund-gatekeeper
# Use purge only to remove its conffile and /var/lib proof/upload data.
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
