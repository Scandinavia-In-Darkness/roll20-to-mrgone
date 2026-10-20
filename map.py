"""Decode character export batches and fill one PDF sheet per character.

Each input file looks like:

    "=== START EXPORT BATCH 1 ==="
    "<JSON string containing a JSON array of characters>"
    "=== END EXPORT BATCH 1 ==="

Every character's `sheettype` attribute selects a mapping in mappings/*.json,
which names a PDF template in templates/ (downloaded from the mapping's "url"
the first time a character needs it) and says which attribute goes into
which form field. Filled sheets are written to out/<sheettype>/ (out/none/
for characters without one), each with a <name>.yaml holding the character's data, cleaned and structured the same
way for every template by character.py (written for skipped characters too), plus out/0-does-not-fit.yaml listing every character with data
that didn't make it onto their sheet, and out/0-too-many.yaml listing only those
with more merits, specialties, dots or lines than the sheet has room for.

Usage:
    uv run map.py [input/*.txt ...] [--out out] [--json] [--type TYPE]

--type (repeatable; "" or "none" for characters without one) only
processes characters of those sheettypes.

Mapping file format (all sections optional except template/sheettypes):

    {
      "template": "VtR1-Page_Editable.pdf",
      "sheettypes": ["vampire1"],          # "" matches characters without one
      "text":   {"<pdf field>": "<template>"},
      "dots":   {"<attribute>": ["<pdf checkbox>", ...]},
      "checks": {"<pdf checkbox>": "<attribute>"},
      "lines":  {"<template>": ["<pdf field>", ...]},
      "lists":  [{"range": [1, 15], "require": "merit{i}_name",
                  "rows": [{"text": {...}, "dots": {...}, "checks": {...}}]}],
      "specialties": {"fields": {"<Skill>": "<pdf field>", ...},
                      "unmatched": ["<pdf field>", ...]},
      "named":  [...],
      "clear":  ["<pdf checkbox>", ...],
      "ignore": ["<attribute>", ...]
    }

A lines entry splits the rendered template into lines, one per field, with
extra lines joined onto the last field. Specialties reads specializations1..20
entries like "Survival (Tracking)" or "Weaponry: Scythe" (one per line) and
puts each on its skill's field; entries naming no known skill go to unmatched.

Templates substitute {attribute} with its value ({name} is the character
name), {attribute|default} with a fallback, and {=a+b+5} with a sum of
attributes and numbers; a template whose placeholders are all empty becomes "". A dots entry
ticks the first N checkboxes, where N is the attribute's integer value. A
checks entry ticks the box when the attribute is "on" or a nonzero number.
Lists fill rows in order (a "label" names the list in overflow warnings) from the indices i in range that have a non-empty
`require` attribute; "{i}" in a row's keys and values is replaced by i. An
optional "exclude": ["Purity", ...] skips indices whose `require` value
matches one of those names the same way (e.g. traits placed by "named").

A list can instead gather items from several sources, in order:

    {"sources": [{"keys": {"Animalism": "Animalism", "ThebanSorcery": "Theban Sorcery"}},
                 {"range": [0, 15], "name": "discipline{i}_name", "value": "discipline{i}"}],
     "skip_zero": true, "exclude": [...],
     "rows": [{"text": {"<field>": "{@name}"}, "dots": {"@value": ["<dot>", ...]}}]}

A "keys" source yields one item per attribute present (labelled by the dict
value); a "range" source yields one per index with a non-empty name. Rows use
{@name} and {@value}; skip_zero drops items whose value is 0 (a name with
no value is kept).

    "named": [{"range": [0, 15], "name": "othertrait{i}_name",
               "value": "othertrait{i}", "rows": {"Purity": ["<dot>", ...]}}]

A named entry ticks a row's dots from the first trait whose name matches the
row label, wherever it is stored. Names match ignoring case, punctuation, a
plural "s" and anything in parentheses ("Wisdom (P)", "*Honor", "RENOWNS").
"forms": ["Dalu", "Gauru", ...] merges entries named "<first name> <Form> ..."
into the character with that first name; templates then read a form's values
as {Gauru.Strength}, {=Urhan.Dexterity+Urhan.Composure} and so on.

    "when": [{"if": "<attribute>", "text": {...}, "dots": {...}, ...}]

applies a section only when the attribute is set, e.g. "Gauru.Strength" to fill
a form's column only for characters that have that form.

A clear entry lists boxes that are always left empty (e.g. current
Willpower and Vitae, which players fill in themselves). An ignore entry lists
attributes left off the sheet on purpose, so they aren't reported as not
fitting (e.g. a geist's krewe).

Checkboxes a mapping covers but does not tick are cleared, so template
defaults (e.g. a pre-ticked first dot) don't show through.
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

BATCH = re.compile(
    r'^[ \t]*"?=== START EXPORT BATCH (\w+) ==="?[ \t]*\r?\n'
    r'(.*?)'
    r'^[ \t]*"?=== END EXPORT BATCH \1 ==="?[ \t]*$',
    re.MULTILINE | re.DOTALL,
)

# One escape sequence: a backslash plus the next character or line break.
ESCAPE = re.compile(r'\\(\r?\n|.)', re.DOTALL)

PLACEHOLDER = re.compile(r'\{([^{}]+)\}')

# Roll20 only exports values that differ from the sheet's defaults, so a
# missing key means the default: attributes and the power stat (Blood
# Potency, Psyche, ...) start at 1 and morality (Humanity, Synergy, ...) at 7.
DEFAULTS = {
    **{attr: "1" for attr in ("Intelligence", "Wits", "Resolve", "Strength", "Dexterity",
                               "Stamina", "Presence", "Manipulation", "Composure")},
    "potency": "1",
    "morality": "7",
}


def decode(data):
    """Decode the JSON-string-encoded batch data, then parse the JSON inside."""
    data = data.strip()
    if not (len(data) >= 2 and data.startswith('"') and data.endswith('"')):
        data = '"' + data + '"'
    # The exporter writes newlines as a backslash followed by a real line
    # break rather than \n, which JSON rejects; turn those into \n.
    data = ESCAPE.sub(
        lambda m: r'\n' if m.group(1) in ('\n', '\r\n') else m.group(0), data)
    # strict=False allows raw newlines/tabs inside the string.
    inner = json.loads(data, strict=False)
    return json.loads(inner, strict=False)


def default_inputs():
    """input/*.txt in natural order, so batch2 comes before batch10."""
    def key(path):
        return [int(t) if t.isdigit() else t.lower()
                for t in re.split(r"(\d+)", path.name)]
    return sorted((HERE / "input").glob("*.txt"), key=key)


def attach_forms(characters, mappings):
    """Move form entries such as "Hans Gauru (Wolf-Man)" into their base
    character ("Hans Johansson") as character["forms"]["Gauru"], for mappings
    with "forms": [...]. Returns the characters left to output on their own."""
    by_type = {}
    for character in characters:
        by_type.setdefault(character["attributes"].get("sheettype", ""), []).append(character)
    merged = set()
    for sheettype, group in by_type.items():
        forms = mappings.get(sheettype, {}).get("forms")
        if not forms:
            continue
        pattern = re.compile(rf"^(\S+)\s+({'|'.join(map(re.escape, forms))})\b")
        variants = [(c, m) for c in group if (m := pattern.match(c["name"]))]
        bases = [c for c in group if not pattern.match(c["name"])]
        for variant, m in variants:
            first, form = m.groups()
            candidates = [b for b in bases if b["name"].split()[0] == first]
            if len(candidates) != 1:
                warn(f"{variant['name']}: no single base character named {first} "
                     f"for this {form} form; giving it its own sheet")
                continue
            candidates[0].setdefault("forms", {})[form] = variant
            merged.add(id(variant))
    return [c for c in characters if id(c) not in merged]


def read_characters(paths):
    characters = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        batches = BATCH.findall(text)
        if not batches:
            sys.exit(f"error: {path}: no START/END EXPORT BATCH markers found")
        for name, data in batches:
            try:
                characters.extend(decode(data))
            except json.JSONDecodeError as e:
                sys.exit(f"error: {path}: batch {name}: {e}")
    return characters


def load_mappings(directory):
    mappings = {}
    for path in sorted(Path(directory).glob("*.json")):
        mapping = json.loads(path.read_text(encoding="utf-8"))
        for sheettype in mapping["sheettypes"]:
            mappings[sheettype] = mapping
    return mappings


class Tracked(dict):
    """Attributes that remember which keys were read and what didn't fit."""

    def __init__(self, data, used=None, problems=None):
        super().__init__(data)
        self.used = set() if used is None else used
        self.problems = {} if problems is None else problems

    def get(self, key, default=None):
        if key in self:
            self.used.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.used.add(key)
        return super().__getitem__(key)

    def extend(self, data):
        """A copy with extra keys that records into the same report."""
        return Tracked({**self, **data}, self.used, self.problems)

    def problem(self, kind, item):
        self.problems.setdefault(kind, []).append(item)


def number(value):
    try:
        return int(str(value).strip())
    except ValueError:
        return 0


def is_on(value):
    return str(value).strip() == "on" or number(value) != 0


def lookup(expr, attrs):
    """Resolve "key", "key|default" or "=key+key-3" (a sum) to a string."""
    if expr.startswith("="):
        terms = re.findall(r'([+-]?)\s*([^+-]+)', expr[1:])
        if not any(str(attrs.get(t.strip(), "")).strip() for _, t in terms
                   if not t.strip().isdigit()):
            return ""
        total = sum((-1 if sign == "-" else 1)
                    * (int(t) if t.strip().isdigit() else number(attrs.get(t.strip(), 0)))
                    for sign, t in terms)
        return str(total)
    key, _, default = expr.partition("|")
    return str(attrs.get(key, "")).strip() or default


def render(template, attrs):
    """Substitute {attribute} placeholders; "" if every one is empty."""
    found = []

    def sub(m):
        value = lookup(m.group(1), attrs)
        found.append(value)
        return value

    result = PLACEHOLDER.sub(sub, template)
    if found and not any(found):
        return ""
    return result.strip()


def fill_lines(lines, fields, text):
    """Put one line per field; extra lines are joined onto the last field."""
    if not fields:
        return
    for field, line in zip(fields, lines):
        text[field] = line
    if len(lines) > len(fields):
        text[fields[-1]] = "; ".join(lines[len(fields) - 1:])


def skill_key(name):
    return re.sub(r"[\W\d_]", "", name.lower())


def match_skill(word, keys):
    """Return (skill key, exact) for a word naming a skill by prefix ("Inv"),
    by inflection ("Driving") or, inexactly, by a near-miss typo."""
    word = skill_key(word)
    if len(word) < 3:
        return None, False
    hits = {k for k in keys if k.startswith(word)
            or (len(word) >= 5 and word.startswith(k[:4]) and k[:4] != word[:5])}
    if len(hits) == 1:
        return hits.pop(), True
    if not hits and len(word) >= 5:
        close = difflib.get_close_matches(word, keys, n=1, cutoff=0.8)
        if close:
            return close[0], False
    return None, False


def split_specialty(entry, keys):
    """Split e.g. "Academics (Math)", "Blades (Weaponry)", "Brawl: Bite" into
    (skill key, specialty); the skill key is None when no single skill is named."""
    words = list(re.finditer(r"[^\W\d_]+", entry))
    found = []
    for n, m in enumerate(words):
        word = m.group()
        # "Animal Ken" is two words; also catch "Animal" alone.
        if word.lower() == "animal":
            end = words[n + 1].end() if n + 1 < len(words) and \
                words[n + 1].group().lower() in ("ken", "keen") else m.end()
            found.append(("animalken", True, m.start(), end))
            continue
        key, exact = match_skill(word, keys)
        if key and key != "animalken":
            found.append((key, exact, m.start(), m.end()))
    # Three or more skills is a list of skills ("Rote: Athl, Inti, Medi").
    if not found or len({key for key, _, _, _ in found}) > 2:
        return None, entry
    # Prefer a skill in parentheses ("Sci-fi (Academics)"), then exact
    # matches over typos, then the skill named first.
    parens = [f for f in found if re.search(r"\(\s*$", entry[:f[2]])]
    if parens:
        found = parens
    if any(exact for _, exact, _, _ in found):
        found = [f for f in found if f[1]]
    skill, _, start, end = found[0]
    entry = entry[:start] + entry[end:]
    return skill, re.sub(r"\(\s*\)", "", entry).strip(" \t()[]-:;,.*/")


