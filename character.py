"""Turn a raw Roll20 character export into clean, consistently structured data.

Every character gets the same layout, whatever its template:

    name, template, player, chronicle, concept, virtue, vice,
    <the template's three identity slots, e.g. clan/bloodline/covenant>,
    attributes {mental, physical, social}, skills {mental, physical, social},
    specialties, merits, power, morality, health, willpower, derived stats,
    <template powers: disciplines, arcana, renown, pillars, ...>,
    forms (werewolves: Dalu, Gauru, Urshul, Urhan stats),
    other_traits, rotes, attacks, armor, conditions, notes

Numbers are integers, untrained skill penalties become 0, missing ratings get
the sheet defaults, and text has trailing whitespace removed. Roll20 internals
and current-state values players track themselves (energy and willpower spent,
damage, experience) are left out.
"""

import re

from map import DEFAULTS, NOT_DATA, names_match, skill_key, split_specialty

ATTRIBUTES = {
    "mental": ["Intelligence", "Wits", "Resolve"],
    "physical": ["Strength", "Dexterity", "Stamina"],
    "social": ["Presence", "Manipulation", "Composure"],
}
SKILLS = {
    "mental": ["Academics", "Computer", "Crafts", "Investigation", "Medicine",
               "Occult", "Politics", "Science"],
    "physical": ["Athletics", "Brawl", "Drive", "Firearms", "Larceny", "Stealth",
                 "Survival", "Weaponry"],
    "social": ["AnimalKen", "Empathy", "Expression", "Intimidation", "Persuasion",
               "Socialize", "Streetwise", "Subterfuge"],
}

# sheettype -> template, its three identity slots (export keys Chronicle,
# Faction, GroupName), its power stat and its morality.
TEMPLATES = {
    "vampire1": ("vampire", ("clan", "bloodline", "covenant"), "Blood Potency", "Humanity"),
    "werewolf1": ("werewolf", ("auspice", "tribe", "lodge"), "Primal Urge", "Harmony"),
    "mage1": ("mage", ("path", "order", "legacy"), "Gnosis", "Wisdom"),
    "changeling1": ("changeling", ("seeming", "kith", "court"), "Wyrd", "Clarity"),
    "geist1": ("geist", ("archetype", "threshold", "krewe"), "Psyche", "Synergy"),
    "mummy1": ("mummy", ("decree", "guild", "meret"), "Sekhem", "Memory"),
    "demon": ("demon", ("incarnation", "agenda", "catalyst"), "Primum", "Cover"),
    "promethean1": ("promethean", ("lineage", "refinement", "group"), "Azoth", "Humanity"),
    "hunter": ("hunter", ("profession", "organization", "group"), None, "Integrity"),
}
MORTAL = ("mortal", ("age", "faction", "group"), None, "Integrity")

DISCIPLINES = {"Animalism": "Animalism", "Auspex": "Auspex", "Celerity": "Celerity",
               "Dominate": "Dominate", "Majesty": "Majesty", "Nightmare": "Nightmare",
               "Obfuscate": "Obfuscate", "Protean": "Protean", "Resilience": "Resilience",
               "Vigor": "Vigor", "Crúac": "Crúac", "ThebanSorcery": "Theban Sorcery"}
ARCANA = ["Death", "Fate", "Forces", "Life", "Matter", "Mind", "Prime", "Space",
          "Spirit", "Time"]
# Traits stored among merits/other traits that belong in their own block.
NAMED_BLOCKS = {
    "werewolf": ("renown", ["Purity", "Glory", "Honor", "Wisdom", "Cunning"]),
    "mummy": ("pillars", ["Ab", "Ba", "Ka", "Ren", "Sheut"]),
}
HEADERS = ["Renown", "Pillars", "-Spent", "Spent"]  # list headers, not traits
# Werewolf forms: Speed, Initiative and Perception over Hishu, as printed on
# the Forsaken sheet. (The export's own form values count these twice.)
FORM_BONUS = {"Dalu": (1, 0, 2), "Gauru": (4, 1, 3), "Urshul": (7, 2, 3), "Urhan": (5, 2, 4)}

