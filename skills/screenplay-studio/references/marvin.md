# Running the pipeline in Marvin

When the story lives in a Marvin workspace (my-studio on your-marvin.example.com), **the records are the source of truth**, not `stories/<slug>/` files. The file route in pipeline.md is the fallback for when no workspace is reachable. Reach the workspace with the CLI: `marvin --workspace my-studio platform ...`. Image and voice generation run through Marvin's integrations (OpenAI Images, ElevenLabs), each behind an approval Jared gives in Marvin. This replaces "Claude writes, Jared generates" for stills and voice.

## Which record holds what

| Record (entry type) | Holds | Rule |
|---|---|---|
| `world` | style rules for every picture | one place; never repeated into prompts by hand |
| `story` | premise, `script` (markdown), format, status | `status`: script, voices, rough-cut, final, published |
| `cast-member`, `casting` | who a person is and their approved master; `casting` is that person's role and state in one story | a master must be approved before a still uses it |
| `scene` | place, light, set dressing, continuity, `anchor` picture, ambience (and whether it is muffled) | every beat in the scene inherits it; put recurring props (the letters on the table) here, not in each beat |
| `beat` | one moment: shot, cast in frame, `expression`, `focus` prop, `references`, `lead_seconds`/`gap_seconds`/`tail_seconds`, `sounds` | status queued, made, approved |
| `still` | the request and the picture made from a beat | |
| `speech-line` | what is spoken (`text` is the source; `direction`, `delivery_text`, `caption`, `stability`, `similarity_boost`, `style`, `speed`, `take_notes`), its voice, its takes | the script and beat sheet are copies of this |
| `voice` | an ElevenLabs voice id | free tier cannot use library voices; premade ones work |
| `sound` | a reusable sound (`kind` effect or ambience, `source`, optional `story`), tagged | **library item**: any story's beat or scene may name it by slug |
| `job`, `job-kind`, `worker` | heavy work queued for a worker (the audio cut), what runs it, who is alive | see Workers |

There is no entry-to-entry reference field: a child holds its parent's **slug** as text (a list as comma text or JSON). Check the slug before writing it.

## Stage by stage

1. **Brainstorm and script**: create or update the `world` and `story` records, not just `worlds/<slug>.md`.
2. **Beats**: one `beat` record each, with its `scene`, cast IDs and states, and the previous beat's outcome. Scarce props still never replenish.
3. **Stills**: **do not hand-write a still prompt.** A prompt written by hand misses the letters, the daylight, the continuity (this happened on beat 04). The still workflows compose it from the world, scene, beat and cast records, and attach the references in order: scene `anchor`, cast masters, beat `references`. To change a picture, change the record (an `expression` that is too soft, a missing prop on the scene) and redo, not the prompt. Judge every picture by eye against the masters and the scene before approving. A master's smile survives a prompt asking for another face, so state a flat expression on the beat and expect to need a better reference.
4. **Lines and sounds**: set a `speech-line` or `sound` to status `queued`. That runs `storyworld-take-line` or `storyworld-take-sound`: one spend approval, generate, attach the take, then keep or redo. **Redo sets status back to queued** and runs only that item; approved ones are untouched. `storyworld-record-lines` does the next 25 lines under one approval. Listen before approving; an approval plays the take.
5. **Listen**: the `storyworld-audio-cut` workflow creates a `job`; a worker stitches narration, sounds and the scene ambience (loud outside, low-passed and quiet inside, continuous across beats) into one cut with a timeline. Jared listens, names a line, and the fix goes into that `speech-line` or `beat`, then a new cut.
6. **Shots, render, publish**: assembly and the YouTube upload stay outside Marvin's records for now (`render/`). **Never publish to YouTube without Jared's say-so; uploads are private only.**

## Workers

Heavy jobs run on a generic worker (`InnerOpen/marvin-worker`): a standing runner that registers the kinds it can do, or a dispatcher that starts one per job. Kinds declare what they take, give and need, and a bad job fails at once with the reason. This repo's `render/` registers `audio-cut`. Settings -> Workers shows who is alive, what each kind takes, the queue, and each job's log and result.

## Rules that cost us time

- One approval covers every paid call after it in a run; a repeat cannot hold its own approval, and repeats take at most 25 items. Word the approval with line and character counts, and check usage on the free ElevenLabs tier (10,000 characters per period).
- Say "no alphabet characters, signs or captions" in a picture rule, never "no letters": letters are props.
- After any upload, check the stored `mimeType`; a call can succeed and store the wrong type.
- Library first: before making a sound, scene or voice, look for one that already exists (tags say what it is, collections group packs).

## The package

All of this (the 15 entry types and the 11 `storyworld-*` workflows) is one Marvin **package**, `storyworld`: in my-studio it shows as one collapsed "Storyworld" section on the Workflows page and under Automation -> Packages. `docs/storyworld.marvin-package.json` is the same package as a file. To use Storyworld in another workspace: Automation -> Packages -> Add a package, choose that file, read the preview, install, then "Turn on workflows" (they arrive off, and need the `elevenlabs` and `openai_images` integrations, which they name). Installing never overwrites. After changing a workflow or record type here, rebuild the file from Automation -> Packages (build from this workspace, pick the same items, "group them here") and commit it, so the file and the live package do not drift.

The three record types workers use (`job`, `job-kind`, `worker`) are core's "Workers" blueprints now (Settings -> Workers -> Set up workers, or `marvin platform workers setup`); this package also carries them, so it installs on its own and says "exists" for any that core already added.

**Direction on a speech line.** `direction` is how a line should sound and feel, in plain words ("tired, a little amused, almost to herself"). The voice cannot read it: Claude turns it into the voice settings (`stability` lower is more expressive, `style`, `speed`) and, for the v3 model, into `delivery_text`, the same words with tags like `[sighs]`, `[whispers]`, `[pause]`. A line with `delivery_text` is recorded by `storyworld-take-line-tagged` (model `eleven_v3`, asks the same approval); one without is recorded by `storyworld-take-line`. Captions always use `text`, never `delivery_text`. `take_notes` stays the record of what sounded wrong and what was changed (a take workflow also writes a line there when it records). Every recording is attached to the line with the role `take`, so earlier takes stay on the line to compare; the `audio` field is the one the Audio cut uses. Punctuation changes delivery: a full stop, comma or ellipsis in `text` or `delivery_text` shifts the pacing and weight, so try the line with and without before reaching for tags. Check one short line before a whole story: v3's accepted settings and the caption word timings against tagged text are not yet confirmed.

**Captions follow the voice.** Both take workflows save the voice's word timings in `words`; the Audio cut and the render pass them on so captions are timed to each word (a caption override, or `caption` different from `text`, gets none and is spread by length; a v3 tag like `[sighs]` is never shown). Takes recorded before this have no `words` and fall back to the even spread: record the line again to get timings.
