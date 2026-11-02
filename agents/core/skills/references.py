"""references.py — what still names a skill a batch deletes (H330).

Hermes' ``skill_manage`` delete takes ``absorbed_into``: the skill that took the deleted
one's place, and its cron jobs' ``skills`` links move to it. In Nerva a skill is named
from more places than a cron job, so a delete in a batch (:mod:`skills.batch`) asks every
holder that can name a skill, and each answer is either *migrated* to the absorbing skill
or *reported* where it is, so nothing is left pointing at a skill that is gone without
anyone being told:

* **other skills** — ``related_skills`` (top-level or ``metadata.hermes``) is a structured
  link: with ``absorbed_into`` it is rewritten in the same atomic batch, on that skill's
  staging copy, and shown in the batch's diff like any edit (:func:`rewrite_related`).
  A skill the batch may not edit (shipped with Nerva, awaiting review in CDX-8
  quarantine, linked, unreadable, or hidden from the caller) is reported instead. Prose
  that names the deleted skill is reported with its lines (:func:`mention_lines`): text
  is not rewritten by guesswork, the model or the owner patches it in the same batch.
* **bundles** (H026) — a member that resolves to the deleted skill is rewritten to the
  absorbing one when the batch lands, inside the same all-or-nothing apply.
* **scheduled jobs** — a Nerva job has no skill link field (``skills`` is refused at
  intake, ``jobs_health`` lists it as unsupported); a job whose prompt, message, title or
  payload names the skill is reported with its id and field.
* **the load set** (H285 ``loadset.skills_disabled`` / ``skills_only``) and **the skill
  switches** (H329 ``skills.disabled`` / ``channel_disabled``) — reported, never
  rewritten: moving an entry to another skill would switch that skill off, or let a skill
  load that the owner's list kept out, so the owner decides. A ``skills_only`` list that
  will not load the absorbing skill is called out.
* **pending skill proposals and batches** that name the skill — reported: they can no
  longer apply.

Everything here reads; the only writes are the two migrations, both made by
:func:`skills.batch.run_batch` inside its staging and swap.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
from collections.abc import Callable, Container, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("jarvis.skills.references")

#: What one delete's report lists before it counts the rest.
MAX_LEFT = 50
#: Lines of one file a mention entry names.
MAX_LINES = 5
#: Supporting files read for mentions, per skill, and the largest one read.
MAX_FILES = 50
MAX_FILE_BYTES = 256 * 1024
_TEXT_DIRS = ("references", "templates", "scripts", "assets")
_SKILL_FILE = "SKILL.md"
_KEY_RE = re.compile(r"^(\s*)related_skills\s*:(.*)$")
_PLAIN_RE = re.compile(r"^[a-z][a-z0-9._-]*$")
_YAML_WORDS = frozenset({"true", "false", "yes", "no", "on", "off", "null", "y", "n"})


def identities(skill: Any) -> set[str]:
    """The names a skill is referred to by: its manifest name and its folder."""
    out = {str(getattr(skill, "name", "") or "")}
    path = getattr(skill, "path", None)
    if path is not None:
        out.add(Path(path).name)
    out.discard("")
    return out


def _token_re(names: Iterable[str]) -> re.Pattern:
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9_.\-])(?:{alternatives})(?![A-Za-z0-9_\-]|\.[A-Za-z0-9])")


def mention_lines(text: str, names: Iterable[str]) -> list[int]:
    """1-based lines of ``text`` that name any of ``names`` as a whole word."""
    names = [n for n in names if n]
    if not names or not text:
        return []
    pattern = _token_re(names)
    return [i for i, line in enumerate(text.split("\n"), 1) if pattern.search(line)]


def text_files(folder: Path | None) -> list[tuple[str, str]]:
    """``[(relative path, text)]``: a skill's SKILL.md and its supporting text files
    (under references/, templates/, scripts/, assets/), at most :data:`MAX_FILES` of at
    most :data:`MAX_FILE_BYTES` each. Links are not followed; bytes that are not UTF-8
    are skipped."""
    import os

    if folder is None:
        return []
    root = Path(folder)
    out: list[tuple[str, str]] = []

    def read(path: Path) -> str | None:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                return None
            return path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError):
            return None

    md = read(root / _SKILL_FILE)
    if md is not None:
        out.append((_SKILL_FILE, md))
    for sub in _TEXT_DIRS:
        base = root / sub
        if base.is_symlink() or not base.is_dir():
            continue
        for here, dirs, files in os.walk(base, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                if len(out) > MAX_FILES:
                    return out
                text = read(Path(here) / name)
                if text is not None:
                    out.append(((Path(here) / name).relative_to(root).as_posix(), text))
    return out


# ── related_skills: the structured link a skill carries ─────────────────────────────

def _related(fm: dict | None) -> dict[str, list[str]]:
    """``{"top": [...], "hermes": [...]}`` for the related_skills keys present."""
    from .frontmatter import str_list

    out: dict[str, list[str]] = {}
    if not isinstance(fm, dict):
        return out
    if "related_skills" in fm:
        out["top"] = str_list(fm.get("related_skills"))
    metadata = fm.get("metadata")
    hermes = metadata.get("hermes") if isinstance(metadata, dict) else None
    if isinstance(hermes, dict) and "related_skills" in hermes:
        out["hermes"] = str_list(hermes.get("related_skills"))
    return out


def related_names(text: str) -> list[str]:
    """Every name the SKILL.md's related_skills keys list (both places)."""
    from .frontmatter import split_frontmatter

    fm, _body = split_frontmatter(text, lenient=False)
    seen: list[str] = []
    for names in _related(fm).values():
        seen.extend(n for n in names if n not in seen)
    return seen


