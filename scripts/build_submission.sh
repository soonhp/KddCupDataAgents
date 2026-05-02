#!/usr/bin/env bash
set -euo pipefail

TEAM_ID="${TEAM_ID:-team0000}"
VERSION="${VERSION:-v3}"
IMAGE_NAME="${TEAM_ID}:${VERSION}"
ARCHIVE_NAME="${TEAM_ID}_${VERSION}.tar.gz"
DOCKERFILE="${DOCKERFILE:-docker/Dockerfile}"

docker build -f "${DOCKERFILE}" -t "${IMAGE_NAME}" .
docker save "${IMAGE_NAME}" | gzip > "${ARCHIVE_NAME}"

ARCHIVE_BYTES="$(wc -c < "${ARCHIVE_NAME}")"
MAX_BYTES="$((10 * 1024 * 1024 * 1024))"
if [ "${ARCHIVE_BYTES}" -gt "${MAX_BYTES}" ]; then
  echo "Archive exceeds 10GB limit: ${ARCHIVE_BYTES} bytes" >&2
  exit 1
fi

echo "${ARCHIVE_NAME}"