def apply_specialties(spec, attrs, text):
    """Place specializationsN entries on the line of the skill they name."""
    by_field, unmatched = {}, []
    fields = {skill_key(skill): field for skill, field in spec["fields"].items()}
    start, end = spec.get("range", [1, 20])
    lines = [line.strip() for i in range(start, end + 1)
             for line in str(attrs.get(f"specializations{i}", "")).splitlines()
             if line.strip()]
    pending = None  # a bare "Skill:" waiting for its specialty on the next line
    for line in lines:
        # "Repairs(Craft), Lies(Empathy)" holds one specialty per piece.
        pieces = [p.strip() for p in re.split(r"[,;]", line) if p.strip()]
        parsed = [split_specialty(p, list(fields)) for p in pieces]
        if len(pieces) < 2 or not all(k and s for k, s in parsed):
            pieces, parsed = [line], [split_specialty(line, list(fields))]
        if pending and len(parsed) == 1 and not parsed[0][0]:
            parsed = [(pending, line)]
        pending = None
        for (key, specialty), entry in zip(parsed, pieces):
            if key and specialty:
                by_field.setdefault(fields[key], []).append(specialty)
            elif key:
                pending = key
            else:
                unmatched.append(entry)
    for field, names in by_field.items():
        text[field] = ", ".join(names)
    if unmatched and not spec.get("unmatched"):
        for entry in unmatched:
            attrs.problem("specialties", entry)
    fill_lines(unmatched, spec.get("unmatched", []), text)


