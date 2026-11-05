#!/usr/bin/env bash
# Build the Screenplay Studio worker image, tagged with the package version it goes with (docs/screenplay-studio.marvin-package.json).
# The generic base is built first from ../MarvinWorker.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
version="v$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$here/docs/screenplay-studio.marvin-package.json")"
docker build -q -f "$here/../MarvinWorker/docker/Dockerfile" -t marvin-worker-base "$here/../MarvinWorker" >/dev/null
revision="$(git -C "$here" rev-parse --short HEAD)$(git -C "$here" diff --quiet HEAD -- . 2>/dev/null || echo -dirty)"
docker build -f "$here/docker/Dockerfile" --build-arg STUDIO_VERSION="$version" --build-arg STUDIO_REVISION="$revision" -t "screenplay-studio-worker:$version" -t screenplay-studio-worker:latest "$here"
echo "built screenplay-studio-worker:$version at $revision (also :latest)"
