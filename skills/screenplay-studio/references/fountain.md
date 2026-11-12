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
- A scene heading starts a place: `INT. CAPTAIN'S CABIN - NIGHT #2#`. **It must start with `INT.`, `EXT.` or `INT./EXT.`** (or a leading dot, `.UNDERWATER - CONTINUOUS`): `UNDERWATER - CONTINUOUS` is not a scene. Spell a place the same way each time: the same place at another hour is one Scene. The `#2#` number is optional and keeps a scene's identity through revisions.
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

- A cue is **all capitals, alone on its line**. **Never put a capitals line above action text:** the import makes it a speaker, and that person reads the action aloud. Write a loud word inside a sentence (`a deafening CRUNCH`) and give the sound its own `[[Sound:]]` note: a line that is only capitals is read as a cue or a heading, never as a sound. If a line of capitals must be action, start it with `!` (`!THE PLAGUE OF THE SEA RISES.`).
- A blank line between speakers. No dual dialogue (`^`) unless two voices must overlap.
- The parenthetical is the delivery note (kept with the line).
- A beat holds at most 6 lines; the next starts a new one.

## 6. Pictures, timing and transitions

- Each action paragraph is part of a **picture** (one still). Action right after speech starts a new one. A paragraph is cut after about 420 characters.
- **`===` on its own line always starts a new picture.** Use it when the camera, place or subject changes inside one scene. One picture is one moment, not one per sentence.
- A silent picture plays 4 seconds. To change it: `[[Hold: 1.5s.]]` on its own line inside that picture. A picture with speech lasts as long as the take. Put no pause after every line.
- Transitions go on their own line, in capitals, with a colon: `CUT TO:`, `DISSOLVE TO:`, `CROSSFADE TO:`; the last line may be `FADE OUT.` A transition belongs to the picture that comes after it.
- A title over a picture: `SUPER: THE DEVIL'S SHOALS` as an action line.

## 7. Sound

- Name each sound yourself: `[[Sound: timber grinding against rock at 0.4s.]]` (seconds into the picture; leave `at` off for the start). Describe the **sound**, not the story: "a single sharp splash", not "Chet falls in". When a picture has `[[Sound:]]` notes, only those are made.
- Without a note, the import reads `the sound of X`, `a X sound` and a loud capitalised word, and keeps the sentence as the prompt.
- Lyrics start with `~`; they become one music Sound.
- Rain, thunder, wind and waves in a place's action make its **ambience** bed. Describe the weather once per place.
- The score is a placeholder made for every story: delete it if there is none.

## 8. Notes

`[[ anything ]]` is removed before pictures, narration and subtitles, so it is safe for comments. Only `Hold:` and `Sound:` notes are acted on. A note must have no blank line inside. Do not put story in a note.

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
7. Run the import as a **preview**: it reports chapters, beats, lines, Characters, scenes, sounds, and what the story still lacks (World, Setting, Premise), before anything is made.

## 11. Editing a Fountain with an AI

Give the AI this page and say: *keep every title-page line, every `#` act line, every `=` synopsis, every scene number, and every paragraph and line you were not asked to change, word for word*. Unchanged paragraphs keep their picture and recording when the revision is checked; reworded ones are flagged. Ask for the whole file back, as plain text, then make a **Revision** in Marvin: *check* it, read the report, *apply* it. For a rewrite where little of the old text is left, set the revision to `replace`.
