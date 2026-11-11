---
name: screenplay-studio
description: Run Screenplay Studio, the story-to-narrated-video pipeline built on a Marvin workspace. Use for cutting a Fountain screenplay into chapters, beats, characters, scenes and sounds in Marvin (import-beats, Refresh), chapters and episodes of a series, casting actors who play one person at several ages (views tagged age-young, age-mid, age-old, make-master), transcribing a recording as the start of a script, the filmstrip approval and the render job, and running or debugging the workers and their container image.
---

# Screenplay Studio

Screenplay Studio is the pipeline, not any one world. A **world** (Storyworld is the first; another could be anything) is just records inside it: a `world` entry, its actors, its stories. This skill covers the pipeline; a world's own skill covers its look and its cast.

**In a Marvin workspace the records are the source of truth.** Read references/marvin.md first: what each record holds, the workflows, and the stages from idea to video.

- **Cutting a Fountain into beats:** the story is one Fountain document (written by you or by an AI) in its Fountain field. The import cuts it with no AI: a `#` section line is a chapter, a scene heading with its first action is a picture, each further action is another, a page break (`===`) always starts a new picture, and each speech is a spoken line. It also makes a Character for each speaker, a Scene for each place and a draft Sound for each sound the words call for. A beat is one picture with its words and sounds, the same as a shot-list row, not a plot beat.
- **One place to edit:** the story's Fountain. Bring it in again after changing it (Refresh adds, updates what nothing has been made from, moves what is gone to the Trash, keeps and flags anything with a picture or recording). The Script job with *version: complete* writes the records back out as a Fountain, and *written* writes the Fountain as it was written.
- **Casting:** read references/actors.md. One actor can play the same person at several ages; tag the actor's views `age-young`, `age-mid`, `age-old` and give each Character an Age.
- **Workers:** one container image, `screenplay-studio-worker`, tagged with the package version it goes with; see docker/README.md in the repository. A queued job that nobody picks up usually means no worker offers its kind: check Settings -> Workers.

Rules that cost time:
- Preview first (`import-beats` and `render` accept a preview), and say what was done in your own words, not only what a job logged.
- Anything that spends credit (images, voices) is asked about first; nothing is published without the author's approval.
