# The Screenplay Studio worker: ONE image holding every kind of job the Screenplay Studio package (docs/screenplay-studio.marvin-package.json)
# hands to a worker. The chain (Media package design §6, P6): the generic Marvin worker (`marvin-worker-base`, from InnerOpen/marvin-worker)
# -> the Media worker (`marvin-media-worker:mN`, from InnerOpen/marvin-media: ffmpeg, faster-whisper + av, and `mediajobs`, whose ffmpeg,
# audio-measure, waveform, video-describe and model helpers Studio's code imports) -> this image, which adds the `storyrender` jobs (audio-cut,
# script, filmstrip, import-voices, import-beats, render...) and the `storytranscribe` ones (transcribe, time-words, transcribe-clip). Which
# kinds a container offers is chosen at run time with WORKER_KINDS, so one image serves the light jobs and the heavy transcribing in separate
# containers (see docker/compose.yml). The image is tagged with the package version it goes with.
# Build with docker/build.sh (the build context is the repository root); MEDIA_VERSION names the Media image it builds on.
ARG MEDIA_VERSION=latest
ARG MEDIA_IMAGE=marvin-media-worker
FROM ${MEDIA_IMAGE}:${MEDIA_VERSION}

USER root
# screenplain + reportlab: the screenplay (Fountain -> PDF in Courier 12, and HTML), pure Python so no browser is needed. pillow: stills.
# ffmpeg, faster-whisper and av come with the Media image.
RUN pip install --no-cache-dir screenplain==0.12.0 reportlab==5.1.0 "pillow>=10"
# /models keeps the transcription model across restarts (mount a volume; the Media image made it); /out keeps full-quality renders (mount a folder).
RUN mkdir -p /models /out && chown 1001 /models /out
COPY render/storyrender ./storyrender
COPY transcribe/storytranscribe ./storytranscribe

ARG STUDIO_VERSION=dev
ARG STUDIO_REVISION=unknown
LABEL org.opencontainers.image.title="screenplay-studio-worker" org.opencontainers.image.version="${STUDIO_VERSION}"
USER 1001

# The base reads MARVIN_API_URL, MARVIN_USER_TOKEN (and WORKER_NAME, WORKER_KINDS, WORKER_POLL_SECONDS) from the environment. WORKER_IMAGE, WORKER_VERSION and
# WORKER_REVISION say which image this is: a container cannot see its own image name, so it is baked in, and the heartbeat reports it to Marvin's Workers page.
# MEDIA_VERSION (which Media image this is built on) comes from the Media image. mediajobs.jobs is loaded too, so a kind name Studio and Media
# both define stops the worker at start (marvin-worker refuses a duplicate) instead of one silently replacing the other; whether this image's
# containers OFFER the media-… kinds is WORKER_KINDS' choice (docker/compose.yml: they do not, the Media container does).
ENV WORKER_JOB_MODULES=mediajobs.jobs,storyrender.jobs,storytranscribe.jobs \
    HF_HOME=/models WHISPER_MODEL=small \
    STUDIO_OUT_DIR=/out STUDIO_VERSION=${STUDIO_VERSION} \
    WORKER_IMAGE=screenplay-studio-worker WORKER_VERSION=${STUDIO_VERSION} WORKER_REVISION=${STUDIO_REVISION}
