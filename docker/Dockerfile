# The Screenplay Studio worker: ONE image holding every kind of job the Screenplay Studio package (docs/screenplay-studio.marvin-package.json)
# hands to a worker. It is the generic Marvin worker (`marvin-worker-base`, from ~/code/MarvinWorker) plus ffmpeg, the `storyrender` jobs
# (audio-cut, script, filmstrip, import-voices, import-beats, sync-sheet, render) and the `storytranscribe` job (transcribe, faster-whisper on
# the CPU). Which kinds a container offers is chosen at run time with WORKER_KINDS, so one image serves the light jobs and the heavy
# transcribing in separate containers (see docker/compose.yml). The image is tagged with the package version it goes with.
# Build with docker/build.sh (the build context is the repository root).
FROM marvin-worker-base

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# screenplain + reportlab: the screenplay (Fountain -> PDF in Courier 12, and HTML), pure Python so no browser is needed.
# faster-whisper + av: transcribing. `av` is pinned because faster-whisper 1.2.1 breaks on a newer one.
RUN pip install --no-cache-dir screenplain==0.12.0 reportlab==5.1.0 faster-whisper==1.2.1 "av>=14,<17"
# /models keeps the transcription model across restarts (mount a volume); /out keeps full-quality renders (mount a folder).
RUN mkdir /models /out && chown 1001 /models /out
COPY render/storyrender ./storyrender
COPY transcribe/storytranscribe ./storytranscribe

ARG STUDIO_VERSION=dev
ARG STUDIO_REVISION=unknown
LABEL org.opencontainers.image.title="screenplay-studio-worker" org.opencontainers.image.version="${STUDIO_VERSION}"
USER 1001

# The base reads MARVIN_API_URL, MARVIN_USER_TOKEN (and WORKER_NAME, WORKER_KINDS, WORKER_POLL_SECONDS) from the environment. WORKER_IMAGE, WORKER_VERSION and
# WORKER_REVISION say which image this is: a container cannot see its own image name, so it is baked in, and the heartbeat reports it to Marvin's Workers page.
ENV WORKER_JOB_MODULES=storyrender.jobs,storytranscribe.jobs \
    HF_HOME=/models WHISPER_MODEL=small \
    STUDIO_OUT_DIR=/out STUDIO_VERSION=${STUDIO_VERSION} \
    WORKER_IMAGE=screenplay-studio-worker WORKER_VERSION=${STUDIO_VERSION} WORKER_REVISION=${STUDIO_REVISION}
