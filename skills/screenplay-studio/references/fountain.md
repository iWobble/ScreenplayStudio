# Writing the Fountain: from an idea to a file the import reads completely

The story is one Fountain document. The import reads it with no AI and makes the chapters, beats, lines, Characters, scenes and sounds from it, so **what is not in the file is empty in Marvin**. This page says what to write so nothing is missing. Follow it when you write a Fountain from an idea, when an AI writes it, and when you ask an AI to edit one.

## 1. Before writing: answer these

If the idea does not say, decide (or ask) before writing a line. Each answer has a place in the file.

| Answer | Where it goes in the file | Becomes in Marvin |
|---|---|---|
| Title, who wrote it, where it comes from | title page: `Title`, `Credit`, `Author`, `Source` | the story's credits, printed on the script |
| One or two sentences: what the story is about | title page: `Premise:` | the story's **Premise** (the picture workflows read it) |
| Where and when it happens, in one sentence | title page: `Setting:` | the story's **Setting** |
| Format and length | title page: `Format:` | kept with the story |
| Who is on screen: name, age, sex, what they are, what they wear and carry, one thing that marks them | the first action line that brings each in | a **Character** (Role holds the sentences) |
| Who only speaks (narrator, announcer) | `NARRATOR (V.O.)` cue | a voice-only Character (no picture) |
| The places | scene headings | a **Scene** per place |
| What the story sounds like | `[[Sound: …]]` notes, weather words, `~` lyrics | **Sounds** to generate or upload, an **ambience** bed per place |
| What each part is about | `= synopsis` line under each scene heading | the chapter's summary, and the setting if none is given |
| How the story is divided | `# ACT …` lines | **chapters** |

The **World** (which look and rules the pictures follow) is not in the file: choose it on the story in Marvin. The import says when it is missing.

## 2. The title page

First lines of the file, `Key: value`, one blank line after. A value that needs several lines continues on lines indented by four spaces.

```
Title: THE DEVIL'S SHOALS
Credit: Written by
Author: Jared
Source: Original story
Draft date: November 2026
Format: Short Screenplay
Setting: A pirate brigantine wrecked on a cursed reef, one stormy night.
Premise: A ruthless captain and her cabin boy survive a wreck and meet the drowned crews of every ship the reef has taken.
Contact:
    Agent: Blackbeard Literary
    info@example.com
Copyright: (c) 2026 Jared. All rights reserved.
```

`Setting` and `Premise` fill the story's fields when they are empty. Without `Setting:` the import uses the first scene's synopsis, else the first place. **It never invents a premise**: with none, the import names it as missing. Keep every title-page line when an AI edits the file: they are lost easily.

## 3. Structure

- `# ACT I: THE WRECK` starts a **chapter** (use `# ACT II …`, `# ACT III …`, or numbered `## 03 The heist`). Without any `#` line the import cuts chapters by length (about 12 pages each, between two scenes), and a short script is one chapter, whose numbers turn clumsy (`00a`, `00b`…). Keep these lines in every revision.
- `## SCENE 2: THE REEF` is a label, kept as written.
- A scene heading starts a place: `INT. CAPTAIN'S CABIN - NIGHT #2#`. **It must start with `INT.`, `EXT.`, `EST.` or `INT./EXT.` (`EXT/INT.`, `I/E.` and `E/I.` work too)** (or a leading dot, `.UNDERWATER - CONTINUOUS`): `UNDERWATER - CONTINUOUS` is not a scene. Spell a place the same way each time: the same place at another hour is one Scene. The `#2#` number is optional and keeps a scene's identity through revisions.
- Under each heading write one synopsis line: `= Captain Valerie refuses to back down despite the cabin boy's pleas.` It becomes the chapter's summary.

## 4. Characters

Introduce each person **once**, in capitals, the first time they appear in the action, with their age and the sentences that say what they look like. The import copies those sentences into the Character's Role, reads the age and the sex (from the pronouns or a word like *boy*, *woman*, *lad* in them) into the Character's **Age** and **Sex** fields, and sets **Age state** (young under 30, mid under 55, old after) from the age, which picks the actor's picture of that age for the master. A Character made before these fields existed gets them on the next import, only where they are empty.

```
CAPTAIN VALERIE "THE VULTURE" VANE (40s) stands over the desk. She wears a rain-soaked tricorn hat and a long leather coat. One eye is clouded over with a cataract. She jams a compass into her belt.

CHET (20s), a young cabin boy, clutches a waterlogged logbook.
```

