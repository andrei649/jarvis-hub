#!/usr/bin/env python3
"""Mechanical completeness check for the Hermes v2026.8.31 inventory.

Answers one question: is every UI string Hermes ships present somewhere in
``sections/*.md``? A string counts as covered when its i18n key appears
verbatim in a section, or when its normalised text appears (substring for
4+ characters, whole word below that).

Usage::

    check_strings.py <chunk.json>   # one catalog chunk, prints the misses
    check_strings.py --all          # every chunk, prints the totals

Chunks live in ``strings_chunks/`` next to this file and hold ``{key, text}``
records flattened from the desktop, web, TUI and gateway i18n catalogs plus
the labels read out of the running dashboard with Playwright. Both the chunks
and the sections ship with the document, so the coverage claim can be re-run
here rather than taken on trust.

Note: ``--all`` matches against every section concatenated, so a match may
straddle a file boundary. ``assemble.py`` repeats the check per section and
is the stricter of the two; the appendix it writes is authoritative.
"""

import glob
import json
import os
import re
import sys

INV = os.path.dirname(os.path.abspath(__file__))

# Keep letters from the scripts the catalogs actually use (Latin + extended,
# Cyrillic, CJK, kana, Hangul); everything else becomes a word separator.
_WORDLIKE = r"[^a-z0-9À-ɏЀ-ӿ一-鿿぀-ヿ가-힯 ]+"


def norm(text):
    """Lowercase, drop placeholders/markup, reduce punctuation to spaces."""
    text = re.sub(r"\{\{?[^}]*\}\}?", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(_WORDLIKE, " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _section_paths():
    """The shard files, in either layout: the working ``sections/`` directory
    used while building, or the published ``NN-<shard>.md`` files beside this
    script."""
    paths = sorted(glob.glob(os.path.join(INV, "sections", "*.md")))
    return paths or sorted(glob.glob(os.path.join(INV, "[0-9][0-9]-*.md")))


def _load_sections():
    raw = ""
    for path in _section_paths():
        with open(path, encoding="utf-8") as handle:
            raw += "\n" + handle.read()
    if not raw.strip():
        raise SystemExit("no section files found next to check_strings.py")
    return raw, norm(raw)


def check(chunk_path, raw, union):
    with open(chunk_path, encoding="utf-8") as handle:
        chunk = json.load(handle)
    catalog = re.sub(r"_\d+\.json$", "", os.path.basename(chunk_path))
    uncovered = []
    for item in chunk:
        key = item["key"]
        text = item["text"]
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        needle = norm(text)
        if key and key in raw:
            continue
        if not needle:
            # Pure placeholder template (e.g. "{bar}") — no words to match on.
            # Section 38 documents these by key; only the key check applies.
            continue
        if len(needle) >= 4 and needle in union:
            continue
        if len(needle) < 4 and re.search(r"(^| )" + re.escape(needle) + r"( |$)", union):
            continue
        uncovered.append({"key": key, "text": text[:300], "catalog": catalog})
    return {
        "chunk": os.path.basename(chunk_path),
        "checked": len(chunk),
        "covered": len(chunk) - len(uncovered),
        "uncovered": uncovered,
    }


def main(argv):
    raw, union = _load_sections()
    if "--all" in argv:
        chunks = sorted(glob.glob(os.path.join(INV, "strings_chunks", "*_[0-9][0-9].json")))
        results = [check(path, raw, union) for path in chunks]
        total = sum(r["checked"] for r in results)
        covered = sum(r["covered"] for r in results)
        print(
            json.dumps(
                {
                    "total": total,
                    "covered": covered,
                    "uncovered_total": total - covered,
                    "per_chunk": [
                        {k: v for k, v in r.items() if k != "uncovered"} for r in results
                    ],
                },
                indent=1,
            )
        )
        return 0
    if len(argv) < 2:
        print(__doc__)
        return 2
    print(json.dumps(check(argv[1], raw, union), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
