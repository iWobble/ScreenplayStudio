# storytranscribe

A second Marvin worker, in its own container, that turns a recording into text with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU. Free:
no service, no key. It offers one kind of job, `transcribe`, and only reaches out to Marvin (like the render runner), so it can run anywhere.

```
docker build -f ../../MarvinWorker/docker/Dockerfile -t marvin-worker-base ../../MarvinWorker   # the base, once
docker build -t storytranscribe-worker .
docker volume create transcribe-models                                                          # the model is kept here
docker run -d --name desktop-transcriber --restart unless-stopped \
  -e MARVIN_API_URL=https://your-marvin.example.com -e MARVIN_USER_TOKEN=… -e WORKER_NAME=desktop-transcriber \
  -v transcribe-models:/models storytranscribe-worker python -m marvin_worker work
docker exec -it desktop-transcriber bash     # a shell inside it; docker logs -f desktop-transcriber follows it
```

Run it from Marvin with the **Screenplay: transcribe a recording** workflow: the recording (an audio or video asset, by slug, name or id), optional
**hotwords** (names and unusual words to listen for; a nudge, not a rule) and the spoken language (empty detects it). The job keeps four files as
assets and names them on its result: the words (written line by line as they are heard, so a failure leaves what was heard), the words with times,
the words in paragraphs, and JSON. `WHISPER_MODEL` picks the model (default `small`; `base` is quicker, `medium` and `large-v3` more exact).
On 10 CPU cores `small` is about 4x real time (50 minutes of speech in about 13).

Tests: `uv run --with pytest --with-editable . --with-editable ../../MarvinWorker python -m pytest`.
