---
name: screenplay-studio
description: Run Screenplay Studio, the story-to-narrated-video pipeline built on a Marvin workspace. Use for cutting a screenplay (Fountain or prose) into a beat sheet or shot list, importing beats into Marvin (import-beats, Refresh, sync-sheet), chapters and episodes of a series, casting actors who play one person at several ages (views tagged age-young, age-mid, age-old, make-master), transcribing a recording as the start of a script, the filmstrip approval and the render job, and running or debugging the workers and their container image.
---

# Screenplay Studio

Screenplay Studio is the pipeline, not any one world. A **world** (Storyworld is the first; another could be anything) is just records inside it: a `world` entry, its actors, its stories. This skill covers the pipeline; a world's own skill covers its look and its cast.

**In a Marvin workspace the records are the source of truth.** Read references/marvin.md first: what each record holds, the workflows, and the stages from idea to video.

- **Cutting a script into beats:** read references/beat-sheet-format.md. It gives the exact table, the rules for cutting, a worked example the tests check against the importer, and a prompt to give any AI. A beat is one picture with its words and sounds, the same as a shot-list row, not a plot beat.
- **One place to edit:** the story's `script` field. Update the beats from it with `import-beats` (Refresh adds, updates what nothing has been made from, moves what is gone to the Trash, keeps and flags anything with a picture or recording). After editing a single beat by hand, `sync-sheet` writes the script back, and refuses if both sides changed.
- **Casting:** read references/actors.md. One actor can play the same person at several ages; tag the actor's views `age-young`, `age-mid`, `age-old` and give each Character an Age.
- **Workers:** one container image, `screenplay-studio-worker`, tagged with the package version it goes with; see docker/README.md in the repository. A queued job that nobody picks up usually means no worker offers its kind: check Settings -> Workers.

Rules that cost time:
- Preview first (`import-beats`, `sync-sheet`, `render` accept a preview), and say what was done in your own words, not only what a job logged.
- Anything that spends credit (images, voices) is asked about first; nothing is published without the author's approval.
- Keep the skill in step with the code: the beat-sheet example is parsed by the importer in a test, so change the guide, the example and the test together.