def apply_section(section, attrs, text, checked):
    for field, template in section.get("text", {}).items():
        value = render(template, attrs)
        if value:
            text[field] = value
    for template, fields in section.get("lines", {}).items():
        lines = [l.strip() for l in render(template, attrs).splitlines() if l.strip()]
        fill_lines(lines, fields, text)
        if len(lines) > len(fields):
            attrs.problem("text", {"field": template.strip("{}"), "lines": len(lines),
                                   "fits": len(fields)})
    if "specialties" in section:
        apply_specialties(section["specialties"], attrs, text)
    for attr, fields in section.get("dots", {}).items():
        value = number(attrs.get(attr, 0))
        checked.update(fields[:max(0, value)])
        if value > len(fields) and attr in attrs:
            attrs.problem("dots", {"trait": attr, "value": value, "fits": len(fields)})
    for field, attr in section.get("checks", {}).items():
        if is_on(attrs.get(attr, "")):
            checked.add(field)


def names_match(name, label):
    """True if a trait name is the label, ignoring case, punctuation, a plural
    "s" and anything in parentheses: "Wisdom (P)", "*Honor", "RENOWNS"."""
    name = skill_key(re.sub(r"\(.*?(\)|$)", "", name))
    label = skill_key(label)
    return bool(name) and name in (label, label + "s")