def _without_related(fm: dict) -> dict:
    out = {k: v for k, v in fm.items() if k != "related_skills"}
    metadata = out.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("hermes"), dict):
        hermes = {k: v for k, v in metadata["hermes"].items() if k != "related_skills"}
        out["metadata"] = {**metadata, "hermes": hermes}
    return out


def _moved(names: list[str], old: set[str], new: str | None) -> list[str]:
    """``names`` with each one in ``old`` moved to ``new`` (dropped when ``new`` is None),
    never repeating a name."""
    out: list[str] = []
    for name in names:
        if name in old:
            if new is None:
                continue
            name = new
        if name not in out:
            out.append(name)
    return out


def _yaml_item(name: str) -> str:
    if _PLAIN_RE.match(name) and name not in _YAML_WORDS:
        return name
    return json.dumps(name, ensure_ascii=False)


def rewrite_related(text: str, old: set[str], new: str | None) -> str | None:
    """``text`` with every related_skills entry naming one of ``old`` moved to ``new``
    (an entry already naming ``new`` is not repeated; with ``new`` None the entries are
    dropped: the absorbing skill's own file never lists itself), or None when no
    related_skills key names ``old`` or the rewrite cannot be proved exact. Only the
    related_skills lines of the frontmatter change, and the result is parsed again: its
    lists must be exactly the moved ones and every other frontmatter key and the body
    unchanged."""
    from .frontmatter import split_frontmatter

    fm, body = split_frontmatter(text, lenient=False)
    if not isinstance(fm, dict):
        return None
    before = _related(fm)
    if not any(set(names) & old for names in before.values()):
        return None
    bom = "﻿" if text.startswith("﻿") else ""
    lines = text.removeprefix(bom).split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return None
    out = list(lines)
    i = 1
    edits: list[tuple[int, int, list[str]]] = []
    while i < end:
        match = _KEY_RE.match(lines[i])
        if not match:
            i += 1
            continue
        indent, value = match.group(1), match.group(2).split(" #", 1)[0].strip()
        j = i + 1
        while j < end:
            line = lines[j]
            stripped = line.strip()
            lead = len(line) - len(line.lstrip())
            if stripped and lead <= len(indent) and not (lead == len(indent) and stripped.startswith("-")):
                break
            j += 1
        while j > i + 1 and not lines[j - 1].strip():
            j -= 1                     # trailing blank lines belong to no list
        region = "\n".join([value] + [ln.strip() for ln in lines[i + 1:j]])
        current = _parse_list(region)
        if current is None:
            return None
        moved = _moved(current, old, new)
        if moved != current:
            if value and not value.startswith("["):
                return None            # a scalar list ("a, b"): not rewritten by hand
            if value or not moved:
                block = [f"{indent}related_skills: [{', '.join(_yaml_item(n) for n in moved)}]"]
            else:
                item = next((ln[: len(ln) - len(ln.lstrip())] for ln in lines[i + 1:j] if ln.strip()),
                            indent + "  ")
                block = [lines[i]] + [f"{item}- {_yaml_item(n)}" for n in moved]
            edits.append((i, j, block))
        i = j
    if not edits:
        return None
    for start, stop, block in reversed(edits):
        out[start:stop] = block
    result = bom + "\n".join(out)
    after_fm, after_body = split_frontmatter(result, lenient=False)
    if not isinstance(after_fm, dict) or after_body != body:
        return None
    after = _related(after_fm)
    if set(after) != set(before) or any(after[k] != _moved(before[k], old, new) for k in before):
        return None
    if _without_related(after_fm) != _without_related(fm):
        return None
    return result


