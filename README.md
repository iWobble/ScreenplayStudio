# Screenplay Studio

Take a story from an idea and a screenplay to a narrated, illustrated video, in a [Marvin](https://github.com/InnerOpen/marvin) workspace. Marvin keeps the story, its cast, its lines and the approvals; Screenplay Studio is what makes them work together: a **package** of record types and workflows, **workers** that do the heavy jobs (ffmpeg, transcription, the screenplay), a **container image** that holds them, and **skills** that teach an AI assistant the format and the flow.

It is the pipeline, not any one world. A *world* (for example Storyworld, a recurring miniature cast) is just records inside it: a `world`, its actors, its stories.

```
idea -> screenplay (Fountain) -> Marvin records -> casting -> stills + voices -> filmstrip (approve) -> video
```

## What is here

| | Where | What |
|---|---|---|
| **Package** | `docs/screenplay-studio.marvin-package.json` | The record types (story, series, chapter, beat, speech line, actor, character, casting, voice, sound...), collections and workflows. Install it from a file in Marvin (Settings -> Automation -> Packages). |
| **Workers** | `render/` (`storyrender`), `transcribe/` (`storytranscribe`) | The job kinds: `audio-cut`, `filmstrip`, `render`, `script`, `import-beats`, `import-voices`, `transcribe`. They only reach *out* to Marvin and poll for `job` records. |
| **Image** | `docker/` | One image, `screenplay-studio-worker`, tagged with the package version it goes with, and a compose file that runs it as two containers. Published to this repository's container registry. |
| **Skill** | `skills/screenplay-studio`, `.claude-plugin/` | The Marvin flow, casting one actor across ages. Installable as a Claude Code plugin. |

## The idea in one paragraph

The story's Fountain is the one place the content is written: by you or by an AI, as one Fountain document. `import-beats` cuts it, with no AI, into chapters, beats and spoken lines (each holding its own piece of the text), and makes a Character for each speaker, a Scene for each place and a draft Sound for each sound the words call for; a re-run adds what is missing and never rewrites what exists. The Script job writes it back out as written, or complete (every detail the records hold). Casting, stills, voices, the filmstrip approval and the render follow from the records.

## Quick start

1. **Package:** install `docs/screenplay-studio.marvin-package.json` into a Marvin workspace (it creates what is missing and never overwrites). Needs a Marvin with packages.
2. **Workers:** see [docker/README.md](docker/README.md). Build or pull the image, put a workspace-pinned token in an env file, `docker compose up -d`.
3. **Skill:** in Claude Code, `/plugin marketplace add iWobble/ScreenplayStudio` then `/plugin install screenplay-studio@screenplay-studio`.

## Status

Built and used on one real story. Known rough edges: package upgrades do not change record types that already exist (a new field is added to a live type by hand); the generic Marvin worker the image is built on is a separate repository; image generation and voices go through Marvin's OpenAI Images and ElevenLabs integrations and cost credit, so every spend asks for approval first.

## Tests

```
cd render && uv run --with pytest --with-editable . --with-editable ../../MarvinWorker python -m pytest
cd transcribe && uv run --with pytest --with-editable . --with-editable ../../MarvinWorker python -m pytest
```

(`MarvinWorker` is a checkout of the generic Marvin worker next to this repository.)

## Licence

MIT. See [LICENSE](LICENSE).
