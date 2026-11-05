# The transcription worker: the generic Marvin worker (`marvin-worker-base`, from ~/code/MarvinWorker) plus faster-whisper, which turns
# speech into text on the CPU (free, no service). It offers one kind of job (`transcribe`) and is a runner: it only reaches out to Marvin.
# Build the base first:  docker build -f docker/Dockerfile -t marvin-worker-base ../../MarvinWorker
FROM marvin-worker-base

USER root
RUN pip install --no-cache-dir faster-whisper==1.2.1 "av>=14,<17"
# The model is downloaded on first use and kept here, so mount a volume on /models to keep it across restarts (a named volume takes this owner).
RUN mkdir /models && chown 1001 /models
COPY storytranscribe ./storytranscribe
USER 1001

ENV HF_HOME=/models WORKER_JOB_MODULES=storytranscribe.jobs WHISPER_MODEL=small
