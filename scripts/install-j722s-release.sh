#!/usr/bin/env bash
# Install a validated J722S/BeagleY-AI release on an Armbian Noble SD root.
# The script is intentionally board-specific: using another K3 SoC's firmware
# or a DTB without the matching 4 GiB reserved-memory map is unsafe.

set -euo pipefail

DEB_DIR=""
KERNEL_DIR=""
CAMERA="none"
REBOOT=0
DRY_RUN=0
EXPECTED_KERNEL_RELEASE="6.12.49-vendor-k3-beagle"

usage() {
    cat <<'EOF'
Usage: scripts/install-j722s-release.sh --debs DIR [options]

Required:
  --debs DIR       Extracted validated J722S package directory containing
                   package-manifest.tsv, SHA256SUMS, and the .deb files

Options:
  --kernel DIR     Extracted matching Armbian kernel bundle. Required when the
                   installed kernel/DTB package is not the release build.
  --camera MODE    none (default) or imx219 for the CSI0 composite DTB
  --reboot         Reboot after a successful install and package audit
  --dry-run        Validate inputs and print the intended changes only
  --help

The install record and the previous /boot/armbianEnv.txt are retained below
/var/lib/ti-edgeai-release/<UTC timestamp>/ for audit and rollback.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --debs)    DEB_DIR="$2"; shift 2 ;;
        --kernel)  KERNEL_DIR="$2"; shift 2 ;;
        --camera)  CAMERA="$2"; shift 2 ;;
        --reboot)  REBOOT=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -n "${DEB_DIR}" ]] || { echo "ERROR: --debs is required" >&2; exit 2; }
[[ "${CAMERA}" == "none" || "${CAMERA}" == "imx219" ]] || {
    echo "ERROR: --camera must be none or imx219" >&2
    exit 2
}

DEB_DIR="$(cd "${DEB_DIR}" && pwd)"
[[ -z "${KERNEL_DIR}" ]] || KERNEL_DIR="$(cd "${KERNEL_DIR}" && pwd)"

command -v dpkg >/dev/null
command -v dpkg-deb >/dev/null
command -v dpkg-query >/dev/null
command -v apt-get >/dev/null
command -v sha256sum >/dev/null

[[ "$(dpkg --print-architecture)" == "arm64" ]] || {
    echo "ERROR: this release supports arm64 only" >&2
    exit 1
}
model="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
[[ "${model}" == *"BeagleY-AI"* ]] || {
    echo "ERROR: expected BeagleY-AI, found: ${model:-unknown}" >&2
    exit 1
}
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_CODENAME:-}" == "noble" ]] || {
    echo "ERROR: this release was validated only on Ubuntu Noble" >&2
    exit 1
}

[[ -s "${DEB_DIR}/SHA256SUMS" && -s "${DEB_DIR}/package-manifest.tsv" ]] || {
    echo "ERROR: ${DEB_DIR} is not a validated release directory" >&2
    exit 1
}
mapfile -t DEBS < <(find "${DEB_DIR}" -maxdepth 1 -type f -name '*.deb' -print | sort)
[[ "${#DEBS[@]}" -eq 28 ]] || {
    echo "ERROR: expected 28 release packages, found ${#DEBS[@]}" >&2
    exit 1
}
grep -q $'^ti-edgeai-firmware-j722s\t.*beagley4gb' \
    "${DEB_DIR}/package-manifest.tsv" || {
    echo "ERROR: release does not contain BeagleY-AI 4 GiB firmware" >&2
    exit 1
}
(
    cd "${DEB_DIR}"
    sha256sum -c SHA256SUMS
)

KERNEL_DEBS=()
if [[ -n "${KERNEL_DIR}" ]]; then
    [[ -s "${KERNEL_DIR}/SHA256SUMS" ]] || {
        echo "ERROR: kernel bundle lacks SHA256SUMS" >&2
        exit 1
    }
    (
        cd "${KERNEL_DIR}"
        sha256sum -c SHA256SUMS
    )
    mapfile -t kernel_images < <(find "${KERNEL_DIR}" -maxdepth 1 -type f \
        -name 'linux-image-vendor-k3-beagle_*.deb' -print)
    mapfile -t kernel_dtbs < <(find "${KERNEL_DIR}" -maxdepth 1 -type f \
        -name 'linux-dtb-vendor-k3-beagle_*.deb' -print)
    [[ "${#kernel_images[@]}" -eq 1 && "${#kernel_dtbs[@]}" -eq 1 ]] || {
        echo "ERROR: kernel bundle must contain exactly one image and one DTB package" >&2
        exit 1
    }
    KERNEL_DEBS=("${kernel_images[0]}" "${kernel_dtbs[0]}")
    [[ "$(dpkg-deb -f "${kernel_images[0]}" Package)" == \
        "linux-image-vendor-k3-beagle" && \
       "$(dpkg-deb -f "${kernel_images[0]}" Architecture)" == "arm64" ]] || {
        echo "ERROR: kernel image archive has unexpected package metadata" >&2
        exit 1
    }
    [[ "$(dpkg-deb -f "${kernel_dtbs[0]}" Package)" == \
        "linux-dtb-vendor-k3-beagle" && \
       "$(dpkg-deb -f "${kernel_dtbs[0]}" Architecture)" == "arm64" ]] || {
        echo "ERROR: kernel DTB archive has unexpected package metadata" >&2
        exit 1
    }
    kernel_image_contents="$(dpkg-deb --contents "${kernel_images[0]}")"
    kernel_dtb_contents="$(dpkg-deb --contents "${kernel_dtbs[0]}")"
    grep -q "\./boot/vmlinuz-${EXPECTED_KERNEL_RELEASE}$" \
        <<<"${kernel_image_contents}" || {
        echo "ERROR: kernel bundle does not contain ${EXPECTED_KERNEL_RELEASE}" >&2
        exit 1
    }
    for required_dtb in \
        k3-am67a-beagley-ai-edgeai.dtb \
        k3-am67a-beagley-ai-edgeai-csi0-imx219.dtb; do
        grep -q "/ti/${required_dtb}$" <<<"${kernel_dtb_contents}" || {
            echo "ERROR: kernel bundle lacks ${required_dtb}" >&2
            exit 1
        }
    done