def apply_named(spec, attrs, checked):
    """Tick a row's dots from the trait whose name matches the row's label."""
    start, end = spec["range"]
    traits = []
    for i in range(start, end + 1):
        name_key = spec["name"].replace("{i}", str(i))
        value_key = spec["value"].replace("{i}", str(i))
        name = str(dict.get(attrs, name_key, "")).strip()
        if name:
            traits.append((name, name_key, value_key))
    for label, fields in spec["rows"].items():
        for name, name_key, value_key in traits:
            if names_match(name, label):
                checked.update(fields[:max(0, number(attrs.get(value_key, 0)))])
                attrs.get(name_key)
                break


def checkboxes(node):
    """Every checkbox field a mapping (or part of one) can tick."""
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "dots":
                found.update(f for fields in value.values() for f in fields)
            elif key in ("checks", "clear"):
                found.update(value)
            elif key == "named":
                found.update(f for spec in value for fields in spec["rows"].values()
                             for f in fields)
            else:
                found |= checkboxes(value)
    elif isinstance(node, list):
        for item in node:
            found |= checkboxes(item)
    return found


def field_values(mapping, character):
    """Return ({text field: value}, {checkbox fields to tick}, overflow, attrs),
    where overflow lists (list label, rows, [names that didn't fit]) per overfull
    list and attrs records the keys used and other things that didn't fit."""
    attrs = Tracked({**DEFAULTS, "name": character["name"], **character["attributes"]})
    # Other forms of the character (see attach_forms) as "<Form>.<key>".
    for form, variant in character.get("forms", {}).items():
        for key, value in {**DEFAULTS, **variant["attributes"]}.items():
            dict.__setitem__(attrs, f"{form}.{key}", value)
    text, checked, overflow = {}, set(), []
    attrs.used.update(mapping.get("ignore", []))
    apply_section(mapping, attrs, text, checked)
    for section in mapping.get("when", []):
        if str(attrs.get(section["if"], "")).strip():
            apply_section(section, attrs, text, checked)
    for spec in mapping.get("named", []):
        apply_named(spec, attrs, checked)

    for spec in mapping.get("lists", []):
        rows = spec["rows"]
        if "sources" in spec:
            items = list_items(spec, attrs)
            for row, item in zip(rows, items):
                attrs.used.update(item.pop("@keys"))
                apply_section(row, attrs.extend(item), text, checked)
            dropped = [item["@name"] for item in items[len(rows):]]
            for item in items[len(rows):]:
                attrs.used.update(item["@keys"])
        else:
            start, end = spec["range"]
            exclude = spec.get("exclude", [])
            indices = []
            for i in range(start, end + 1):
                value = str(dict.get(attrs, spec["require"].replace("{i}", str(i)), "")).strip()
                if value and not any(names_match(value, e) for e in exclude):
                    indices.append(i)
                elif value:  # excluded on purpose, so not "left out" either
                    attrs.used.update(row_keys(spec["rows"][0], i))
            for row, i in zip(rows, indices):
                row = json.loads(json.dumps(row).replace("{i}", str(i)))
                apply_section(row, attrs, text, checked)
            dropped = [str(dict.get(attrs, spec["require"].replace("{i}", str(i)))).strip()
                       for i in indices[len(rows):]]
            for i in indices[len(rows):]:
                attrs.used.update(row_keys(spec["rows"][0], i))
        if dropped:
            overflow.append((list_label(spec), len(rows), dropped))
            attrs.problem("lists", {"list": list_label(spec), "count": len(rows) + len(dropped),
                                    "rows": len(rows), "left_out": dropped})
    return text, checked, overflow, attrs


