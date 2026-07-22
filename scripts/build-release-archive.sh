#!/usr/bin/env bash
# Assemble the validated package and kernel directories into one standard,
# deterministic tar.xz release asset.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEBS=""
KERNEL_IMAGE=""
KERNEL_DTB=""
KERNEL_HEADERS=""
GRAPHICS=""
OUTPUT="${REPO_ROOT}/release"
ROOT_NAME="beagley-edgeai-j722s-psdk-11.02.01.03"
ASSET_NAME="beagley-edgeai-all-debs-j722s-psdk-11.02.01.03.tar.xz"
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-1783987200}"
BUILDER_COMMIT="${EDGEAI_BUILDER_COMMIT:-}"

usage() {
    cat <<'EOF'
Usage: scripts/build-release-archive.sh --debs DIR --graphics DIR --kernel-image DEB --kernel-dtb DEB --kernel-headers DEB --builder-commit SHA [--output DIR]

Requires GNU tar, xz, dpkg-deb, and sha256sum. DIR must be the validated
30-package release directory and the checksum-pinned 10-package TI PowerVR
directory. The kernel image, DTB, and headers must share one ABI.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --debs) DEBS="$2"; shift 2 ;;
        --kernel-image) KERNEL_IMAGE="$2"; shift 2 ;;
        --kernel-dtb) KERNEL_DTB="$2"; shift 2 ;;
        --kernel-headers) KERNEL_HEADERS="$2"; shift 2 ;;
        --graphics) GRAPHICS="$2"; shift 2 ;;
        --builder-commit) BUILDER_COMMIT="$2"; shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -n "${DEBS}" && -n "${GRAPHICS}" && -n "${KERNEL_IMAGE}" && \
   -n "${KERNEL_DTB}" && -n "${KERNEL_HEADERS}" && -n "${BUILDER_COMMIT}" ]] || {
    usage >&2
    exit 2
}
for tool in tar xz dpkg-deb sha256sum; do
    command -v "${tool}" >/dev/null || {
        echo "ERROR: ${tool} is required" >&2
        exit 1
    }
done

DEBS="$(cd "${DEBS}" && pwd)"
GRAPHICS="$(cd "${GRAPHICS}" && pwd)"
KERNEL_IMAGE="$(cd "$(dirname "${KERNEL_IMAGE}")" && pwd)/$(basename "${KERNEL_IMAGE}")"
KERNEL_DTB="$(cd "$(dirname "${KERNEL_DTB}")" && pwd)/$(basename "${KERNEL_DTB}")"
KERNEL_HEADERS="$(cd "$(dirname "${KERNEL_HEADERS}")" && pwd)/$(basename "${KERNEL_HEADERS}")"
mkdir -p "${OUTPUT}"
OUTPUT="$(cd "${OUTPUT}" && pwd)"

[[ -s "${DEBS}/SHA256SUMS" && -s "${DEBS}/package-manifest.tsv" ]] || {
    echo "ERROR: ${DEBS} is not a validated release directory" >&2
    exit 1
}
[[ -s "${GRAPHICS}/SHA256SUMS" ]] || {
    echo "ERROR: ${GRAPHICS} is not a checksum-pinned PowerVR directory" >&2
    exit 1
}
[[ "${BUILDER_COMMIT}" =~ ^[0-9a-f]{40}$ ]] || {
    echo "ERROR: --builder-commit must be a full 40-character git SHA" >&2
    exit 1
}
mapfile -t package_debs < <(find "${DEBS}" -maxdepth 1 -type f -name '*.deb' -print | sort)
[[ "${#package_debs[@]}" -eq 30 ]] || {
    echo "ERROR: expected 30 EdgeAI packages, found ${#package_debs[@]}" >&2
    exit 1
}
mapfile -t graphics_debs < <(find "${GRAPHICS}" -maxdepth 1 -type f -name '*.deb' -print | sort)
[[ "${#graphics_debs[@]}" -eq 10 ]] || {
    echo "ERROR: expected 10 PowerVR packages, found ${#graphics_debs[@]}" >&2
    exit 1
}
(
    cd "${GRAPHICS}"
    sha256sum -c SHA256SUMS
)
for file in "${KERNEL_IMAGE}" "${KERNEL_DTB}" "${KERNEL_HEADERS}"; do
    [[ -s "${file}" ]] || { echo "ERROR: missing ${file}" >&2; exit 1; }
    [[ "$(dpkg-deb -f "${file}" Architecture)" == arm64 ]] || {
        echo "ERROR: kernel package is not arm64: ${file}" >&2
        exit 1
    }
done
[[ "$(dpkg-deb -f "${KERNEL_IMAGE}" Package)" == linux-image-vendor-k3-beagle ]]
[[ "$(dpkg-deb -f "${KERNEL_DTB}" Package)" == linux-dtb-vendor-k3-beagle ]]
[[ "$(dpkg-deb -f "${KERNEL_HEADERS}" Package)" == linux-headers-vendor-k3-beagle ]]
(
    cd "${DEBS}"
    sha256sum -c SHA256SUMS
)

stage="$(mktemp -d)"
trap 'rm -rf "${stage}"' EXIT
root="${stage}/${ROOT_NAME}"
mkdir -p "${root}/debs" "${root}/graphics" "${root}/kernel"
cp -a "${DEBS}/." "${root}/debs/"
cp -a "${GRAPHICS}/." "${root}/graphics/"
cp -a "${KERNEL_IMAGE}" "${KERNEL_DTB}" "${KERNEL_HEADERS}" "${root}/kernel/"
cp -a "${REPO_ROOT}/scripts/install-j722s-release.sh" "${root}/"
cp -a "${REPO_ROOT}/docs/STOCK_ARMBIAN_INSTALL.md" "${root}/README.md"

(
    cd "${root}/kernel"
    sha256sum ./*.deb | sed 's#  \./#  #' > SHA256SUMS
)
cat >"${root}/RELEASE_INFO" <<EOF
psdk=11.02.01.03
psdk_analytics=REL.PSDK.ANALYTICS.11.02.01.02
tidl_osrt=11.02.16.00
vision_apps=11.02.03
kernel=6.12.49-vendor-k3-beagle
edgeai_package_count=30
powervr_package_count=10
powervr_userspace=25.3.6908880
powervr_mesa=24.0.1
kernel_package_count=3
source_commit=${BUILDER_COMMIT}
EOF
contents_manifest="${stage}/CONTENTS.SHA256.tmp"
(
    cd "${root}"
    find . -type f -print0 | sort -z | xargs -0 sha256sum
) >"${contents_manifest}"
mv "${contents_manifest}" "${root}/CONTENTS.SHA256"

asset="${OUTPUT}/${ASSET_NAME}"
rm -f "${asset}" "${OUTPUT}/SHA256SUMS"
tar --sort=name --mtime="@${SOURCE_DATE_EPOCH}" \
    --owner=0 --group=0 --numeric-owner -C "${stage}" -cf - "${ROOT_NAME}" | \
    xz -9e -T1 --check=crc64 >"${asset}"
(
    cd "${OUTPUT}"
    sha256sum "${ASSET_NAME}" > SHA256SUMS
    sha256sum -c SHA256SUMS
)
printf 'Wrote %s\n' "${asset}"
