# The Screenplay Studio worker

One image, `screenplay-studio-worker`, holds every kind of job the Screenplay Studio package hands to a worker. It is tagged with the package version it goes with (`v33` for package v33), so you can always tell which image a package needs.

| Job kind | What it does |
|---|---|
| `audio-cut`, `filmstrip`, `render` | the rough-cut audio, the filmstrip page to approve, and the final video (kept on the story as `video`) |
| `script` | the screenplay: Fountain, PDF (Courier 12), HTML and a breakdown |
| `import-beats`, `sync-sheet` | a story's script into beats, lines and chapters, and back again |
| `import-voices` | the ElevenLabs voices into voice records |
| `transcribe` | a recording into text (faster-whisper, free, on the CPU) |

The workers only reach **out** to Marvin and poll for `job` records; nothing listens. Run one container for the light jobs and one for transcribing (a long transcription then never holds up a filmstrip); `WORKER_KINDS` chooses what each offers.

```
docker/build.sh                                  # builds marvin-worker-base (../MarvinWorker) then screenplay-studio-worker:v<package version>
mkdir -p ~/.config/screenplay-studio ~/screenplay-studio-out
cp docker/worker.env.example ~/.config/screenplay-studio/worker.env   # fill in MARVIN_USER_TOKEN; keep it out of the repository (chmod 600)
docker volume create transcribe-models
export STUDIO_ENV_FILE=~/.config/screenplay-studio/worker.env STUDIO_VERSION=v33 STUDIO_UID=$(id -u) STUDIO_GID=$(id -g)
docker compose -f docker/compose.yml up -d
docker logs -f desktop-runner                    # or desktop-transcriber
docker exec -it desktop-runner bash              # a shell inside it
```

- **Full-quality renders** are kept in `~/screenplay-studio-out` (the runner runs as your user so it can write there). Marvin gets a smaller 720x1280 copy by default, because its upload limit is 100 MB; `quality: full` uploads the 1080x1920 file when it fits.
- **The transcription model** is downloaded the first time and kept in the `transcribe-models` volume.
- **After changing the code**, rebuild with `docker/build.sh` and `docker compose up -d --force-recreate`. A running container keeps the code it was built with.
- Needs a Marvin workspace with the package installed and a token pinned to that workspace.