def row_keys(row, i):
    """The attribute keys a list row reads for index i."""
    row = json.loads(json.dumps(row).replace("{i}", str(i)))
    keys = set(row.get("dots", {})) | set(row.get("checks", {}).values())
    for template in [*row.get("text", {}).values(), *row.get("lines", {})]:
        for expr in PLACEHOLDER.findall(template):
            keys.update(t.strip() for t in re.split(r"[=+\-|]", expr.split("|")[0]))
    return keys


def list_label(spec):
    """A list's "label", or one derived from its source, e.g. "merit" -> "merits"."""
    if "label" in spec:
        return spec["label"]
    source = spec.get("require") or spec["sources"][-1].get("name", "items")
    return re.sub(r"\{i\}.*$", "", source).rstrip("_") + "s"


def list_items(spec, attrs):
    """Collect {"@name", "@value"} items from a list's sources, in order."""
    exclude = spec.get("exclude", [])
    items = []
    for source in spec["sources"]:
        get = lambda key: dict.get(attrs, key, "")
        if "keys" in source:
            pairs = [(label, get(key), [key]) for key, label in source["keys"].items()
                     if str(get(key)).strip()]
        else:
            start, end = source["range"]
            pairs = []
            for i in range(start, end + 1):
                keys = [source["name"].replace("{i}", str(i)),
                        source["value"].replace("{i}", str(i))]
                pairs.append((get(keys[0]), get(keys[1]), keys))
        for name, value, keys in pairs:
            name = str(name).strip()
            if not name:
                continue
            # Skipped on purpose, so not "left out" either.
            if any(names_match(name, e) for e in exclude) or \
                    (spec.get("skip_zero") and str(value).strip() and number(value) <= 0):
                attrs.used.update(keys)
                continue
            items.append({"@name": name, "@value": str(value).strip(), "@keys": keys})
    return items