def _parse_list(region: str) -> list[str] | None:
    """A related_skills value (flow list, block list) as names; None when it is not one."""
    import yaml

    from .frontmatter import str_list

    try:
        data = yaml.safe_load(region if region.strip() else "[]")
    except Exception:
        return None
    if data is None:
        return []
    if isinstance(data, (list, str)):
        return str_list(data)
    return None


# ── the holders outside the skills tree ──────────────────────────────────────────────

@dataclass
class Holders:
    """Where a skill can be named outside the skills tree. Each getter is read when a
    batch asks; one that fails is reported as unreadable, never as "nothing names it"."""

    jobs: Callable[[], list] = field(default=lambda: [])
    proposals: Callable[[], list[dict]] = field(default=lambda: [])
    batches: Callable[[], list[dict]] = field(default=lambda: [])
    bundles: Callable[[], list] | None = None
    switches: Callable[[], dict] | None = None
    load_set: Callable[[], dict] | None = None

    def bundle_list(self) -> list:
        if self.bundles is not None:
            return list(self.bundles())
        from . import bundles

        return bundles.snapshot()[0]

    def switch_state(self) -> dict:
        if self.switches is not None:
            return self.switches()
        from . import switches

        return switches.state()

    def load_lists(self) -> dict:
        if self.load_set is not None:
            return self.load_set()
        from agents.core import load_set

        return load_set.declared("skills")


def hub_holders(orch: Any = None) -> Holders:
    """The live hub's holders: its scheduled jobs, pending proposals and batches."""
    if orch is None:
        from agents.core.app_state import get_orch

        orch = get_orch()
    runner = getattr(orch, "jobs", None)
    job_store = getattr(runner, "store", None)
    proposals = getattr(orch, "skill_proposals", None)
    batches = getattr(orch, "skill_batches", None)
    return Holders(
        jobs=(lambda: list(job_store.list())) if job_store is not None else (lambda: []),
        proposals=(lambda: list(proposals.list("pending"))) if proposals is not None else (lambda: []),
        batches=(lambda: list(batches.list("pending"))) if batches is not None else (lambda: []),
    )


def _job_texts(job: Any) -> list[tuple[str, str]]:
    action = getattr(job, "action", None) or {}
    out = []
    for key in ("prompt", "message", "title"):
        value = action.get(key)
        if isinstance(value, str) and value:
            out.append((key, value))
    payload = action.get("payload")
    if payload:
        with contextlib.suppress(TypeError, ValueError):
            out.append(("payload", json.dumps(payload, ensure_ascii=False)))
    return out


def bundle_pin(members: Iterable[str]) -> str:
    """What a reviewer saw of one bundle: its member list, as a digest. A governed apply
    rewrites a bundle only while its members are still the ones the review showed."""
    return hashlib.sha256(json.dumps(list(members), ensure_ascii=False).encode("utf-8")).hexdigest()


