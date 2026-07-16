#!/usr/bin/env bash
# Download, verify, and install the pinned BeagleY-AI J722S EdgeAI release.

set -Eeuo pipefail

readonly RELEASE_TAG="v11.2.1-beagley.1"
readonly RELEASE_BASE="https://github.com/TexasInstruments-Sandbox/BeagleY-EdgeAI-Demos/releases/download/${RELEASE_TAG}"
readonly ARCHIVE="beagley-edgeai-all-debs-j722s-psdk-11.02.01.03.tar.xz"
readonly ARCHIVE_ROOT="beagley-edgeai-j722s-psdk-11.02.01.03"
readonly ARCHIVE_SHA256="25038b1e00960a73f6183857c171fc39699281271988380486dc0a2d63ea85ba"

CAMERA="none"
REBOOT=0
DRY_RUN=0
WORK_DIR=""

usage() {
    cat <<'EOF'
Download, verify, and install TI EdgeAI on a 4 GB BeagleY-AI running
64-bit Armbian Ubuntu Noble.

Usage:
  curl -fsSL https://github.com/TexasInstruments-Sandbox/BeagleY-EdgeAI-Demos/releases/download/v11.2.1-beagley.1/install-beagley-edgeai.sh | sudo bash -s -- [options]

Options:
  --camera MODE  none (default) or imx219 for an IMX219 attached to CSI0
  --dry-run      Download and validate everything, but make no board changes
  --reboot       Reboot after a successful installation
  --help         Show this help

Without --reboot, the script finishes installation and asks you to reboot
manually. Install records and rollback data are retained under
/var/lib/ti-edgeai-release/ by the package installer.
EOF
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if [[ -n "${WORK_DIR}" && -d "${WORK_DIR}" ]]; then
        rm -rf -- "${WORK_DIR}"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --camera)
            [[ $# -ge 2 ]] || die "--camera requires none or imx219"
            CAMERA="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --reboot)
            REBOOT=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

[[ "${CAMERA}" == "none" || "${CAMERA}" == "imx219" ]] || \
    die "--camera must be none or imx219"
[[ "${EUID}" -eq 0 ]] || die "run through sudo as shown in the README"

for command in curl sha256sum tar xz; do
    command -v "${command}" >/dev/null || die "required command not found: ${command}"
done

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/beagley-edgeai.XXXXXX")"
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cd "${WORK_DIR}"

printf 'Downloading %s (%s)...\n' "${ARCHIVE}" "${RELEASE_TAG}"
curl --fail --location --show-error --silent \
    --retry 3 --retry-all-errors --proto '=https' --tlsv1.2 \
    --output "${ARCHIVE}" "${RELEASE_BASE}/${ARCHIVE}"

printf '%s  %s\n' "${ARCHIVE_SHA256}" "${ARCHIVE}" | sha256sum -c -
xz -t "${ARCHIVE}"
tar -xJf "${ARCHIVE}"

release_dir="${WORK_DIR}/${ARCHIVE_ROOT}"
[[ -x "${release_dir}/install-j722s-release.sh" ]] || \
    die "release archive does not contain its guarded installer"
(
    cd "${release_dir}"
    sha256sum -c CONTENTS.SHA256
)

install_args=(
    --debs "${release_dir}/debs"
    --kernel "${release_dir}/kernel"
    --camera "${CAMERA}"
)
if [[ "${DRY_RUN}" -eq 1 ]]; then
    install_args+=(--dry-run)
fi

printf 'Running the guarded installer with camera policy: %s\n' "${CAMERA}"
bash "${release_dir}/install-j722s-release.sh" "${install_args[@]}"

if [[ "${DRY_RUN}" -eq 1 ]]; then
    printf 'Dry run complete; no board changes were made.\n'
elif [[ "${REBOOT}" -eq 1 ]]; then
    cleanup
    WORK_DIR=""
    trap - EXIT INT TERM
    printf 'Installation complete; rebooting now.\n'
    sync
    systemctl reboot
else
    printf 'Installation complete. Reboot with: sudo systemctl reboot\n'
fi