def template_path(mapping, templates_dir, cache):
    """The mapping's PDF template, downloaded from its "url" if it's missing.
    Returns None (and reports why, once) if it can't be had."""
    name = mapping["template"]
    if name not in cache:
        path = templates_dir / name
        if not path.exists():
            path = download_template(mapping.get("url"), path)
        cache[name] = path
    return cache[name]


def download_template(url, path):
    if not url:
        error(f"{path.name} is missing and its mapping has no url")
        return None
    status(f"downloading template {path.name} from {url}")
    started = time.monotonic()
    tty = sys.stderr.isatty()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "character-sheets"})
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            chunks, done = [], 0
            while chunk := response.read(64 * 1024):
                chunks.append(chunk)
                done += len(chunk)
                if tty:  # redraw one progress line in place
                    of = f" of {total / 1e6:.1f} MB ({done * 100 // total}%)" if total else " MB"
                    print(f"\r  {done / 1e6:.1f}{of}", end="", file=sys.stderr, flush=True)
            if tty:
                print("\r\033[K", end="", file=sys.stderr)
        data = b"".join(chunks)
        if not data.startswith(b"%PDF"):
            raise ValueError("the download is not a PDF")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        status(f"downloaded template {path.name} ({len(data) / 1e6:.1f} MB "
               f"in {time.monotonic() - started:.1f} s)")
        return path
    except (OSError, ValueError) as e:
        if tty:
            print("\r\033[K", end="", file=sys.stderr)
        error(f"couldn't download {path.name} from {url}: {e}")
        return None


def fill_pdf(template_path, text, checked, unchecked, out_path):
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    reader = PdfReader(template_path)
    fields = reader.get_fields() or {}
    values = dict(text)
    # Clear boxes the mapping covers but this character doesn't tick, in case
    # the template ships with them ticked.
    for name in unchecked:
        if name in fields:
            values[name] = NameObject("/Off")
    for name in checked:
        states = [s for s in fields.get(name, {}).get("/_States_", []) if s != "/Off"]
        if states:
            values[name] = NameObject(states[0])

    writer = PdfWriter(clone_from=reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, values, auto_regenerate=False)
    writer.set_need_appearances_writer(True)
    with open(out_path, "wb") as f:
        writer.write(f)


# Attributes that are sheet internals, derived from other values, current
# state players fill in themselves (pools, damage, experience), or the player
# name (Roll20's "Age"), which is left off the sheets: never reported.
NOT_DATA = re.compile(
    r"^(roll|_reporder|attack_type|attack$|dicepoolmacro|modifiermacro|unarmedmacro"
    r"|pagenumber|repeating_custom|sheettype$|potency_name$|defense_select$"
    r"|woundpenalties_|vitae_box|willpower_box|beat_box|healthbox_|experience$"
    r"|bonus_|base_size$|species_factor$|giant$|fast_reflexes$|fleet_of_foot$"
    r"|iron_stamina$|Age$)|_penalty$|_flag\d*$")

