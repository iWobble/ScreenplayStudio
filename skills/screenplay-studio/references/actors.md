# Actors, characters and casting

Three records, kept apart. An **actor** belongs to the *world's troupe*: the look that stays the same in every role. A **character** (`cast-member`) is that actor in **one story**: a role, a costume and props. A **casting** is the search for who plays a role: the candidate actor, how well they fit, a screen test, and whether they were chosen or passed. The same actor can play a different character in the next story. A peg leg or a false beard is a costume or prop of the character, not part of the actor. The narrator can be a **voice-only** character with no picture.

## Bases belong to the world

A *base* is the general figure an actor is made from: proportions and silhouette. A world lists its bases in its `bases` field, each with a base sheet picture (`base_sheets`). Add a base only when making an actor from another one would look wrong (a different body, not a different person). Age within a base is the actor's business.

## The actor record

Fill the `actor` fields from the actor's picture and the brief. Leave a field empty rather than guess; an age is a proposal until the author confirms it.

| Field | What goes in it |
|---|---|
| `title` | the actor's name (the slug is the name in lower case) |
| `world` | the world's slug |
| `base` | one of the world's bases |
| `presence` | `on screen`, or `voice only` for a voice actor (no picture; use a shared featureless placeholder as the `general_view`) |
| `age` | years, only when set |
| `build`, `hair`, `skin_tone` | one line each. Skin tone describes the artwork, not ethnicity |
| `look` | the general look: the face and manner that stay the same |
| `distinguishing_features` | what picks them out in a lineup (a beard, an earring, a hairstyle). Not costume |
| `baseline_wardrobe` | what they wear in the plain sheet. A role's costume replaces it |
| `general_view` | the actor's sheet picture |
| `age_views` | more pictures of the same person at other ages (see below) |
| `voice`, `voice_sample` | their default voice (a voice record's slug) and a clip to hear it |
| `status` | `draft` until the sheet is approved |
| `notes` | anything else that is established |

Do not put story role, family relationships or personality on the actor from how they look. Only established facts are recorded.

**Name the picture file for the actor** (`Nell.png`, not `image-3.png`): in Marvin, "Create entry from asset" turns the file name into the actor's name and slug.

## The character record

A character is made from an actor, not from scratch. Fields: `story`, `actor` (the actor's slug), `role`, `speaker` (the one-word name its speech lines use in the beat sheet), `presence`, `age_state` (young, mid, old), `costume`, `props`, `rules` and `master` (the approved picture). Stills attach the approved master, so an unapproved master blocks them.

**`rules`** is what must hold in every picture of this one character (which side a peg leg is on; that the face matches the same person at other ages). The world holds only the style, so a rule about one person lives here; the still and master workflows put each character's costume, props and rules into the prompt.

## The casting record

`story`, `role`, `character`, `actor` (the candidate), `state` (what the role needs at that point), `fit` (why this actor does or does not fit), `status` (`considering`, `auditioned`, `chosen`, `passed`) and a `screen_test` picture. Search the troupe on the hard fields (presence, base, age range) first, then judge look and voice by eye and ear and write the verdict in `fit`. A role that fits nobody is a gap: make a new actor.

The **Casting call** guided setup (Setups) walks it for one story: pick the world and the story, list the roles (the characters), look through the troupe, shortlist actors for a role (each shortlisted actor is a casting record, with a note on the fit and an optional screen test; mark one Chosen and the others Passed), give the role to the chosen actor with the age and the costume and props, then make the role's master picture (it starts from the actor's pictures tagged for the role's age, so tag one `age-young`, `age-mid` or `age-old` first). Do the next role by picking it again. The Open call scouts the troupe first; Narrate a story brings in the script and beats.

## Reading what is in Marvin

`marvin platform entries get <slug>` returns an actor's or character's fields and its attached pictures with their URLs. Download the picture to attach it as a reference; do not describe it from memory.

## One actor, many ages (views tagged by age)

An actor has **Views at different ages** (`age_views`): as many pictures of the same person as you like, at other ages and angles. In the Assets library tag each one **`age-young`**, **`age-mid`** or **`age-old`**, and `face-closeup` or `profile` where it is one. A Character (`cast-member`) has an **Age** (`age_state`: young, mid, old). The **`screenplay-make-master`** workflow reads the Character's actor, collects up to four of the actor's pictures tagged for that age, and makes the master from them, the costume and props, and the world's style: it asks before spending image credit, then Keep or Redo, and Keep approves the master.

Rules that keep one man one man across 18, 30 and 52: put the features that never change (brow shape, nose, jaw, a scar, the hair parting) in `distinguishing_features` and keep them in every version; make the young and old masters early and approve them as a pair, side by side; a still takes the approved master, not the raw views (the plain actor sheet fights the costume), except a tagged `face-closeup` when a shot is a reuse of a face. A story that shows the same person at two ages has two Characters pointing at the same actor.