fi

if [[ "${CAMERA}" == "imx219" ]]; then
    FDTFILE="ti/k3-am67a-beagley-ai-edgeai-csi0-imx219.dtb"
else
    FDTFILE="ti/k3-am67a-beagley-ai-edgeai.dtb"
fi

if [[ -z "${KERNEL_DIR}" ]]; then
    [[ "$(uname -r)" == "${EXPECTED_KERNEL_RELEASE}" ]] || {
        echo "ERROR: running kernel is $(uname -r), expected " \
            "${EXPECTED_KERNEL_RELEASE}; supply --kernel" >&2
        exit 1
    }
    installed_dtb=""
    for candidate in /boot/dtb-*/"${FDTFILE}" /boot/dtb/"${FDTFILE}"; do
        if [[ -f "${candidate}" ]]; then
            installed_dtb="${candidate}"
            break
        fi
    done
    [[ -n "${installed_dtb}" ]] || {
        echo "ERROR: installed kernel package lacks ${FDTFILE}; supply --kernel" >&2
        exit 1
    }
fi

printf 'Board: %s\n' "${model}"
printf 'Userspace: %s %s (%s)\n' "${ID}" "${VERSION_CODENAME}" \
    "$(dpkg --print-architecture)"
printf 'Current kernel: %s\n' "$(uname -r)"
printf 'Release packages: %s\n' "${#DEBS[@]}"
printf 'Selected DTB: %s\n' "${FDTFILE}"
if [[ -n "${KERNEL_DIR}" ]]; then
    printf 'Kernel bundle: %s\n' "${KERNEL_DIR}"
else
    printf 'Kernel bundle: reuse installed release kernel/DTB package\n'
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "DRY RUN: validation passed; no system state changed"
    exit 0
fi

if [[ "${EUID}" -eq 0 ]]; then
    SUDO=()
else
    command -v sudo >/dev/null || {
        echo "ERROR: run as root or install sudo" >&2
        exit 1
    }
    SUDO=(sudo)
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
STATE_DIR="/var/lib/ti-edgeai-release/${timestamp}"
"${SUDO[@]}" install -d -m 0755 "${STATE_DIR}"
"${SUDO[@]}" cp -a "${DEB_DIR}/SHA256SUMS" \
    "${DEB_DIR}/package-manifest.tsv" "${STATE_DIR}/"
dpkg-query -W >"/tmp/ti-edgeai-packages-before.${timestamp}"
"${SUDO[@]}" mv "/tmp/ti-edgeai-packages-before.${timestamp}" \
    "${STATE_DIR}/packages-before.tsv"
if [[ -e /boot/armbianEnv.txt ]]; then
    "${SUDO[@]}" cp -a /boot/armbianEnv.txt \
        "${STATE_DIR}/armbianEnv.txt.before"
fi

LOG="${STATE_DIR}/install.log"
exec > >("${SUDO[@]}" tee -a "${LOG}") 2>&1

echo "Installing J722S EdgeAI release at ${timestamp}"
"${SUDO[@]}" apt-get update
if [[ "${#KERNEL_DEBS[@]}" -gt 0 ]]; then
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y \
        --reinstall "${KERNEL_DEBS[@]}"
fi

dtb=""
for candidate in /boot/dtb-*/"${FDTFILE}" /boot/dtb/"${FDTFILE}"; do
    if [[ -f "${candidate}" ]]; then
        dtb="${candidate}"
        break
    fi
done
[[ -n "${dtb}" ]] || {
    echo "ERROR: selected release DTB was not installed: ${FDTFILE}" >&2
    exit 1
}

"${SUDO[@]}" touch /boot/armbianEnv.txt
env_tmp="$(mktemp)"
awk -v value="fdtfile=${FDTFILE}" '
    BEGIN { written = 0 }
    /^fdtfile=/ {
        if (!written) print value
        written = 1
        next
    }
    { print }
    END { if (!written) print value }
' /boot/armbianEnv.txt >"${env_tmp}"
"${SUDO[@]}" install -m 0644 "${env_tmp}" /boot/armbianEnv.txt
rm -f "${env_tmp}"

"${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --reinstall "${DEBS[@]}"
"${SUDO[@]}" apt-get check
"${SUDO[@]}" dpkg --audit

packages="$(tail -n +2 "${DEB_DIR}/package-manifest.tsv" | cut -f1 | sort -u)"
# shellcheck disable=SC2086
dpkg-query -W ${packages} >"/tmp/ti-edgeai-packages-after.${timestamp}"
"${SUDO[@]}" mv "/tmp/ti-edgeai-packages-after.${timestamp}" \
    "${STATE_DIR}/packages-after.tsv"
"${SUDO[@]}" cp -a /boot/armbianEnv.txt "${STATE_DIR}/armbianEnv.txt.after"

echo "INSTALL: PASS"
echo "Install record: ${STATE_DIR}"
echo "Reboot is required before acceleration validation."
if [[ "${REBOOT}" -eq 1 ]]; then
    sync
    "${SUDO[@]}" systemctl reboot
fi