# Free-text export keys -> clean note names; unknown keys are snake_cased.
NOTE_NAMES = {
    "derangments": "derangements", "paradoxmarks": "paradox_marks",
    "dedicatedmagicaltools": "magical_tools", "spellscastuponself": "spells_on_self",
    "kithability": "kith_ability", "seemingblessing": "seeming_blessing",
    "seemingcurse": "seeming_curse", "ketystonemomento": "keystone",
    "culgitt": "cult", "viniculum": "vinculum", "demonicform": "demonic_form",
    "Player": "chronicle",  # Roll20 keeps the chronicle in "Player"
}
# Consumed below, or current state players track themselves.
SKIP = re.compile(r"^(conditions\d+|specializations\d+|merit\d+(_name)?|othertrait\d+(_name)?"
                  r"|discipline\d+(_name)?|arcana\d+(_name)?|attack_|armor_|repeating_)")


def clean_text(value):
    lines = [line.rstrip() for line in str(value).replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def num(value):
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def rating(value):
    """A dot rating: an int, untrained penalties (-1, -3) as 0."""
    n = num(value)
    return max(0, n) if n is not None else None


def snake(name):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name).lower()


def pairs(attrs, prefix, start, end):
    """(name, rating) for prefix{i}_name / prefix{i}, skipping empty names."""
    found = []
    for i in range(start, end + 1):
        name = clean_text(attrs.get(f"{prefix}{i}_name", ""))
        if name:
            found.append((name, rating(attrs.get(f"{prefix}{i}", ""))))
    return found


def specialties(attrs):
    keys = {skill_key(s): snake(s) for group in SKILLS.values() for s in group}
    by_skill, other = {}, []
    lines = [line.strip() for i in range(1, 21)
             for line in str(attrs.get(f"specializations{i}", "")).splitlines()
             if line.strip()]
    pending = None
    for line in lines:
        pieces = [p.strip() for p in re.split(r"[,;]", line) if p.strip()]
        parsed = [split_specialty(p, list(keys)) for p in pieces]
        if len(pieces) < 2 or not all(k and s for k, s in parsed):
            pieces, parsed = [line], [split_specialty(line, list(keys))]
        if pending and len(parsed) == 1 and not parsed[0][0]:
            parsed = [(pending, line)]
        pending = None
        for (key, specialty), entry in zip(parsed, pieces):
            if key and specialty:
                by_skill.setdefault(keys[key], []).append(specialty)
            elif key:
                pending = key
            else:
                other.append(entry)
    if other:
        by_skill["unsorted"] = other
    return by_skill


def gear(attrs, kind, fields):
    """attack_name1/attack_damage1/... -> [{name, damage, ...}], skipping "-"."""
    items = {}
    for key, value in attrs.items():
        m = re.match(rf"^{kind}_([a-z]+)(\d+)$", key)
        value = clean_text(value)
        if m and m.group(1) in fields and value not in ("", "-"):
            items.setdefault(int(m.group(2)), {})[fields[m.group(1)]] = \
                num(value) if num(value) is not None else value
    return [{"name": item.pop("name", None), **item}
            for _, item in sorted(items.items()) if "name" in item or len(item) > 1]


