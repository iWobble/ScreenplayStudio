# The Storyworld media worker: the generic Marvin worker (`marvin-worker-base`, from ~/code/MarvinWorker) plus ffmpeg and this
# package's kinds of job (`audio-cut`). Build the base first:  docker build -f docker/Dockerfile -t marvin-worker-base ../../MarvinWorker
FROM marvin-worker-base

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY storyrender ./storyrender
USER 1001

# The base reads MARVIN_API_URL, MARVIN_USER_TOKEN and WORKER_TOKEN from the environment, and loads the kinds named here.
ENV WORKER_JOB_MODULES=storyrender.jobs
