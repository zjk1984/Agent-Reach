#!/usr/bin/env bash
# OpenlibExtended launcher — works without libfuse2 (Ubuntu 24.04+)
export APPIMAGE_EXTRACT_AND_RUN=1
exec /home/zjk/.local/bin/OpenlibExtended.AppImage "$@"
