"""Print decoded characters as JSON, one character per line.

Usage:
    uv run characters.py [input/*.txt ...] [--sheettype TYPE] [--name TEXT]
                         [--fields KEY,KEY,...] [--clean]

Filters combine: --sheettype (repeatable; "" or "none" for characters without
one) and --name (case-insensitive substring) select characters, --fields keeps
only the listed attributes, and --clean drops the sheet's internal attributes
(roll macros, *_flag, repeating_* rows and similar).
"""

import argparse
import json
import re
import sys

from map import default_inputs, read_characters

INTERNAL = re.compile(
    r'^(roll|_reporder|attack_type|attack$|dicepoolmacro|modifiermacro|unarmedmacro'
    r'|pagenumber|repeating_)|_flag\d*$')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("inputs", nargs="*",
                        help="export files (default: input/*.txt)")
    parser.add_argument("--sheettype", action="append",
                        help="only this sheettype (repeatable)")
    parser.add_argument("--name", help="only names containing this text")
    parser.add_argument("--fields", help="comma-separated attributes to keep")
    parser.add_argument("--clean", action="store_true",
                        help="drop internal sheet attributes")
    args = parser.parse_args()

    inputs = args.inputs or default_inputs()
    if not inputs:
        sys.exit("error: no input files")

    sheettypes = None
    if args.sheettype:
        sheettypes = {"" if s == "none" else s for s in args.sheettype}
    fields = args.fields.split(",") if args.fields else None

    for character in read_characters(inputs):
        attrs = character["attributes"]
        if sheettypes is not None and attrs.get("sheettype", "") not in sheettypes:
            continue
        if args.name and args.name.lower() not in character["name"].lower():
            continue
        if fields:
            attrs = {k: attrs[k] for k in fields if k in attrs}
        if args.clean:
            attrs = {k: v for k, v in attrs.items() if not INTERNAL.search(k)}
        print(json.dumps({"name": character["name"], "attributes": attrs},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