INFO = re.compile(r"^repeating_info(left|right)_(.+)_(title|text)(left|right)$")
GEAR = re.compile(r"^(attack|armor)_([a-z]+)(\d+)$")
TRAIT = re.compile(r"^(othertrait|merit|discipline|arcana)(\d+)(_name)?$")
TRAIT_LABELS = {"othertrait": "other traits", "merit": "merits",
                "discipline": "disciplines", "arcana": "rotes"}


def leftovers(character, used):
    """Data with a real value that no field of the sheet shows, as
    {"notes": [{title, text}], "unplaced": {name: value or [items]}}."""
    from character import NOTE_NAMES, clean_text, num, snake

    unplaced, notes, traits, gear = {}, {}, {}, {}
    attrs = character["attributes"]
    for key, value in attrs.items():
        value = clean_text(value)
        if key in used or NOT_DATA.search(key) or value in ("", "0", "-") \
                or value.startswith("@{"):
            continue
        if num(value) is not None:
            value = num(value)
        if m := INFO.match(key):  # Roll20 info panels: a title and a text
            notes.setdefault(m.group(2), {})[m.group(3)] = value
        elif m := TRAIT.match(key):  # othertrait3_name + othertrait3 -> {name, dots}
            kind, n, _ = m.groups()
            name = clean_text(attrs.get(f"{kind}{n}_name", "")) or f"{kind} {n}"
            traits.setdefault(TRAIT_LABELS[kind], {})[name] = number(attrs.get(f"{kind}{n}", "")) \
                if str(attrs.get(f"{kind}{n}", "")).strip() else None
        elif m := GEAR.match(key):  # attack_damage1 -> attacks: [{name, damage}]
            kind, field, n = m.groups()
            item = gear.setdefault(kind, {}).setdefault(int(n), {})
            item["name"] = clean_text(attrs.get(f"{kind}_name{n}", "")) or None
            if field != "name":
                item[field] = value
        else:
            unplaced[NOTE_NAMES.get(key, snake(key))] = value
    for label, items in traits.items():
        unplaced[label.replace(" ", "_")] = [{"name": n, "dots": d} for n, d in items.items()]
    for kind, items in gear.items():
        unplaced["attacks" if kind == "attack" else "armor"] = \
            [item for _, item in sorted(items.items())]
    found = {}
    if notes:
        found["notes"] = [{"title": n.get("title"), "text": n.get("text")} for n in notes.values()]
    if unplaced:
        found["unplaced"] = unplaced
    return found


def report_entry(name, stem, template, problems=(), extra=None, reason=None):
    """One character's entry in 0-does-not-fit.yaml / 0-too-many.yaml."""
    entry = {"name": name, "pdf": f"{stem}.pdf" if template else None,
             "yaml": f"{stem}.yaml", "template": template}
    if reason:
        entry["reason"] = reason
    entry.update(problems)
    entry.update(extra or {})
    return entry


# Problems that mean "more than the sheet has room for" (0-too-many.yaml).
CROWDED = ("lists", "dots", "specialties", "text")


def to_yaml(character):
    """A character as YAML, keeping key order and writing multi-line text as
    literal | blocks."""
    import yaml

    class Dumper(yaml.SafeDumper):
        pass

    def string(dumper, value):
        style = "|" if "\n" in value else None
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)

    Dumper.add_representer(str, string)
    return yaml.dump(character, Dumper=Dumper, allow_unicode=True,
                     sort_keys=False, width=1000)


def status(message):
    """Print progress to stderr, in cyan when stderr is a terminal."""
    print(paint(message, "36"), file=sys.stderr)


def error(message):
    print(paint("error:", "31") + " " + paint(message, "31") if color()
          else f"error: {message}", file=sys.stderr)


def color():
    return sys.stderr.isatty() and not os.environ.get("NO_COLOR")


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if color() else text


def warn(message):
    """Print a warning to stderr, in yellow when stderr is a terminal."""
    if sys.stderr.isatty() and not os.environ.get("NO_COLOR"):
        message = f"\033[33mwarning:\033[0m \033[33m{message}\033[0m"
    else:
        message = f"warning: {message}"
    print(message, file=sys.stderr)


