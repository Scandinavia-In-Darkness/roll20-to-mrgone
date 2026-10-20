# Character sheets

Turns Roll20 "Chronicles of Darkness" character exports into filled-in,
editable PDF character sheets, one per character, plus a clean YAML file of
each character's data.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python and the dependencies
  (`pypdf`, `fonttools`, `pyyaml`, listed in `requirements.txt` and
  `pyproject.toml`) the first time you run anything.

## Exporting from Roll20

The export files come from `export.js`, a Roll20 API script (Mod). Mods need
a Roll20 Pro subscription for the game's creator.

1. In the game's settings, open **Mod (API) Scripts**. Create a new script,
   paste in the contents of `export.js`, and save it.
2. In the game's chat, as a GM, run:

   ```
   !export-cofd 1
   ```

   This exports batch 1: the first 20 characters in alphabetical order. The
   chat replies with how many batches there are in total.
   Then run `!export-cofd 2`, `!export-cofd 3`, … until the last batch.
   Only GMs can run the command.
3. Each batch is written to the **API Output Console** at the bottom of the
   Mod Scripts page, between `=== START EXPORT BATCH n ===` and
   `=== END EXPORT BATCH n ===`. Copy everything from the START line through
   the END line into `input/batch<n>.txt`, one file per batch.

Good to know:

- The console prints each logged line as a quoted string, which is why the
  character data inside the file is JSON wrapped in a string. `map.py`
  unwraps it.
- Batches are counted alphabetically by name, so adding or renaming
  characters in Roll20 changes which characters land in which batch. Export
  all batches again in one go rather than mixing old and new files.