def normalize(character):
    raw = character["attributes"]
    sheettype = raw.get("sheettype", "")
    template, slots, power, morality = TEMPLATES.get(sheettype, MORTAL)
    attrs = {**DEFAULTS, **raw}
    if power is None:
        attrs.pop("potency", None)
    get = lambda key: clean_text(attrs.get(key, ""))

    data = {"name": clean_text(character["name"]), "template": template,
            "player": get("Age") or None, "chronicle": get("Player") or None,
            "concept": get("Concept") or None,
            "virtue": get("Virtue") or None, "vice": get("Vice") or None}
    for slot, key in zip(slots, ("Chronicle", "Faction", "GroupName")):
        value = get(key)
        data[slot] = value if value not in ("", "-", "--") else None

    data["attributes"] = {group: {snake(a): rating(attrs.get(a)) or 0 for a in names}
                          for group, names in ATTRIBUTES.items()}
    data["skills"] = {group: {snake(s): rating(attrs.get(s, 0)) or 0 for s in names}
                      for group, names in SKILLS.items()}
    data["specialties"] = specialties(attrs)

    # Merits and other traits, with named blocks (renown, pillars) pulled out.
    merits = pairs(attrs, "merit", 1, 15)
    others = pairs(attrs, "othertrait", 0, 15)
    blocks = {}
    if template in NAMED_BLOCKS:
        block, labels = NAMED_BLOCKS[template]
        blocks[block] = {snake(label): 0 for label in labels}
        for name, value in merits + others:
            for label in labels:
                if names_match(name, label) or \
                        (label == "Honor" and names_match(name, "Honour")):
                    blocks[block][snake(label)] = max(blocks[block][snake(label)], value or 0)
        skip = labels + HEADERS + (["Honour"] if template == "werewolf" else [])
    else:
        skip = HEADERS
    keep = lambda items: [{"name": n, "dots": v} for n, v in items
                          if not any(names_match(n, s) for s in skip)]
    data["merits"] = keep(merits)

    data["power"] = {"name": power, "dots": rating(attrs.get("potency"))} if power else None
    data["morality"] = {"name": morality, "dots": rating(attrs.get("morality"))}
    data["health"] = rating(attrs.get("health"))
    data["willpower"] = rating(attrs.get("willpower"))
    strength, dexterity = rating(attrs["Strength"]) or 0, rating(attrs["Dexterity"]) or 0
    composure = rating(attrs["Composure"]) or 0
    data["size"] = rating(attrs.get("base_size")) or 5
    data["speed"] = strength + dexterity + 5 + (rating(attrs.get("fleet_of_foot")) or 0)
    data["defense"] = rating(attrs.get("defense_base"))
    data["initiative"] = dexterity + composure + (rating(attrs.get("fast_reflexes")) or 0)

    if template == "vampire":
        found = [(label, rating(attrs[key])) for key, label in DISCIPLINES.items()
                 if str(attrs.get(key, "")).strip()]
        found += pairs(attrs, "discipline", 0, 15)
        data["disciplines"] = {name: dots for name, dots in found if dots != 0}
    if template == "mage":
        data["arcana"] = {a.lower(): rating(attrs.get(a, 0)) or 0 for a in ARCANA}
        data["rotes"] = [{"name": n, "level": v or None} for n, v in pairs(attrs, "arcana", 1, 20)]
    data.update(blocks)
    if character.get("forms"):
        data["forms"] = {}
        for form, variant in character["forms"].items():
            v = normalize(variant)
            speed, initiative, perception = FORM_BONUS.get(form, (0, 0, 0))
            hishu = data["attributes"]
            data["forms"][form.lower()] = {
                "attributes": v["attributes"], "health": v["health"],
                "size": v["size"], "speed": data["speed"] + speed,
                "defense": v["defense"], "initiative": data["initiative"] + initiative,
                "perception": hishu["mental"]["wits"] + hishu["social"]["composure"]
                + perception,
                "armor": v["armor"]}
    data["other_traits"] = keep(others)

    data["attacks"] = gear(attrs, "attack", {
        "name": "name", "damage": "damage", "range": "range", "magazine": "clip",
        "initiative": "initiative", "strength": "strength", "size": "size"})
    data["armor"] = gear(attrs, "armor", {
        "name": "name", "general": "general", "ballistic": "ballistic",
        "defense": "defense", "speed": "speed", "strength": "strength",
        "description": "description"})
    data["conditions"] = [c for c in (get(f"conditions{i}") for i in range(1, 5)) if c]

    notes = {}
    for key, value in raw.items():
        value = clean_text(value)
        if value in ("", "0", "-") or value.startswith("@{") or NOT_DATA.search(key) \
                or SKIP.match(key) or key in DEFAULTS or key in (
                    "Age", "Player", "Concept", "Virtue", "Vice", "Chronicle",
                    "Faction", "GroupName", "health", "willpower", "defense_base"):
            continue
        if any(key in group for group in SKILLS.values()) or key in DISCIPLINES \
                or key in ARCANA:
            continue
        notes[NOTE_NAMES.get(key, snake(key))] = value
    info = {}
    for key, value in raw.items():
        m = re.match(r"^repeating_info(?:left|right)_(.+)_(title|text)(?:left|right)$", key)
        if m and clean_text(value):
            info.setdefault(m.group(1), {})[m.group(2)] = clean_text(value)
    if info:
        notes["info"] = [{"title": i.get("title"), "text": i.get("text")} for i in info.values()]
    data["notes"] = notes
    return data
