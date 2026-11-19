#!/usr/bin/env bash
# Build the Screenplay Studio worker image, tagged with the package version it goes with (docs/screenplay-studio.marvin-package.json).
# The chain: marvin-worker-base (../MarvinWorker) -> marvin-media-worker:mN (../MarvinMedia, a checkout of InnerOpen/marvin-media next to this
# one) -> screenplay-studio-worker:vN. By default the Media image is built first with ../MarvinMedia/docker/build.sh, which builds the base
# first from ../MarvinWorker (both checkouts on main). STUDIO_SKIP_MEDIA=1 builds on the marvin-media-worker:mN already on this machine
# instead; MEDIA_VERSION=mN picks another Media image than the one ../MarvinMedia's package names.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
media="$here/../MarvinMedia"
version="v$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$here/docs/screenplay-studio.marvin-package.json")"
media_version="${MEDIA_VERSION:-m$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['version'])" "$media/docs/media.marvin-package.json")}"
if [ "${STUDIO_SKIP_MEDIA:-}" != "1" ]; then
  "$media/docker/build.sh"
fi
docker image inspect "marvin-media-worker:$media_version" >/dev/null 2>&1 || {
  echo "no marvin-media-worker:$media_version on this machine: build it (../MarvinMedia/docker/build.sh) or name one with MEDIA_VERSION" >&2
  exit 1
}
revision="$(git -C "$here" rev-parse --short HEAD)$(git -C "$here" diff --quiet HEAD -- . 2>/dev/null || echo -dirty)"
docker build -f "$here/docker/Dockerfile" --build-arg MEDIA_VERSION="$media_version" --build-arg STUDIO_VERSION="$version" --build-arg STUDIO_REVISION="$revision" \
  -t "screenplay-studio-worker:$version" -t screenplay-studio-worker:latest "$here"
# Every kind loads (Studio's and Media's, no name twice: marvin-worker stops on a duplicate) and the render's helpers are Media's.
docker run --rm --entrypoint python "screenplay-studio-worker:$version" -c \
  "import storyrender.ffmpeg as f, mediajobs.ffmpeg as m; assert f is m; from marvin_worker import jobs; jobs.load_kinds()" >/dev/null || {
  echo "screenplay-studio-worker:$version does not load its kinds on marvin-media-worker:$media_version" >&2
  exit 1
}
echo "built screenplay-studio-worker:$version at $revision on marvin-media-worker:$media_version (also :latest)"
