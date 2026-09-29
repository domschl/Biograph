#!/usr/bin/env bash
#
# scripts/set-version.sh
# Sets the project version across all Biograph components from the root VERSION file.
#
# Usage:
#   ./scripts/set-version.sh            # Print current version
#   ./scripts/set-version.sh <version>  # Set new version everywhere
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION_FILE="${ROOT_DIR}/VERSION"

if [[ $# -eq 0 || "${1:-}" == "--get" || "${1:-}" == "-g" ]]; then
    if [[ -f "${VERSION_FILE}" ]]; then
        cat "${VERSION_FILE}"
        exit 0
    else
        echo "Error: ${VERSION_FILE} not found." >&2
        exit 1
    fi
fi

NEW_VERSION="${1}"

# Strip leading 'v' if provided
NEW_VERSION="${NEW_VERSION#v}"

# Basic semver validation
if ! [[ "${NEW_VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([a-zA-Z0-9._-]+)?$ ]]; then
    echo "Error: Invalid version format '${NEW_VERSION}'. Expected e.g. 0.2.1" >&2
    exit 1
fi

OLD_VERSION=""
if [[ -f "${VERSION_FILE}" ]]; then
    OLD_VERSION="$(tr -d ' \n\r' < "${VERSION_FILE}")"
fi

echo "==> Setting Biograph version: ${OLD_VERSION:-<none>} -> ${NEW_VERSION}"

# 1. Update root VERSION
echo "${NEW_VERSION}" > "${VERSION_FILE}"
echo "  ✓ Updated VERSION"

# 2. Update Python pyproject.toml files
PYTHON_PROJECTS=(
    "backend/pyproject.toml"
    "sensors/cli/pyproject.toml"
    "sensors/shell/pyproject.toml"
)

for proj in "${PYTHON_PROJECTS[@]}"; do
    file="${ROOT_DIR}/${proj}"
    if [[ -f "${file}" ]]; then
        sed -i -E "s/^(version[[:space:]]*=[[:space:]]*\")[^\"]+(\")/\1${NEW_VERSION}\2/" "${file}"
        echo "  ✓ Updated ${proj}"
    fi
done

# 3. Update uv.lock files
for dir in "backend" "sensors/cli" "sensors/shell"; do
    if [[ -d "${ROOT_DIR}/${dir}" ]] && command -v uv >/dev/null 2>&1; then
        (cd "${ROOT_DIR}/${dir}" && uv lock --quiet)
        echo "  ✓ Updated ${dir}/uv.lock"
    fi
done

# 4. Update Arch Linux PKGBUILDs
PKGBUILDS=(
    "packaging/arch/biograph-backend/PKGBUILD"
    "packaging/arch/biograph-cli/PKGBUILD"
    "packaging/arch/biograph-sensor-shell/PKGBUILD"
)

for pkgbuild in "${PKGBUILDS[@]}"; do
    file="${ROOT_DIR}/${pkgbuild}"
    if [[ -f "${file}" ]]; then
        sed -i -E "s/^(pkgver=).*/\1${NEW_VERSION}/" "${file}"
        sed -i -E "s/^(pkgrel=).*/\11/" "${file}"
        echo "  ✓ Updated ${pkgbuild}"
    fi
done

# 5. Update GNU Guix definition
GUIX_FILE="${ROOT_DIR}/packaging/guix/biograph.scm"
if [[ -f "${GUIX_FILE}" ]]; then
    sed -i -E "s/(\(version[[:space:]]+\")[^\"]+(\")/\1${NEW_VERSION}\2/" "${GUIX_FILE}"
    echo "  ✓ Updated packaging/guix/biograph.scm"
fi

# 6. Update Browser Extension manifest.json
MANIFEST_FILE="${ROOT_DIR}/browser-extension/manifest.json"
if [[ -f "${MANIFEST_FILE}" ]]; then
    sed -i -E "s/(\"version\"[[:space:]]*:[[:space:]]*\")[^\"]+(\")/\1${NEW_VERSION}\2/" "${MANIFEST_FILE}"
    echo "  ✓ Updated browser-extension/manifest.json"
fi

# 7. Update Kodi addon.xml
KODI_FILE="${ROOT_DIR}/sensors/kodi/service.biograph/addon.xml"
if [[ -f "${KODI_FILE}" ]]; then
    sed -i -E "s/(version=\")[^\"]+(\"[[:space:]]+provider-name=\"Biograph\")/\1${NEW_VERSION}\2/" "${KODI_FILE}"
    echo "  ✓ Updated sensors/kodi/service.biograph/addon.xml"
fi

echo "==> Biograph version successfully updated to ${NEW_VERSION} across all components."
