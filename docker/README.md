# The Screenplay Studio worker

One image, `screenplay-studio-worker`, holds every kind of job the Screenplay Studio package hands to a worker. It is tagged with the package version it goes with (`v33` for package v33), so you can always tell which image a package needs.

| Job kind | What it does |
|---|---|
| `audio-cut`, `filmstrip`, `render` | the rough-cut audio, the filmstrip page to approve, and the final video (kept on the story as `video`) |
| `script` | the screenplay: Fountain, PDF (Courier 12), HTML and a breakdown |
| `import-beats`, `sync-sheet` | a story's script into beats, lines and chapters, and back again |
| `import-voices` | the ElevenLabs voices into voice records |
| `convert-audio` | a recording a browser made (webm, ogg) into an mp3 or m4a, and the entry's field pointed at it |
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

## Which image is running

A container cannot see its own image name, so the image bakes it in (`WORKER_IMAGE`, `WORKER_VERSION`, `WORKER_REVISION`) and each worker's heartbeat reports it. Marvin's **Settings -> Workers** page shows it beside each worker (needs a Marvin that shows the fields); the worker records hold `image`, `version` and `revision` either way. A revision ending `-dirty` means the image was built from uncommitted changes. From the shell: `docker inspect desktop-runner --format '{{.Config.Image}}'`.

## Taking jobs by POST (optional, off by default)

The two workers poll Marvin and listen on nothing. The image can also be a standing worker that is *sent* jobs:

```
# put a long random WORKER_TOKEN in your env file, then:
docker compose -f docker/compose.yml --profile endpoint up -d endpoint
curl http://127.0.0.1:8080/health
curl -X POST http://127.0.0.1:8080/jobs -H "Authorization: Bearer $WORKER_TOKEN" \
     -d '{"kind": "import-beats", "job": "<an existing job record slug>", "args": {"story": "my-story", "dry_run": "yes"}}'     # 202 at once
```

It answers `202` and runs the job, writing the status, log and result onto the `job` record you name (it must already exist, and its status must not be `queued`, or a polling worker may take it first). It is bound to `127.0.0.1` only; Marvin's `request` step reaches public hosts only, so something must put a public address in front of it (a reverse proxy or tunnel) before a workflow can call it. Any of the eight job kinds can be sent.

