# Actors and characters

Two things, kept apart. An **actor** is a person in the world's troupe: the look that stays the same in every role. A **character** is that actor in one story: a role, a costume and props. The same actor can play a different character in the next story. A peg leg or a false beard is a costume or prop of the character; the actor keeps both legs and a bare face.

## The actor sheet

One image: four full-body views of the actor in plain baseline clothes (front, three-quarter, right-side profile, back), same neutral pose, scale and light, warm cream background, no text or labels. Make it from the base in `assets/adult-bases.jpg` (woman or man) for construction and the approved rendering anchor for style. Small dark oval eyes, tiny mouth, minimal nose; simplified rounded hands and two natural legs unless the actor really differs.

**Name the file for the actor: `Nell.png`, not `image-3.png`.** In Marvin, "Create entry from asset" turns the file name into the actor's name and slug, so the right name has to be on the file before it is uploaded. Say the preferred file name at the top of every prompt handoff.

In Claude Code the default is a prompt handoff (see SKILL.md): `cast/<Name>.prompt.txt`, with the anchors to attach listed at the top. Save the result as `cast/actors/<Name>.png`, inspect it, then upload it.

## Bases belong to the world

A base is the general figure an actor is made from. Storyworld's two adult bases are in `assets/adult-bases.jpg`. Children (the twins) need their own girl and boy bases, since child proportions are not a smaller adult; animals, or anything else a world has, need theirs. Make each base as a front, side and back sheet in the world's style, list it in the world's `bases`, and only then make actors from it.

## The actor record

Fill these `actor` fields in Marvin from the sheet and the brief. Leave a field empty rather than guess; an age is a proposal until Jared confirms it.

| Field | What goes in it |
|---|---|
| `title` | the actor's name (the slug is the name in lower case: `nell`) |
| `world` | the world's slug, e.g. `storyworld` |
| `base` | the general figure it was made from: one of the **world's bases** (Storyworld has woman and man from `adult-bases.jpg`; children need girl and boy bases, and another world would have its own, say a dog or a cat). A world lists its bases in its `bases` field, each with a base sheet |
| `presence` | `on screen`, or `voice only` for a voice actor (no picture is made; a placeholder stands in) |
| `age` | years, only when set |
| `build`, `hair`, `skin_tone` | one line each. Skin tone describes the artwork, not ethnicity |
| `look` | the general look: the face and manner that stay the same |
| `distinguishing_features` | what picks them out in a lineup (a beard, an earring, a hairstyle). Not costume |
| `baseline_wardrobe` | what they wear in this plain sheet. A role's costume replaces it |
| `general_view` | the actor sheet picture |
| `voice`, `voice_sample` | their default voice (a voice record's slug) and a clip to hear it |
| `summary`, `description` | one line ("An older adult woman with a sturdy build and a calm, attentive presence.") and one sentence of what the picture shows ("A rounded Storyworld miniature character with warm medium-brown skin, short silver curls, and a simple, softly rendered face."). No age unless confirmed |
| `status` | `draft` until the sheet is approved |
| `notes` | anything else that is established, e.g. "Twin of Maya" |

Do not put story role, family relationships or personality on the actor from how they look. Only established facts (the twins) are recorded.

## The character sheet

A character is made from an actor, not from scratch. Attach the actor's `general_view` (download it from the actor's asset URL, or use the file in `cast/actors/`) as the identity anchor, then dress them for the role: the same four views, same pose and light, with the role's **costume** and **props** from the character record and any state change (age, injury, beard) as the brief says. The actor's face, build and proportions do not change.

File name: the character's id, `pirate-captain.png`. Show it for approval before anything depends on it; the approved picture is the character's `master`. A character with `presence: voice only` (a narrator) has no picture and needs no sheet.

Character fields: `story`, `actor` (the actor's slug), `role`, `speaker` (the name its speech lines use), `presence`, `costume`, `props`, `master`.

## Reading what is in Marvin

`marvin platform entries get <slug>` returns an actor's or character's fields and its attached pictures with their URLs. Download the picture to attach it as a reference; do not describe it from memory.