- Both `NAME (40s)` and `NAME, 40s,` are read. Use the first.
- Say the sex with a pronoun or a word, say what they wear and carry, and give one mark that tells them apart. **A costume the file never mentions is empty**, and the picture falls back to the actor's own clothes.
- A speaker the file never introduces gets a Character with only a name.
- A narrator or announcer is written `NARRATOR (V.O.)`; someone heard but not seen, `CHET (O.S.)`. Neither is in a picture.

## 5. Dialogue

```
CHET
(shouting over the storm)
The hull is groaning, Captain!

VALERIE
(sneers)
Drop anchor in a graveyard, boy?
```

- A cue is **all capitals, alone on its line**. **Never put a capitals line above action text:** the import makes it a speaker, and that person reads the action aloud. A sound is made only from a `[[Sound:]]` note (or `the sound of X`): a word or a line in capitals is never a sound, and a capitals line standing alone is read as action. If a line of capitals must be action, start it with `!` (`!THE PLAGUE OF THE SEA RISES.`).
- A blank line between speakers. No dual dialogue (`^`) unless two voices must overlap: `NAME ^` on the second speaker's cue, after a blank line, plays that line at the same time as the one before (v210).
- The parenthetical is the delivery note (kept with the line).
- A beat holds at most 6 lines; the next starts a new one.

## 6. Pictures, timing and transitions

