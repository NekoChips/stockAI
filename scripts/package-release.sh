#!/bin/sh
set -eu
export COPYFILE_DISABLE=1

VERSION=${1:-0.1.0-mysql}
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT_DIR="$ROOT/dist"
PACKAGE_NAME="stockai-release-$VERSION"
ARCHIVE="$OUTPUT_DIR/$PACKAGE_NAME.tar.gz"

mkdir -p "$OUTPUT_DIR"
if [ -e "$ARCHIVE" ]; then
  printf '%s\n' "Release archive already exists: $ARCHIVE" >&2
  exit 1
fi
STAGING_DIR=$(mktemp -d "$OUTPUT_DIR/.stockai-stage.XXXXXX")
PACKAGE_DIR="$STAGING_DIR/$PACKAGE_NAME"
mkdir -p "$PACKAGE_DIR"
trap 'rm -rf "$STAGING_DIR"' EXIT

cp "$ROOT/Dockerfile" "$ROOT/.dockerignore" "$ROOT/docker-compose.release.yml" "$ROOT/docker-compose.yml" "$ROOT/pyproject.toml" "$ROOT/setup.py" "$ROOT/README.md" "$PACKAGE_DIR/"
cp -R "$ROOT/src" "$PACKAGE_DIR/src"
find "$PACKAGE_DIR/src" -name .DS_Store -delete
find "$PACKAGE_DIR/src" -type d -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$PACKAGE_DIR/config" "$PACKAGE_DIR/docker"
cp "$ROOT/config/default.yaml" "$ROOT/config/release.container.yaml" "$ROOT/config/release.example.yaml" "$PACKAGE_DIR/config/"
cp "$ROOT/docker/.env.release.example" "$PACKAGE_DIR/docker/"

if command -v xattr >/dev/null 2>&1; then
  xattr -cr "$PACKAGE_DIR"
fi

tar --no-xattrs -C "$STAGING_DIR" -czf "$ARCHIVE" "$PACKAGE_NAME"
printf '%s\n' "Release package created: $ARCHIVE"