- The script exports each attribute's current value and skips empty ones.
  Values still at the sheet's default are not stored in Roll20 at all, so
  they are missing from the export too. `map.py` fills them in (see
  [Missing values](#missing-values)).
- Change `batchSize` in `export.js` to export more or fewer characters per
  batch.

## Quick start

1. Put the export files in `input/`, e.g. `input/batch1.txt`,
   `input/batch2.txt`, … Each file looks like:

   ```
   "=== START EXPORT BATCH 1 ==="
   "[{\"name\":\"...\",\"attributes\":{...}}, ...]"
   "=== END EXPORT BATCH 1 ==="
   ```

2. Run:

   ```sh
   uv run map.py
   ```

3. Find the results in `out/`.

Templates are downloaded into `templates/` automatically the first time a
character needs one. To download a template again, delete it from
`templates/`.

## What you get in `out/`

| File | Contents |
| --- | --- |
| `<sheettype>/<name>.pdf` | The character's filled sheet. The fields stay editable. |
| `<sheettype>/<name>.yaml` | The character's data, cleaned up and structured the same way for every template (see below). |
| `0-does-not-fit.yaml` | Every character with data that didn't make it onto their sheet, and what that data is. |
| `0-too-many.yaml` | Only the characters with more merits, specialties, dots or text lines than their sheet has room for. |

Sheets are grouped in one folder per sheettype, e.g. `vampire1/`, with
`none/` for characters without one. Characters with the same name and
sheettype get a numbered suffix, e.g. `vampire1/Ares (2).yaml`.
The two reports start with `0-` so they're listed first.

Both reports have the same format. `0-too-many.yaml` uses only the first four
sections:

```yaml
count: 55
characters:
- name: Akhenaten
  pdf: mummy1/Akhenaten.pdf     # null when the character has no sheet
  yaml: mummy1/Akhenaten.yaml
  template: MtC1-Page_Interactive.pdf
  reason: …                     # only when there's no sheet, e.g. "no sheet for sheettype 'demon'"
  lists:                        # lists longer than the sheet's rows
  - list: merits
    count: 14
    rows: 9
    left_out: ["- Alien Attractor", "+ Remote"]
  dots:                         # ratings larger than the sheet's dot track
  - {trait: health, value: 15, fits: 12}
  specialties: [Flamethrowers]  # specialties that name no skill
  text:                         # notes with more lines than the box
  - {field: flaws, lines: 5, fits: 3}
  notes:                        # Roll20 info panels
  - {title: …, text: …}
  unplaced:                     # data the sheet has no field for
    allies: …
    attacks: [{name: …, damage: 1}]
    other_traits: [{name: …, dots: 2}]
```

While it runs, `map.py` prints a yellow warning (to stderr) for every list
that overflows its sheet, e.g.:

```
warning: vampire1/Becki.pdf: 12 merits but only 10 rows; left out: Contacts(Taboras), Hollow
```

Set `NO_COLOR=1` to turn the colours off. To see only the warnings, run
`uv run map.py > /dev/null`.

## Sheets

| Export sheettype | Template | Downloaded from |
| --- | --- | --- |
| `vampire1` | `VtR1-Page_Editable.pdf` | `VtR/` |
| `werewolf1` | `Forsaken2-Page_Editable.pdf` | `WtF/` |
| `mage1` | `Awakening2-Page_Editable.pdf` | `MtANWOD/` |
| `changeling1` | `CtL_1-Page_Editable.pdf` | `CtL/` |
| `geist1` | `Geist1-Page_Editable.pdf` | `GtSE/` |
| `mummy1` | `MtC1-Page_Interactive.pdf` | `MtC/` |
| `hunter` | `HtV1-Page_Editable.pdf` (Hunter: The Vigil) | `HtV/` |

All templates come from <https://mrgone.rocksolidshells.com/pdf/>. Characters
with any other sheettype (currently `demon`, `promethean1`, `mortal2`) or none
(mortals) get a YAML file but no PDF, and are listed in `0-does-not-fit.yaml`.

### What goes on the sheets

- Name, chronicle, concept, virtue/vice and the template's identity
  slots (clan/bloodline/covenant, auspice/tribe/lodge, …).
- Attributes, skills, specialties (placed on their skill's line), merits, the
  power stat (Blood Potency, Gnosis, …), morality, health and willpower.
- Template powers: disciplines, arcana and rotes, contracts, gifts and rites,
  manifestations, werewolf renown, mummy pillars.
- Size, speed, defense, initiative, armor and weapons where the sheet has room.
- Werewolf forms: export entries such as "Hans Gauru (Wolf-Man)" are merged
  into the base character's sheet and fill the Dalu/Gauru/Urshul/Urhan columns
  on page 2.

### Left blank on purpose

Players fill these in themselves:

- Current energy (Vitae, Essence, Mana, Glamour, Plasm) and spent willpower.
- Experience and beats.
- Damage.
- Player name (it is still in the YAML files).

The permanent ratings (willpower dots, Blood Potency, …) are filled in.

### Missing values

Values still at the sheet default don't exist in Roll20, so `export.js` can't
export them. A missing attribute therefore counts as 1, a missing power stat
as 1 and missing morality as 7.

## The YAML files

Every character file has the same layout:

```yaml
name: …
template: werewolf          # vampire, mage, changeling, geist, mummy, hunter, mortal, …
player: …
chronicle: …
concept: …
virtue: …
vice: …
auspice: …                  # the template's three identity slots
tribe: …
lodge: …
attributes: {mental: {…}, physical: {…}, social: {…}}
skills: {mental: {…}, physical: {…}, social: {…}}
specialties: {crafts: [...], unsorted: [...]}
merits: [{name: …, dots: …}]
power: {name: Primal Urge, dots: 3}
morality: {name: Harmony, dots: 5}
health: 7
willpower: 6
size: 5
speed: 10
defense: 2
initiative: 5
renown: {…}                 # template blocks: disciplines, arcana, rotes, renown, pillars, forms
other_traits: [{name: …, dots: …}]
attacks: [{name: …, damage: …}]
armor: [...]
conditions: [...]
notes: {allies: …, derangements: …, info: [{title: …, text: …}]}
```

Roll20 internals and the values left blank on purpose are not included.

## Other commands

```sh
uv run characters.py                    # every decoded character as raw JSON, one per line
uv run characters.py --clean            # without Roll20 internals (roll macros, flags, …)
uv run characters.py --sheettype vampire1 --name lisa --fields Concept,Virtue,Vice
uv run map.py input/batch3.txt          # only some export files
uv run map.py --out somewhere-else      # another output folder
uv run map.py --json                    # also write the raw export as <name>.json
uv run map.py --type vampire1            # only some sheettypes (repeatable)
```

## Project layout

| Path | What it is |
| --- | --- |
| `export.js` | Roll20 API script that produces the export files (see [Exporting from Roll20](#exporting-from-roll20)). |
| `map.py` | Decodes the exports, downloads missing templates and fills the PDFs (the mapping engine). |
| `character.py` | Builds the structured YAML data. |
| `characters.py` | Prints decoded characters as JSON lines. |
| `mappings/*.json` | One file per sheet: which template, where to download it, and which data goes into which PDF field. |
| `input/` | Your export files (not in git). |
| `templates/` | The PDF templates (downloaded, not in git). |
| `out/` | Generated sheets and YAML (not in git). |

## Adding or changing a sheet

Each sheet is described by a mapping file in `mappings/`; no code changes are
needed. The format is documented at the top of `map.py`. In short, a mapping
sets:

- `template`, `url` and `sheettypes`;
- `text` fields from templates like `{Concept}`, `{base_size|5}` or
  `{=Dexterity+Composure}`;
- `dots`: the checkboxes for a rating;
- `lists`: merits and similar repeating rows;
- `named`: traits placed by name (renown, pillars);
- `specialties`: each skill's specialty field;
- `lines`: multi-line text;
- `clear`: boxes that always stay empty;
- `ignore`: attributes left off the sheet on purpose (not reported);
- `forms` and `when`: werewolf forms.

PDF field names often don't say what they are (`dot17`), so map them by their
position on the page.

## License

This project is released into the public domain under
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/); see
`LICENSE`. The character sheet PDFs downloaded into `templates/` are not part
of the project and keep their own terms.
