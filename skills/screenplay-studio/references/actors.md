# Actors and characters

Two things, kept apart. An **actor** is a person in the world's troupe: the look that stays the same in every role. A **character** is that actor in one story: a role, a costume and props. The same actor can play a different character in the next story. A peg leg or a false beard is a costume or prop of the character; the actor keeps both legs and a bare face.

## The actor sheet

One image: four full-body views of the actor in plain baseline clothes (front, three-quarter, right-side profile, back), same neutral pose, scale and light, warm cream background, no text or labels. Make it from the base in `assets/adult-bases.jpg` (woman or man) for construction and the approved rendering anchor for style. Small dark oval eyes, tiny mouth, minimal nose; simplified rounded hands and two natural legs unless the actor really differs.

**Name the file for the actor: `Nell.png`, not `image-3.png`.** In Marvin, "Create entry from asset" turns the file name into the actor's name and slug, so the right name has to be on the file before it is uploaded. Say the preferred file name at the top of every prompt handoff.

In Claude Code the default is a prompt handoff (see SKILL.md): `cast/<Name>.prompt.txt`, with the anchors to attach listed at the top. Save the result as `cast/actors/<Name>.png`, inspect it, then upload it.

## The actor record

Fill these `actor` fields in Marvin from the sheet and the brief. Leave a field empty rather than guess; an age is a proposal until Jared confirms it.

| Field | What goes in it |
|---|---|
| `title` | the actor's name (the slug is the name in lower case: `nell`) |
| `world` | the world's slug, e.g. `storyworld` |
| `base` | the general figure it was made from (`woman` or `man`) |
| `age` | years, only when set |
| `build`, `hair`, `skin_tone` | one line each. Skin tone describes the artwork, not ethnicity |
| `look` | the general look: the face and manner that stay the same |
| `distinguishing_features` | what picks them out in a lineup (a beard, an earring, a hairstyle). Not costume |
| `baseline_wardrobe` | what they wear in this plain sheet. A role's costume replaces it |
| `general_view` | the actor sheet picture |
| `voice`, `voice_sample` | their default voice (a voice record's slug) and a clip to hear it |
| `status` | `draft` until the sheet is approved |
| `notes` | anything else that is established, e.g. "Twin of Maya" |

Do not put story role, family relationships or personality on the actor from how they look. Only established facts (the twins) are recorded.

## The character sheet

A character is made from an actor, not from scratch. Attach the actor's `general_view` (download it from the actor's asset URL, or use the file in `cast/actors/`) as the identity anchor, then dress them for the role: the same four views, same pose and light, with the role's **costume** and **props** from the character record and any state change (age, injury, beard) as the brief says. The actor's face, build and proportions do not change.

File name: the character's id, `pirate-captain.png`. Show it for approval before anything depends on it; the approved picture is the character's `master`. A character with `presence: voice only` (a narrator) has no picture and needs no sheet.

Character fields: `story`, `actor` (the actor's slug), `role`, `speaker` (the name its speech lines use), `presence`, `costume`, `props`, `master`.

## Reading what is in Marvin

`marvin platform entries get <slug>` returns an actor's or character's fields and its attached pictures with their URLs. Download the picture to attach it as a reference; do not describe it from memory.