def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip(" .'")
    return re.sub(r"\s+", " ", name) or "unnamed"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="*",
                        help="export files (default: input/*.txt)")
    parser.add_argument("--out", default=HERE / "out", type=Path,
                        help="output folder (default: out/)")
    parser.add_argument("--templates", default=HERE / "templates", type=Path)
    parser.add_argument("--mappings", default=HERE / "mappings", type=Path)
    parser.add_argument("--json", action="store_true",
                        help="also write each character's decoded attributes as JSON")
    parser.add_argument("--type", action="append",
                        help="only this sheettype (repeatable)")
    args = parser.parse_args()

    from character import normalize

    inputs = args.inputs or default_inputs()
    if not inputs:
        sys.exit("error: no input files")
    characters = read_characters(inputs)
    mappings = load_mappings(args.mappings)
    characters = attach_forms(characters, mappings)
    if args.type:
        sheettypes = {"" if s == "none" else s for s in args.type}
        characters = [c for c in characters
                      if c["attributes"].get("sheettype", "") in sheettypes]
        if not characters:
            sys.exit(f"error: no characters with sheettype {', '.join(map(repr, args.type))}")
    args.out.mkdir(parents=True, exist_ok=True)

    used, skipped, report, too_many = set(), {}, [], []
    templates = {}  # template name -> path, or None if it couldn't be had
    for character in characters:
        sheettype = character["attributes"].get("sheettype", "")
        # One folder per sheettype; stem is the path relative to args.out.
        folder = safe_filename(sheettype) if sheettype else "none"
        (args.out / folder).mkdir(exist_ok=True)
        base = f"{folder}/{safe_filename(character['name'])}"
        stem, n = base, 1
        while stem.lower() in used:
            n += 1
            stem = f"{base} ({n})"
        used.add(stem.lower())

        (args.out / f"{stem}.yaml").write_text(to_yaml(normalize(character)),
                                               encoding="utf-8")
        if args.json:
            (args.out / f"{stem}.json").write_text(
                json.dumps(character, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")

        mapping = mappings.get(sheettype)
        template = mapping and template_path(mapping, args.templates, templates)
        if template is None:
            reason = (f"template {mapping['template']} couldn't be downloaded" if mapping
                      else f"no sheet for sheettype {sheettype or '(none)'!r}")
            skipped.setdefault(reason, []).append(character["name"])
            report.append(report_entry(character["name"], stem, None, reason=reason))
            continue
        text, checked, overflow, attrs = field_values(mapping, character)
        problems = {k: attrs.problems[k] for k in CROWDED if k in attrs.problems}
        extra = leftovers(character, attrs.used)
        if problems or extra:
            report.append(report_entry(character["name"], stem, mapping["template"],
                                       problems, extra))
        if problems:
            too_many.append(report_entry(character["name"], stem, mapping["template"],
                                         problems))
        out_path = args.out / f"{stem}.pdf"
        fill_pdf(template, text, checked,
                 checkboxes(mapping) - checked, out_path)
        print(f"{stem}.pdf: {mapping['template']} "
              f"({len(text)} text, {len(checked)} checked)")
        for label, rows, dropped in overflow:
            warn(f"{stem}.pdf: {rows + len(dropped)} {label} but only {rows} "
                 f"rows; left out: {', '.join(dropped)}")

    for reason, names in skipped.items():
        warn(f"skipped {len(names)}, {reason}: {', '.join(names)}")

    report_path = args.out / "0-does-not-fit.yaml"
    report_path.write_text(to_yaml({"count": len(report), "characters": report}),
                           encoding="utf-8")
    print(f"{report_path.name}: {len(report)} characters with data that "
          f"doesn't fit on their sheet")
    crowded_path = args.out / "0-too-many.yaml"
    crowded_path.write_text(to_yaml({"count": len(too_many), "characters": too_many}),
                            encoding="utf-8")
    print(f"{crowded_path.name}: {len(too_many)} characters with more merits, "
          f"specialties or other entries than their sheet has room for")


if __name__ == "__main__":
    main()
