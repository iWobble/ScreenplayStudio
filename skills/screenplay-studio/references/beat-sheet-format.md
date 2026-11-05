# The beat sheet format (what `import-beats` reads)

A **beat** is one unit of the story, shown as **one picture** with the words and sounds that go with it: what film people call a shot-list row or a storyboard panel. Beats come *after* the screenplay. Cutting a script into beats is a creative decision (where the picture changes), made by a person or an AI with a person approving; the importer only reads the result. Beats are not "story beats" in the plot-outline sense.

## The table

One Markdown table, one row per beat, these four columns in this order:

```
| Beat | Time | Audio | Single still / composition |
|---|---|---|---|
| 01 | 0–8s | Narrator: The captain ordered a feast. At dawn, they would attack. | Low-angle medium: Captain on the raised deck, rigging overhead; nobody else in frame. |
```

| Column | Rule |
|---|---|
| **Beat** | A number: `01`, `02`, ... Add one between 04 and 05 as `04a`; never renumber. Each number once. |
| **Time** | `start–endS` in seconds, e.g. `0–8s`, `8–12s`. Always write one. For a **spoken** beat estimate it from the words (about 2.5 words a second, plus a second at each end): the recording replaces it, because a spoken beat lasts as long as its audio. For a **silent** beat it is the real length (at least end minus start). Times run on continuously from `0s`, so the last beat's end is the length of the film. |
| **Audio** | Everything heard in this beat, in order: `Speaker: words.` for each voice, and `Sound: description` for a sound cue. Several voices in one cell are fine: `Narrator: He looked up. Cook: Your feast. Captain: Make do.` Leave it empty for a held picture, or write `No speech. Hold on the smile.` |
| **Single still / composition** | The one picture, as a director would brief it: shot size and angle, who is in frame (use the Characters' names), what they are doing, the one prop the frame is about. **Do not** describe the standing setting (the place, its light, its furnishings: the scene record brings those) and ask for **no written words** in the picture. Weather, light or place that is the *event* of the beat is the picture, so say what changes: `the sun is covered by a cloud and the water loses its sparkle`, `a wave breaks over the deck`. To reuse a picture, say so: `Same picture as 05, pushed in on the Captain's face.` |

### Speaker names and where a speaker ends

- A speaker label is **one capitalised word and a colon**: `Narrator:`, `Cook:`, `Captain:`. No spaces, digits or hyphens (`Oldman` works, `OldMan` and `Old Man` do not; a role word is better: `Pilot`, not `Ship's Pilot`).
- **You choose the handles**, and list them (handle: who it is) above the table. Each handle becomes the `speaker` of one Character, so give one person at two ages two handles when they are two Characters (`Boy`, `Storyteller`), and set each Character's `speaker` to its handle.
- A label is recognised at the start of the cell, or after a sentence that ends with `.`, `?` or `!`. End each speaker's words with one of those, or the next label is missed.
- Words with no label in a table row are a note and are not spoken. A line that begins `No speech`, `No narration` or `No dialogue`, or is just `Silence.`, is a direction for a held beat. (Narration that merely starts with the word, `Silence fell over the deck.`, is spoken as written.)
- `Sound:` cues are listed in the job log and are **not** imported; sounds are placed from the library afterwards.
- Never put a `|` or a line break inside a cell.
- **Any capitalised word followed by a colon in the Audio cell is read as a speaker** (`Note:`, `Idea:`). In a note, put the colon after a lowercase word or write it in a parenthesis: `(narration wanted: the old man admits how far his thoughts went)`.

### Silent beats

- `No speech.` alone: a picture where something happens (a gesture, a wave, a walk) and nobody speaks.
- `No speech. Hold on the smile.`: a picture deliberately held. Both make a beat with no line.
- A sound can go with either: `No speech. Sound: gulls, wind, creaking rigging`. A beat that is only a sound is `Sound: a pot lid rattles`.
- **Do not invent words.** If the script has a place where someone should speak or the narrator should say something, and it does not, leave the beat silent and mark it `No speech. (narration wanted: what it should say)`. Writing new narration is the author's decision. A script with almost no dialogue gives a sheet that is mostly silent beats; that is expected.
- Indirect speech in the script (`he calls him an English dog`) stays in the picture cell as action, not as a line.

### Scenes, background people, and how many pictures

- **Mark scenes with a heading and one table each**: a `## Scene 3 - The Wages` line (`Chapter` or `Part` also work), then the table with its header row. Beat numbers and times continue across the tables. **Each heading is a chapter**: the importer makes a `chapter` record (`<story>-chapter-03`, titled `The Wages`) and puts the beats under it in it. Keep the title plain; an episode label such as `E01` is added when episodes are put together, not stored in the title. Beats above the first heading have no chapter.
- **Background people** (sailors, the surgeon, villagers) are named by role in the picture cell (`a sailor`, `the surgeon`). Only people who speak or recur need a handle and a Character.
- **Every beat is one picture to make.** A 12-minute story cut every 5 seconds is about 140 pictures. In a silent stretch prefer fewer, longer beats (8–12 seconds) with a camera push, and reuse a picture (`Same picture as 31, pushed in on ...`) where the moment stays on the same image.

## The other accepted form: numbered lines

The story's `script` field can hold the same thing without the table, one beat per line:

```
**01** — Narrator: The captain ordered a feast. At dawn, they would attack.
**02** — Narrator: Tonight, she said, they would eat like kings.
**03** — Narrator: The old cook checked his stores. Cook: Your feast. Captain: Make do.
**03a** — Sound: a pot lid rattles
```

Here words with no speaker are the narrator's, and a following line that starts `Name: words` continues the beat before it. This form has no picture or time, so pictures are added to the beats afterwards. The table is better when a person has already thought about the pictures.

## A worked example

<!-- example:start -->
## Scene 1 - The Feast

| Beat | Time | Audio | Single still / composition |
|---|---|---|---|
| 01 | 0–8s | Narrator: The captain ordered a feast. At dawn, they would attack a merchant ship twice their size. | Low-angle medium: Captain on the raised deck, rigging overhead; nobody else in frame. |
| 02 | 8–12s | Narrator: Tonight, she said, they would eat like kings. | Exterior establishing shot of the ship under cream sails; no recognisable people. |
| 03 | 12–20s | Narrator: The old cook checked his stores. Two scraps of pork. One onion. | Close on Cook's weathered hands holding a single onion over an almost empty crate. |

## Scene 2 - The Table

| Beat | Time | Audio | Single still / composition |
|---|---|---|---|
| 04 | 20–24s | Cook: Your feast. Captain: Make do. | Two-shot across the table, Cook left, Captain right, the onion between them. |
| 04a | 24–26s | Sound: a pot lid rattles | Same picture as 04, pushed in on Cook's face. |
| 05 | 26–34s | No speech. Sound: wind, creaking timber | A cloud covers the sun; the table and the onion turn cooler, Cook alone in frame. |
| 06 | 34–40s | No speech. (narration wanted: the cook admits how far his thoughts went) | Close on Cook's hand lifting a knife from the table and setting it down again. |
| 07 | 40–44s | No speech. Hold on the Captain's small smile. Cut to black. | Close on Captain's face, a small smile; nothing else in frame. |
<!-- example:end -->

## How to cut a script into beats

- **Start a new beat** when the picture changes: a new place, a different person speaking in an exchange, a new action, a reveal, or a prop that matters.
- **One idea per picture**: if it cannot be drawn in a sentence, split it.
- **Length**: narration runs about 2.5 words a second, so **4 to 8 seconds is roughly 10 to 20 words**. A long paragraph is two or three beats.
- **A quiet beat** (a held picture, no words) at the end of a scene or the story lets it land.
- **Reuse a picture** when a moment stays on the same image and only the words change; say "same picture as NN" and what to push in on.
- Keep the story's own facts: the order of events, what each person knows, props that were used up stay used up.

## Before importing

1. Every beat number appears once, in order, with `04a`-style numbers for insertions.
2. Every speaker label is one capitalised word and matches a Character.
3. Each speaker's words end in `.`, `?` or `!` before the next label.
4. Every row has all four cells and no `|` inside a cell.
5. Run the `screenplay-import-beats` workflow with **Preview** set to yes first; it says how many beats and lines it would make and what it left out.

## A prompt to give ChatGPT (or any AI) for the shot-list pass

Fill the two bracketed parts, then paste:

```
You are the storyboard artist for a narrated, illustrated vertical video (9:16). Below is the finished screenplay. Cut it into BEATS: one picture each, with the words and sounds that go with it. Return ONLY a Markdown table in a code block, with exactly these columns:

| Beat | Time | Audio | Single still / composition |

Rules:
- Put each scene under a heading line ("## Scene 3 - Title") with its own table and header row; one row per beat, numbered 01, 02, 03... continuously across the whole film (no gaps).
- Time: start–end in seconds, like 0–8s, running on continuously from 0s across the whole film. Spoken beats usually last 4–8 seconds (about 10–20 words, 2.5 words a second); a silent picture states its real length; in a long silent stretch prefer fewer, longer pictures (8–12 seconds) over many short ones.
- Audio: everything heard, in order. Write each voice as "Speaker: words." using ONLY these speaker names: [LIST OF SPEAKERS, one capitalised word each, e.g. Narrator, Cook, Captain]. End each speaker's words with . ? or ! before the next label. Write sound cues as "Sound: description". A silent picture is "No speech." (action) or "No speech. Hold on …" (held), optionally followed by "Sound: …". NEVER write new dialogue or narration that is not in the screenplay: where words seem to be missing, write "No speech. (narration wanted: what it should say)". Never use a capitalised word and a colon except for a real speaker or Sound.
- Single still / composition: one picture, as a director would brief it: shot size and angle, who is in frame (by their names; background people by role: "a sailor"), what they are doing, and the one prop the frame is about. Do NOT describe the standing setting (place, light, furnishings), but DO say what changes when weather or light is the event ("a cloud covers the sun"). Ask for no written words in the picture. To reuse an earlier picture write "Same picture as NN, pushed in on …".
- Start a new beat when the picture changes: a new place, a different person speaking, a new action, a reveal, or an important prop. One idea per picture. Do not cut or change the story; keep its order and its words.
- Never use the | character inside a cell, and never put a line break inside a cell.

SCREENPLAY:
[PASTE THE SCREENPLAY HERE]
```

## The script is the one place to edit

The table lives in the story's `script` field, and the beats, lines and chapters follow it (`import-beats`, Refresh). To change a single beat by hand, edit its record and run `sync-sheet` to write the script back; if both sides were edited since they last agreed it stops and names the beats instead of overwriting. Notes, sound cues and the text above the first scene heading survive both ways, so write them in the sheet freely.