- Each action paragraph is part of a **picture** (one still). Action right after speech starts a new one. A paragraph is cut after about 420 characters.
- **`===` on its own line always starts a new picture.** Use it when the camera, place or subject changes inside one scene. By default one picture is one moment, not one per sentence; to ask for more pictures, and say what each shows, use `[[Pic:]]` (below).
- A silent picture plays 4 seconds. To change it: `[[Hold: 1.5s.]]` on its own line inside that picture. A picture with speech lasts as long as the take. Put no pause after every line.
- Transitions go on their own line, in capitals, ending in `TO:`: `CUT TO:`, `DISSOLVE TO:`, `CROSSFADE TO:`. Any such line is a transition: one that names a dissolve or a fade is that, every other (`BACK TO:`, `FLASHBACK TO:`, `WIPE TO:`) is a cut with its words kept. A transition belongs to the picture that comes after it. `FADE IN:` before the first picture brings the film up from black; `FADE OUT.` after the last one takes it down to black. A transition never changes how long the film is.
- A transition's length: `[[Transition: 1.2s.]]` inside the picture it leads into (empty: the story's length, else 0.5 s).
- Something that happens at a word: a note among the words of a speech, `The hammer strikes [[Sound: clang | Camera: punch]] the wheel.` or `…in 1977, [[Pic: a small probe in dark space]] had needed…`. The voice and captions never read it; a Sound plays at the end of the word before the note, a Pic is a picture of its own that dissolves in at the word after it (v211).
- A line that should start earlier or later than it falls (an interruption): `[[Nudge: -0.4]]` on its own line right before the speaker (or right under the speaker's name). Seconds; a negative nudge overlaps the line before. It fills the line's *Nudge* (v209).
- **A card in the film** (`THREE YEARS LATER`, a chapter's title, `THE END`): centred text in a paragraph of its own, `> THE END <`. It is a beat that shows the words on the story's card colour, with no picture made for it. A second centred line under the first is a sentence under the title. A speech right after it is read over the card. It plays 4 seconds, or as long as its lines; `[[Hold: 2s.]]` changes that. Centred text inside a paragraph of action is still action.
- A title over a picture: `SUPER: THE DEVIL'S SHOALS` as an action line.

### One picture per sentence, or a picture you direct: `[[Pic: ...]]`

`[[Pic: Close on the coin in her fist.]]` on a line of its own starts a new picture, as `===` does, and its words become that beat's **Shot direction**: the field the still's prompt reads as where the camera looks, which a person (or an AI) can read and edit later. `[[Pic]]` or `[[Pic.]]` starts a picture with no direction. Every other Fountain app reads it as a note and ignores it, so the file is still an ordinary screenplay anywhere else.

- Use it in place of `===`, or beside one: a Pic note and a `===` written together are one break. It may sit right above the speaker or the action of its picture, with no blank line; but leave a blank line after a speech, since a Pic note right under a speech's last line is inside the speech, and only a note.
- Right under a scene heading (or above it) it directs the scene's first picture; it never makes a picture of the heading alone. With nothing after it (before `FADE OUT.`, or at the end) it makes no picture.
- Two Pic notes with nothing between them are one picture with the first one's words; the check says the second is ignored. A Pic note inside a speech, or in the middle of a line, is only a note (the check says so too).
- Keep it to the shot: where the camera is and what the frame holds, in a sentence. The check flags one over 400 characters.
- The note stays in the beat's own Fountain text. Rewording only a Pic note is not a revision of the beat; adding or removing one moves where pictures break, as adding or removing `===` does. An import fills Shot direction on a new beat, or on one whose field is empty; one a person wrote is never written over.

A picture for each spoken sentence:

```
[[Pic: Wide on black rocks in a storm, a wave vanishing between them.]]
Black rocks break the surface like teeth.

NARRATOR (V.O.)
There was a channel through the Devil's Shoals.

[[Pic: Medium wide: a lane of dark water between two rock walls.]]
Between two black walls of rock, a lane of dark water opens.

NARRATOR (V.O.)
Wide enough for a ship.
```

Every picture is a still to make (and pay for): count the Pic notes before you bring the story in. The import's preview says how many beats it would make.

### An info card and what stays changed: `[[Info card: …]]`, `[[Changes: …]]`

Two more notes belong to the picture they sit in, wherever in its text (under its Pic note, under its action, after its speech), each on a line of its own and outside a speech. They start and end no picture, and every other Fountain app ignores them as notes.

- `[[Info card: label | title | sentence]]` is the card shown over the picture: the beat's **Info card** label, title and sentence. Any slot may be empty (`[[Info card: | Day one | The fleet is alone.]]`), but one must have words. One slot alone is the **title**: `[[Info card: 2302]]`. Two slots are the label and the title.
- `[[Changes: the lead ship's hull is scorched black.]]` is the beat's **Changes from here on**: what stays changed in every later picture.
- An import fills them on a new beat, or on one whose field is empty; a value a person set is never written over (an info card is one thing: a beat with any of its three set keeps its own). A plain card's centred words are its card, so a note does not change them.
- One with no words, in the middle of a line or inside a speech is only a note: the check says so (worth a look).
- The *complete* script writes both notes back, so it reads back as the same beats.

The card over the first picture of a chapter:

```
# Chapter 4

EXT. INTERSTELLAR SPACE - 2302

[[Info card: CHAPTER 4 | 2302]]
[[Pic: Wide on three generation ships against the stars.]]

NARRATOR (V.O.)
Three ships left the old sun behind.
```

## 7. Sound

- Name each sound yourself: `[[Sound: timber grinding against rock at 0.4s.]]` (seconds into the picture; leave `at` off for the start). Describe the **sound**, not the story: "a single sharp splash", not "Chet falls in". When a picture has `[[Sound:]]` notes, only those are made.
- Without a note, the import reads `the sound of X`, `a X sound` and a loud capitalised word, and keeps the sentence as the prompt.
- Lyrics start with `~`; they become one music Sound.
- Rain, thunder, wind and waves in a place's action make its **ambience** bed. Describe the weather once per place.
- The score is a placeholder made for every story: delete it if there is none.

## 8. Notes

`[[ anything ]]` is removed before pictures, narration and subtitles, so it is safe for comments. Only `Hold:`, `Sound:`, `Pic:`, `Camera:` (among a speech's words), `Info card:`, `Changes:` and `Nudge:` notes are acted on (a Pic note starts a picture; the last two fill the beat's info card and changes: see section 6). A note must have no blank line inside. Do not put story in a note.

### What the *complete* script carries back (v204)

The *complete* script (Make the script, version complete) is made from the records and drops nothing the import was given:

- Your own notes come back where you wrote them: those under the title page (`[[Production: …]]`, `[[Visual style: …]]`, `[[Continuity: …]]`, `[[Timing: …]]`) after the title page, and each note in a picture (`[[Sentence: …]]`, `[[Silent on purpose: …]]`, `[[One picture: …]]`, a comment) in the same picture, above its Pic note, right under it, or after its lines, in the same order. A note inside a speech is the line's and is not carried. The notes the export writes itself (Pic, Beat, Scene, Ambience, Info card, Changes, Hold, Sound) are written from the records, never twice.
- A picture with a `[[Pic:]]` note has no `===` above it: the note starts the picture. A picture without one keeps its `===`.
- It reads back what it wrote: a scene's Place, Light, Set dressing and Continuity from `[[Scene <name>. Place: …. Light: …. Set dressing: …. Continuity: ….]]` (the scene the note names only), and a beat's Focus and Expression from `[[Beat NN. … Focus: …. Expression: ….]]`, both as the export writes them (each part once, in that order; otherwise the check says the note is not read). A new scene or beat takes them; one that exists only into an empty field, never over one a person set.
- Not read back yet: a beat's Camera, Cast and Note, and a scene's ambience level, from those notes; a field that had no final full stop comes back with one.

## 9. A skeleton

```
Title: …
Credit: Written by
Author: …
Source: …
Draft date: …
Format: …
Setting: …
Premise: …

# ACT I: …

## SCENE 1: …

EXT. PLACE - NIGHT #1#
= One sentence on what this scene does.

Establishing action in one or two sentences. NAME (30s), what they look like and wear.

[[Hold: 2.5s.]]

===

NARRATOR (V.O.)
One spoken line.

NAME
(how it is said)
Their line.

CUT TO:

INT. ANOTHER PLACE - CONTINUOUS #2#
= …

…

FADE OUT.
```

## 10. Check before you hand it over

1. Title page has Title, Credit, Author, Source, Draft date, Format, **Setting** and **Premise**.
2. Every `#` act line is there; every scene heading starts INT./EXT. and has a `=` synopsis.
3. Every person is introduced once, in capitals, with age, a sex word or pronoun, clothes and a mark.
4. No capitals line stands above action; no heading lacks INT./EXT. (the import's report, under **Check:**, names each such line by its number and says how to fix it: a capitals line alone or ending in a full stop is read as a speaker, so start it with `!`; a place-and-time line without INT./EXT. is not a scene)
5. Every silent picture that should not be 4 seconds has a `[[Hold:]]`; every sound that matters has a `[[Sound:]]`.
6. A page break `===` sits wherever the picture must change.
7. **Check it** (next section), then run the import as a **preview**: it reports chapters, beats, lines, Characters, scenes, sounds, and what the story still lacks (World, Setting, Premise), before anything is made.

## 11. Editing a Fountain with an AI

Give the AI this page and say: *keep every title-page line, every `#` act line, every `=` synopsis, every scene number, and every paragraph and line you were not asked to change, word for word*. Unchanged paragraphs keep their picture and recording when the revision is checked; reworded ones are flagged. Ask for the whole file back, as plain text, then make a **Revision** in Marvin: *check* it, read the report, *apply* it. For a rewrite where little of the old text is left, set the revision to `replace`.

## 12. Check it before it is read

The import reads a Fountain the way the format says, and a slip in the writing is not an error to it: a speaker in lower case is action, a note left open is ignored, two scenes with one number are one, a transition without its colon is a line of the story. Each reads fine and means something else. **Check the Fountain** finds those before anything is made, each with its line and what to write, and costs nothing: it reads the text only.

- **In the Narrate a story setup:** the step *Check the Fountain*, before the split; its report shows under the button. It writes the report in the story's **Fountain check**. Nothing needs approving. An uploaded file can be read on *Story details* (*Read the file*, under the file, with the report's line numbers; the address `#L17` opens it at line 17) but not edited in Marvin: fix it where it came from, then choose or upload it again under *Fountain file* and check again.
- **From the command line, no Marvin needed:** `python -m storyrender check file.fountain` (or `-` for standard input; `--json` for data). It prints what it found, its first line saying whether the import would stop or go ahead, and exits 1 when the import would stop. In the worker image: `docker run --rm -i screenplay-studio-worker python -m storyrender check - < file.fountain`.
- **Through Marvin** (the Marvin CLI, the web app, or an AI over MCP): run the workflow *Screenplay: check some Fountain text* with the text, or *Screenplay: check the Fountain* on a story; both make a `job` of kind `check-fountain` (also queued directly: `args.text`, `args.asset`, or `args.story`). The job's `result` holds `errors`, `looks`, `import_stops`, `report` and `findings`. **An AI writing a Fountain should check it this way before handing it over, fix every error, and check again until there are none.**
- **The import itself** stops on the serious ones (a speaker in lower case that is also written in capitals elsewhere, a note or a bracket left open, a scene number used for two places, a transition with no colon, a Hold or Sound time that is not a number, a section with no title, a heading with no place) and lists them. A preview (dry run) and a revision check only report. To go on anyway, run the import with `accept_errors: yes`. The capitals warnings (a lone line in capitals, a heading with no INT./EXT.) were warnings before and still are: the report lists them, every one, under *Worth a look*.
- **Worth a look, not mistakes:** no title page, no Setting or Premise, a one-word lower-case line above a sentence (a speaker?), a speaker spelled almost like another, characters you cannot see that change how a line reads (a direction mark or a control character; a non-breaking or zero-width space is read as the space it looks like), a stray `===` or `]]`, `>centered<` text (alone it is a plain card, which may be what you want; inside a paragraph it is action).