def bundle_plan(deleted: dict[str, tuple[Any, str | None]], loaded: Iterable[Any], holders: Holders,
                allowed: Container[str] | None = None) -> tuple[list[dict], list[dict]]:
    """``(rewrites, left)`` for the bundles that list a deleted skill. ``deleted`` maps
    each deleted skill's name to ``(skill, absorbed_into)``. A bundle whose deleted
    members all have an absorbing skill is rewritten (``allowed``, when given, holds the
    bundle slugs that may be: the ones the owner saw); the rest are reported. Each
    rewrite carries its ``pin`` (:func:`bundle_pin` of the members before)."""
    from . import bundles

    pool = list(loaded)
    by_path = {str(Path(skill.path)): name for name, (skill, _new) in deleted.items()}
    rewrites, left = [], []
    for bundle in holders.bundle_list():
        hits: dict[str, str] = {}
        for member in bundle.skills:
            skill, _why = bundles.find_member(pool, member)
            if skill is not None and str(Path(skill.path)) in by_path:
                hits[member] = by_path[str(Path(skill.path))]
        if not hits:
            continue
        targets = {member: deleted[name][1] for member, name in hits.items()}
        if all(targets.values()) and (allowed is None or bundle.slug in allowed):
            members: list[str] = []
            for member in bundle.skills:
                name = targets.get(member) or member
                if name.casefold() not in {m.casefold() for m in members}:
                    members.append(name)
            rewrites.append({"holder": "bundle", "name": bundle.name, "slug": bundle.slug,
                             "skills": sorted(set(hits.values())), "before": list(bundle.skills),
                             "after": members, "pin": bundle_pin(bundle.skills), "bundle": bundle})
        else:
            for member, name in hits.items():
                left.append({"holder": "bundle", "name": bundle.name, "slug": bundle.slug, "skill": name,
                             "member": member,
                             "why": ("no absorbing skill named" if not targets[member] else
                                     "not in the batch the owner approved")})
    return rewrites, left


def outside(name: str, skill: Any, new: str | None, holders: Holders, *,
            exclude_batch: str | None = None) -> list[dict]:
    """Every holder outside the skills tree and the bundles that names ``skill`` (one
    deleted skill), each as a reported entry."""
    ids = identities(skill)
    keys = {i.casefold() for i in ids}
    left: list[dict] = []
    try:
        jobs = holders.jobs()
    except Exception:
        logger.warning("skill references: the scheduled jobs could not be read", exc_info=True)
        left.append({"holder": "job", "unreadable": True})
        jobs = []
    for job in jobs:
        for where, text in _job_texts(job):
            lines = mention_lines(text, ids)
            if lines:
                left.append({"holder": "job", "id": str(getattr(job, "id", "")),
                             "name": str(getattr(job, "name", "")), "field": where, "lines": lines[:MAX_LINES]})
    try:
        lists = holders.load_lists()
    except Exception:
        logger.warning("skill references: the load set could not be read", exc_info=True)
        left.append({"holder": "load_set", "unreadable": True})
        lists = {}
    for key, setting in (("disabled", "skills_disabled"), ("only", "skills_only")):
        if ids & set(lists.get(key) or []):
            left.append({"holder": "load_set", "setting": f"loadset.{setting}", "skill": name})
    only = list(lists.get("only") or [])
    if new and only and ids & set(only) and new not in only:
        left.append({"holder": "load_set", "setting": "loadset.skills_only", "skill": name,
                     "warning": f"{new!r} is not in skills_only, so it does not load after a restart"})
    try:
        state = holders.switch_state()
    except Exception:
        state = {"__unavailable__": True}
    if state.get("__unavailable__"):
        left.append({"holder": "switch", "unreadable": True})
    else:
        if keys & {str(n).casefold() for n in state.get("disabled") or []}:
            left.append({"holder": "switch", "setting": "skills.disabled", "skill": name})
        for channel, names in sorted((state.get("channel_disabled") or {}).items()):
            if keys & {str(n).casefold() for n in names or []}:
                left.append({"holder": "switch", "setting": "skills.channel_disabled", "channel": channel,
                             "skill": name})
    for getter, holder, key in ((holders.proposals, "proposal", "skill"), (holders.batches, "batch", "skills")):
        try:
            records = getter()
        except Exception:
            left.append({"holder": holder, "unreadable": True})
            continue
        for rec in records:
            if holder == "batch" and rec.get("id") == exclude_batch:
                continue
            named = rec.get(key)
            named = set(named) if isinstance(named, list) else {named}
            if ids & named:
                left.append({"holder": holder, "id": str(rec.get("id") or ""), "skill": name})
    return left


__all__ = [
    "Holders", "MAX_LEFT", "bundle_pin", "bundle_plan", "hub_holders", "identities", "mention_lines", "outside",
    "related_names", "rewrite_related", "text_files",
]
