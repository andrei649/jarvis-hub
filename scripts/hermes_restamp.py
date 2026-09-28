#!/usr/bin/env python3
"""Map drifted Hermes evidence back to what a review pinned, then restamp it honestly.

`hermes_status.py` owns every rule: the review schema, the file hash and the citation
screen. This helper reuses those rules to answer the three questions a restamp needs:

  drift ID... | --all-stale   For each pinned file: the pinned hash, the current one, and
                              the commit(s), on any branch, whose blob hashes to the pin.
  cite ID                     Where each `path:line` citation of the review sits now:
                              unchanged, moved, edited, deleted or ambiguous, never guessed,
                              plus the diff hunks that touch the cited lines.
  stamp --patch FILE          The only write: put re-read reviews into docs/hermes/assessment.json.

A patch is a JSON list of {id, status, summary, remaining, evidence: [paths]}. Hashes are
always recomputed from the working tree, and the result must pass hermes_status with every
patched row current, or nothing is written. A hash-only restamp stays forbidden
(docs/HERMES_SPRINT.md): re-read the row, then stamp what you read.

cite and stamp read the working tree, as hermes_status does. So a stamp also refuses
evidence that only this checkout holds, which every other checkout would read as stale:
  - evidence reached through a symlink, file or directory (always): hs hashes the target's
    text, git holds the link, and a checkout without symlinks (core.symlinks=false,
    Windows' default) holds a text file there, which the index still records as a link,
    so both are refused; pin the file it points to instead;
  - evidence that is untracked or gitignored (always);
  - evidence whose bytes the recorded base_sha does not hold (an uncommitted edit, a
    staged new file, a --base-sha older than the file), unless --allow-uncommitted is
    given; then each such file is printed as UNCOMMITTED, ahead of any --dry-run diff;
  - evidence the stamp itself rewrites (docs/hermes/assessment.json) or that
    `hermes_status.py write` regenerates (hs.reports()): it would be stale on arrival.

cite numbers lines as hermes_status does (str.splitlines, which also breaks at U+2028 and
friends) and moves each cited range onto git's \\n-only numbering before it meets a hunk.
A place it finds away from the lines that anchored a citation (moved and edited), or a
unique copy (unchanged or moved) that a pinned neighbour no longer flanks, is flagged
"confirm by reading". Cited text still at its own line numbers is unchanged, whatever was
added beside it, unless an edit that both pinned neighbours still flank sits where the
lines were (a function copied above itself, then the original edited): the copy may have
taken the cited numbers, so both places are candidates (ambiguous). A look-alike inserted
right above a line is, by design, such a rival too, since it reads exactly like the line
edited in place with a copy added below. A file renamed to several files is never
followed to one of them. Known gap: a committed symlink replaced by a regular file and
not yet staged is still refused as a link, even with --allow-uncommitted; stage the
typechange (`git add`) and it is treated as an ordinary uncommitted edit.

Exit codes: 0 done; 1 refused or unknown row; 2 error (unreadable records, git failure).
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import io
import json
import os
import re
import stat
import subprocess  # nosec B404  # fixed git argv lists only, never a shell
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import hermes_status as hs  # noqa: E402

PATCH_FIELDS = ("id", "status", "summary", "remaining", "evidence")
ROW = re.compile(r"H\d{3}")
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@")
CUTOFF = 0.6      # below this difflib ratio the cited text is gone, not edited
TIE = 0.05        # two places scoring this close cannot be told apart: ambiguous
MAX_REGION = 400  # an anchored gap wider than this is a rewrite, not a location
SHORT = 3         # blocks up to this many lines are compared character by character
VOUCHED = 2       # unchanged lines that must vouch for a place found away from the anchors
SHOWN = 5         # commits listed per pin; the rest are counted


class Refused(Exception):
    """stamp found a reason not to write; nothing was written."""


class UnknownRow(LookupError):
    """The id names no inventory row (or, for cite, a row with no review)."""


class GitError(RuntimeError):
    """A git command failed."""


def git(root: Path, *args: str, stdin: bytes | None = None,
        ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[bytes]:
    """Run one read-only git command in `root`; user config cannot reshape its output."""
    argv = ["git", "--no-pager", "--literal-pathspecs", "-c", "core.quotepath=off",
            "-c", "color.ui=never", "-c", "log.showSignature=false", "-c", "log.follow=false",
            "-C", str(root), *args]
    proc = subprocess.run(  # noqa: S603  # nosec B603  # fixed git argv, no shell
        argv, input=stdin, capture_output=True, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    if proc.returncode not in ok:
        detail = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
        raise GitError(f"git {args[0]}: {detail}")
    return proc


# --- hashing: hermes_status's own rule, applied to git blobs ---------------------------------

class _Blob:
    """A git blob behind the one method `hs.file_digest` calls.

    hs.file_digest hashes `path.read_text(encoding="utf-8")`: a text-mode open whose
    universal newlines turn CRLF and a lone CR into LF. The same TextIOWrapper over the
    blob's bytes lets hermes_status hash history with its own rule, so the rule lives in
    one place; if hs ever stops reading text this way, this fails loudly instead of
    quietly hashing differently.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read_text(self, encoding: str = "utf-8") -> str:
        return io.TextIOWrapper(io.BytesIO(self._data), encoding=encoding).read()


def blob_text(data: bytes) -> str | None:
    """The blob as hermes_status reads a file, or None when it is not UTF-8."""
    try:
        return _Blob(data).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def blob_digest(data: bytes) -> str | None:
    """`hs.file_digest` of a blob's bytes, or None when it is not UTF-8 (hs cannot hash it)."""
    try:
        return hs.file_digest(_Blob(data))  # type: ignore[arg-type]
    except UnicodeDecodeError:
        return None


def _evidence_digest(path: Path) -> str:
    return hs.file_digest(path)


# --- drift: find the pinned bytes in history -------------------------------------------------

@dataclass
class Pin:
    path: str
    pinned: str
    state: str = ""               # current | drifted | absent | non-utf8
    current: str | None = None    # digest of the working-tree file
    found: str = ""               # holds | found | unrecoverable | shallow | incomplete
    blobs: list[str] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    more_commits: int = 0
    searched: int = 0
    non_utf8: int = 0
    moved_to: list[str] = field(default_factory=list)
    removed_in: str = ""
    text: str | None = None       # the pinned version, as hermes_status reads it
    raw: str | None = None        # the same, newlines untranslated, as git numbers its lines

    def public(self) -> dict:
        view = asdict(self)
        view.pop("text")
        view.pop("raw")
        return view


class History:
    """Read-only questions to one checkout's history; each path is searched once."""

    def __init__(self, root: Path, base_sha: str = "") -> None:
        self.root = root
        self.base_sha = base_sha
        self._blobs: dict[str, dict[str, dict]] = {}
        self._shallow: bool | None = None

    def git(self, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return git(self.root, *args, **kwargs)

    @property
    def shallow(self) -> bool:
        if self._shallow is None:
            out = self.git("rev-parse", "--is-shallow-repository").stdout
            self._shallow = out.strip() == b"true"
        return self._shallow

    def blobs(self, path: str) -> dict[str, dict]:
        """Every blob `path` held on any branch: its hs digest and the commits around it."""
        if path in self._blobs:
            return self._blobs[path]
        out = self.git("log", "--all", "--full-history", "--diff-merges=separate", "--no-abbrev",
                       "--format=%x01%H", "--raw", "--", path).stdout.decode("utf-8", "replace")
        blobs: dict[str, dict] = {}
        commit = ""
        for line in out.splitlines():
            if line.startswith("\x01"):
                commit = line[1:]
                continue
            meta = line.split("\t", 1)[0].split()
            if not (line.startswith(":") and commit and len(meta) >= 5):
                continue
            for sha, role in ((meta[3], "introduced"), (meta[2], "replaced")):
                if sha.strip("0"):   # all zeros: no blob on that side (added or deleted)
                    entry = blobs.setdefault(sha, {"kind": "missing", "digest": None,
                                                   "introduced": [], "replaced": []})
                    if commit not in entry[role]:
                        entry[role].append(commit)
        for sha, data in self._cat(list(blobs)).items():   # each distinct blob hashed once
            digest = blob_digest(data)
            blobs[sha].update(kind="text" if digest else "non-utf8", digest=digest)
        self._blobs[path] = blobs
        return blobs

    def _cat(self, shas: list[str]) -> dict[str, bytes]:
        if not shas:
            return {}
        out = self.git("cat-file", "--batch", stdin="".join(f"{sha}\n" for sha in shas).encode()).stdout
        found: dict[str, bytes] = {}
        pos = 0
        while pos < len(out):
            end = out.index(b"\n", pos)
            head = out[pos:end].split()
            pos = end + 1
            if len(head) == 3:   # "<sha> <type> <size>", the content, a newline
                size = int(head[2])
                if head[1] == b"blob":
                    found[head[0].decode()] = out[pos:pos + size]
                pos += size + 1
            # "<sha> missing": the object is not in this clone
        return found

    def is_ancestor(self, commit: str, of: str) -> bool | None:
        code = self.git("merge-base", "--is-ancestor", commit, of, ok=(0, 1, 128)).returncode
        return None if code == 128 else code == 0

    def describe(self, commits: list[str]) -> tuple[list[dict], int]:
        """Newest first: date, subject, whether HEAD and the last restamp base contain it."""
        if not commits:
            return [], 0
        out = self.git("log", "--no-walk=unsorted", "--format=%H%x09%ct%x09%cs%x09%s",
                       *commits, "--").stdout.decode("utf-8", "replace")
        rows = [(line.split("\t", 3) + ["", "", ""])[:4] for line in out.splitlines() if line]
        rows.sort(key=lambda row: -int(row[1] or 0))
        shown = []
        for sha, _, day, subject in rows[:SHOWN]:
            on_head = self.is_ancestor(sha, "HEAD")
            base = self.base_sha
            shown.append({
                "sha": sha, "date": day, "subject": subject, "on_head": on_head,
                "predates_base": bool(base) and sha != base and bool(self.is_ancestor(sha, base)),
                "branches": [] if on_head else self.branches(sha),
            })
        return shown, len(rows) - len(shown)

    def branches(self, commit: str) -> list[str]:
        out = self.git("for-each-ref", "--contains", commit, "--format=%(refname:short)",
                       "refs/heads", "refs/remotes").stdout.decode("utf-8", "replace")
        return out.split()[:6]

    def whereabouts(self, path: str, hops: int = 5) -> tuple[str, list[str]]:
        """The commit on HEAD's history that removed `path`, and where a rename took it."""
        removed = self.git("log", "-1", "--format=%H", "--diff-filter=D", "HEAD", "--",
                           path).stdout.decode().strip()
        if not removed:
            return "", []
        tokens = self.git("diff-tree", "-r", "-m", "-M", "--no-commit-id", "--name-status", "-z",
                          "--root", removed).stdout.decode("utf-8", "replace").split("\0")
        targets, pos = [], 0
        while pos < len(tokens) - 1:
            status = tokens[pos]
            if status[:1] in ("R", "C"):
                if status[0] == "R" and tokens[pos + 1] == path:
                    targets.append(tokens[pos + 2])
                pos += 3
            else:
                pos += 2
        moved: list[str] = []
        for target in dict.fromkeys(targets):
            if (self.root / target).is_file():
                moved.append(target)
            elif hops:   # renamed again later: follow it a few hops
                moved.extend(self.whereabouts(target, hops - 1)[1])
        return removed, moved

    def locate(self, entry: dict) -> Pin:
        """Where the exact bytes a review hashed for one evidence path can still be found."""
        pin = Pin(entry["path"], entry["sha256"])
        file = self.root / pin.path
        try:
            _, holds = hs._evidence(self.root, entry)   # hs's own path rules and hash check
        except UnicodeDecodeError:
            pin.state = "non-utf8"
        else:
            if file.is_file():
                pin.state = "current" if holds else "drifted"
                pin.current = pin.pinned if holds else hs.file_digest(file)
            else:
                pin.state = "absent"
                pin.removed_in, pin.moved_to = self.whereabouts(pin.path)
        if pin.state == "current":
            pin.found, pin.text = "holds", file.read_text(encoding="utf-8")
            return pin
        blobs = self.blobs(pin.path)
        pin.searched = len(blobs)
        pin.non_utf8 = sum(blob["kind"] == "non-utf8" for blob in blobs.values())
        pin.blobs = sorted(sha for sha, blob in blobs.items() if blob["digest"] == pin.pinned)
        if not pin.blobs:
            missing = any(blob["kind"] == "missing" for blob in blobs.values())
            pin.found = "shallow" if self.shallow else "incomplete" if missing else "unrecoverable"
            return pin
        pin.found = "found"
        commits = [commit for sha in pin.blobs for commit in blobs[sha]["introduced"]]
        pin.commits, pin.more_commits = self.describe(list(dict.fromkeys(commits)))
        data = self.git("cat-file", "blob", pin.blobs[0]).stdout
        pin.text, pin.raw = blob_text(data), data.decode("utf-8")   # it hashed, so it decodes
        return pin


def _row_id(ident: str, caps: list) -> str:
    ident = ident.strip().upper()
    if not ROW.fullmatch(ident) or not 1 <= int(ident[1:]) <= len(caps):
        raise UnknownRow(f"unknown row: {ident}")
    return ident


def drift(root: Path, ids: list[str] | None = None, *, all_stale: bool = False) -> list[dict]:
    ledger, data = hs.load(root)
    caps = ledger["capabilities"]
    try:
        live, error = {row["id"]: row for row in hs.assess(ledger, data, root)}, ""
    except (ValueError, TypeError, KeyError, OSError) as exc:
        live, error = {}, str(exc)
    if all_stale:
        if error:
            raise ValueError(f"hermes_status cannot assess the records ({error}); name the rows instead")
        ids = [ident for ident, row in live.items() if row["basis"] == "stale_evidence"]
    wanted = list(dict.fromkeys(_row_id(ident, caps) for ident in ids or []))
    reviews = {item["id"]: item for item in data["reviews"] if isinstance(item, dict) and "id" in item}
    history = History(root, data.get("base_sha", ""))
    report = []
    for ident in wanted:
        row, item = live.get(ident, {}), reviews.get(ident)
        report.append({
            "id": ident, "name": caps[int(ident[1:]) - 1].get("name", ""),
            "status": row.get("status"), "basis": row.get("basis"), "assess_error": error or None,
            "recorded": item.get("status") if item else None,
            "pins": [history.locate(entry).public() for entry in item["evidence"]] if item else [],
        })
    return report


# --- cite: where each citation sits now ------------------------------------------------------

def _resolve(citation: str, pinned: list[str]) -> str | None:
    """The pinned path a citation names by hermes_status's own screen, or None when hs ignores it.

    hs._cited_lines reports a citation only when its name resolves to exactly one pinned
    path (the exact path or a unique '/'-suffix) and the line misses. Against empty
    stand-ins every resolvable citation misses, so hs itself decides whether, and to
    which path, a citation resolves.
    """
    if not hs._cited_lines(citation, dict.fromkeys(pinned, [])):
        return None
    return next(path for path in pinned if hs._cited_lines(citation, {path: []}))


def _neighbours(lines: list[str], start: int, end: int) -> tuple[str | None, str | None]:
    """The nearest non-blank line above and below lines[start:end]; None at the file's edge."""
    above = next((lines[i] for i in range(start - 1, -1, -1) if lines[i].strip()), None)
    below = next((lines[i] for i in range(end, len(lines)) if lines[i].strip()), None)
    return above, below


def _result(kind: str, *, now: list[int] | None = None, candidates: list[list[int]] | None = None,
            anchored: bool | None = None, similarity: float | None = None) -> dict[str, Any]:
    return {"class": kind, "now": now, "candidates": candidates or [], "anchored": anchored,
            "similarity": similarity}


def _agreement(context: tuple[str | None, str | None], current: list[str], j: int, n: int) -> int:
    """How many of the pinned neighbours (0, 1 or 2) still flank current[j:j + n]."""
    return sum(a == b for a, b in zip(context, _neighbours(current, j, j + n), strict=True))


def classify(pinned: list[str], first: int, last: int, current: list[str]) -> dict[str, Any]:
    """Where pinned lines first..last (1-based, inclusive) sit in `current`, by content only.

    A file that did not change places every citation where it was. So does a unique exact
    copy still at the cited numbers, whatever was added around it (anchored says whether
    both neighbours stayed too), unless both unchanged neighbours still flank an edit
    between the anchors: the copy may then be a look-alike that took the cited numbers
    (a function copied above itself, the original then edited), so it is ambiguous. An exact
    unique copy elsewhere wins when both unchanged neighbours still flank it; with fewer,
    an edit where the lines were, flanked at least as well, makes it ambiguous, as does,
    for a copy that kept neither neighbour, a region between the anchors too wide to
    search (MAX_REGION); a copy with no such rival is placed but flagged (anchored
    False). A look-alike inserted right above a line is such a rival: it reads exactly
    like the line edited in place with a copy added below, so that case stays ambiguous
    by design. Several exact copies are told apart only by unchanged neighbours on both
    sides; otherwise the citation is ambiguous. With no exact copy, the whole-file
    alignment bounds where the text can be, and a difflib ratio inside those bounds finds
    it (edited). When nothing there resembles it, the whole file is searched, since the
    block may have moved as well as changed (edited, flagged); a place there needs
    VOUCHED distinct unchanged lines vouching for it. When nothing anywhere resembles it,
    it is deleted, unless a third of its lines still sit between the same anchors: then
    it was rewritten in place and the whole region is the (ambiguous) answer. Nothing is
    ever guessed.
    """
    start, end = first - 1, last
    if pinned == current:   # the pin holds: every line is where it was, repeated or not
        return _result("unchanged", now=[first, last], anchored=True)
    block = pinned[start:end]
    size = len(block)
    context = _neighbours(pinned, start, end)
    hits = [j for j in range(len(current) - size + 1) if current[j:j + size] == block]

    def at(j: int, anchored: bool) -> dict[str, Any]:
        return _result("unchanged" if j == start else "moved", now=[j + 1, j + size], anchored=anchored)

    if len(hits) == 1:
        hit = hits[0]
        agree = _agreement(context, current, hit, size)
        if agree < 2:
            # Away from the cited numbers an edit flanked as well as the copy is a rival. At them
            # only one that both pinned neighbours still flank is: then the copy may be a
            # look-alike that took the cited numbers, and the edit the cited line itself.
            need = agree if hit != start else 2
            rivals = _in_place(pinned, start, end, current, (hit, hit + size), need)
            if rivals:
                return _result("ambiguous", candidates=sorted([[hit + 1, hit + size], *rivals]))
        return at(hit, agree == 2)
    if hits:
        agreed = [j for j in hits if _neighbours(current, j, j + size) == context]
        if len(agreed) == 1:
            return at(agreed[0], True)
        return _result("ambiguous", candidates=[[j + 1, j + size] for j in hits])
    return _nearest(pinned, start, end, current)


def _region(pinned: list[str], start: int, end: int, current: list[str]) -> tuple[int, int, bool]:
    """current[lo:hi], between the nearest lines around pinned[start:end] the whole-file
    alignment kept unchanged, and whether any such anchor exists."""
    kept: dict[int, int] = {}
    for tag, i1, i2, j1, _ in difflib.SequenceMatcher(None, pinned, current).get_opcodes():
        if tag == "equal":
            kept.update((i1 + k, j1 + k) for k in range(i2 - i1))
    above = next((i for i in range(start - 1, -1, -1) if i in kept), None)
    below = next((i for i in range(end, len(pinned)) if i in kept), None)
    lo = kept[above] + 1 if above is not None else 0
    hi = kept[below] if below is not None else len(current)
    return lo, hi, above is not None or below is not None


def _scan(block: list[str], current: list[str], lo: int, hi: int, *, rising: bool = True,
          skip: tuple[int, int] | None = None,
          keep: Callable[[int, int], bool] | None = None) -> list[tuple[float, int, int]]:
    """(ratio, first index, length) of the windows of current[lo:hi] that resemble `block`.

    With `rising`, a window must also come within TIE of the best one seen so far, which
    only prunes windows that could never tie with the best. Windows overlapping `skip`
    (a [first, end) index pair), or that `keep(first, length)` rejects, are not scored.
    """
    size = len(block)
    # A few lines compare as characters, so a one-line edit still resembles itself; a longer
    # block compares whitespace-stripped lines, so re-indenting is not an edit and a
    # 40-line citation does not cost minutes.
    short = size <= SHORT

    def shape(lines: list[str]) -> str | list[str]:
        return "\n".join(lines) if short else [line.strip() for line in lines]

    target = shape(block)
    scored: list[tuple[float, int, int]] = []
    floor = CUTOFF
    for length in sorted({max(1, size - 1), size, size + 1}):
        for j in range(lo, max(lo, hi - length) + 1):
            window = current[j:min(j + length, hi)]
            if not window or (skip and j < skip[1] and j + len(window) > skip[0]) \
                    or (keep and not keep(j, len(window))):
                continue
            matcher = difflib.SequenceMatcher(None, target, shape(window), autojunk=False)
            if matcher.real_quick_ratio() < floor or matcher.quick_ratio() < floor:
                continue
            ratio = matcher.ratio()
            if ratio >= floor:
                scored.append((ratio, j, len(window)))
                if rising:
                    floor = max(floor, ratio - TIE)
    return scored


def _spots(scored: list[tuple[float, int, int]], size: int) -> list[tuple[float, int, int]]:
    """The best-scoring window of each non-overlapping place, best first; at equal scores
    a window of the cited length, then the earlier one, wins."""
    chosen: list[tuple[float, int, int]] = []
    for ratio, j, n in sorted(scored, key=lambda s: (-s[0], s[2] != size, s[1])):
        if all(j >= cj + cn or j + n <= cj for _, cj, cn in chosen):
            chosen.append((ratio, j, n))
    return chosen


def _choose(scored: list[tuple[float, int, int]], size: int, anchored: bool) -> dict[str, Any]:
    """edited at the best place, or ambiguous when another place scores within TIE of it."""
    best, *others = _spots(scored, size)
    rivals = [spot for spot in others if spot[0] >= best[0] - TIE]
    if rivals:
        return _result("ambiguous", candidates=sorted([j + 1, j + n] for _, j, n in (best, *rivals)),
                       anchored=anchored)
    return _result("edited", now=[best[1] + 1, best[1] + best[2]], anchored=anchored,
                   similarity=round(best[0], 2))


def _in_place(pinned: list[str], start: int, end: int, current: list[str],
              skip: tuple[int, int], need: int) -> list[list[int]]:
    """Where an in-place edit of pinned[start:end] could be (1-based [first, last] pairs):
    the places between its anchors that resemble it, other than the exact copy at `skip`,
    that at least `need` (0, 1 or 2) of its pinned neighbours still flank.

    Only windows flanked that well are scored, and all of them (no rising floor): the
    best-scoring window at a place may be flanked worse than a weaker one. So a rival that
    must keep a neighbour is checked cheaply between anchors of any width. With need 0
    every window is a candidate: a region wider than MAX_REGION is then a rewrite, as in
    _nearest, not searched, and all of it is the answer.

    With need 2 the whole file is searched: only windows both pinned neighbours flank
    count, and difflib may have aligned the pinned lines with a copy elsewhere, leaving
    the flanked edit outside the anchored region.
    """
    lo, hi, _ = _region(pinned, start, end, current)
    if need == 2:
        lo, hi = 0, len(current)
    if not need and hi - lo > MAX_REGION:
        return [[lo + 1, hi]]
    context = _neighbours(pinned, start, end)
    scored = _scan(pinned[start:end], current, lo, hi, rising=False, skip=skip,
                   keep=lambda j, n: _agreement(context, current, j, n) >= need)
    return [[j + 1, j + n] for _, j, n in _spots(scored, end - start)]


def _distinct(pinned: list[str]) -> set[str]:
    """The non-blank texts (whitespace-stripped) that occur exactly once in `pinned`."""
    counts = Counter(line.strip() for line in pinned)
    return {text for text, count in counts.items() if count == 1 and text}


def _vouched(pinned: list[str], start: int, end: int, current: list[str], j: int, n: int,
             distinct: set[str]) -> int:
    """Unchanged lines vouching for current[j:j + n] as the new place of pinned[start:end]:
    the block's own lines found in it (whitespace aside), plus the pinned neighbours that
    still flank it. Only a line whose text is `distinct` (once in the pinned file) vouches:
    `}`, `return null;`, `try:` or `pass` turn up in every block of the same shape."""
    lines = {line.strip() for line in current[j:j + n]}
    own = {line.strip() for line in pinned[start:end]} & distinct
    flank = zip(_neighbours(pinned, start, end), _neighbours(current, j, j + n), strict=True)
    return len(own & lines) + sum(a == b and a.strip() in distinct for a, b in flank if a is not None)


def _nearest(pinned: list[str], start: int, end: int, current: list[str]) -> dict[str, Any]:
    lo, hi, anchored = _region(pinned, start, end, current)
    if hi - lo > MAX_REGION:
        return _result("ambiguous", candidates=[[lo + 1, hi]], anchored=anchored)
    block = pinned[start:end]
    scored = _scan(block, current, lo, hi)
    if scored:
        return _choose(scored, len(block), anchored)
    # Nothing between the anchors resembles it: it may have moved as well as changed. Away
    # from its anchors a look-alike is cheap (every `def x():\n    return y` resembles every
    # other), so a place there also needs two distinct unchanged lines vouching for it.
    distinct = _distinct(pinned)
    far = [] if (lo, hi) == (0, len(current)) else [
        spot for spot in _scan(block, current, 0, len(current), rising=False)
        if _vouched(pinned, start, end, current, spot[1], spot[2], distinct) >= VOUCHED]
    region = {line.strip() for line in current[lo:hi]}
    lines = [line.strip() for line in block if line.strip()]
    rewritten = bool(lines) and 3 * sum(line in region for line in lines) >= len(lines)
    if rewritten:   # rewritten in place, and perhaps also copied elsewhere: never guessed
        best = max((ratio for ratio, _, _ in far), default=0.0)
        spots = [[j + 1, j + n] for ratio, j, n in _spots(far, len(block)) if ratio >= best - TIE]
        return _result("ambiguous", candidates=sorted([[lo + 1, hi], *spots]), anchored=anchored)
    if far:
        return _choose(far, len(block), anchored=False)   # found away from its anchors
    return _result("deleted", anchored=anchored)


def _overlaps(start: int, count: int, first: int, last: int) -> bool:
    if count == 0:   # lines inserted after `start`
        return first <= start < last
    return start <= last and start + count - 1 >= first


def _git_lines(raw: str) -> list[int]:
    """The 1-based line git numbers each line hermes_status numbers, in one file's text.

    hermes_status numbers lines with str.splitlines(), which also breaks at a lone CR, \\v,
    \\f, \\x1c-\\x1e, \\x85, U+2028 and U+2029; git breaks at \\n only. `raw` is the text with
    its newlines untranslated; its splitlines() are exactly hermes_status's lines.
    """
    numbers, line = [], 1
    for piece in raw.splitlines(keepends=True):
        numbers.append(line)
        line += piece.count("\n")
    return numbers


def _hunks(history: History, path: str, view: dict, ranges: list[tuple[int, int]]) -> list[str]:
    """`git diff <pinned commit> -- <path>` hunks whose pinned side overlaps a cited range.

    Citations count lines as hermes_status does and git counts \\n alone, so each cited
    range is moved onto git's numbering first, and git's output is split on \\n alone.
    """
    numbers = view["_numbers"]
    if view["found"] != "found" or not view["commit"] or not view["now_path"] or numbers is None:
        return []
    spans = [(numbers[first - 1], numbers[last - 1]) for first, last in ranges
             if 1 <= first <= last <= len(numbers)]
    if not spans:
        return []
    paths = [path] if view["now_path"] == path else [path, view["now_path"]]
    out = history.git("diff", "--no-ext-diff", "--no-color", "--ignore-cr-at-eol", "-M", "-U3",
                      view["commit"], "--", *paths).stdout.decode("utf-8", "replace")
    hunks: list[list[str]] = []
    hunk: list[str] | None = None
    for line in out.split("\n"):
        if HUNK.match(line):
            hunk = [line]
            hunks.append(hunk)
        elif hunk is not None and line[:1] in (" ", "+", "-", "\\"):
            hunk.append(line)
        else:
            hunk = None
    kept = []
    for lines in hunks:
        match = HUNK.match(lines[0])
        start, count = int(match.group(1)), int(match.group(2) or 1)
        if any(_overlaps(start, count, first, last) for first, last in spans):
            kept.append("\n".join(lines))
    return kept


def _view(history: History, entry: dict) -> dict:
    pin = history.locate(entry)
    path = pin.path
    if (history.root / path).is_file():
        now_path = path
    else:
        now_path = pin.moved_to[0] if len(pin.moved_to) == 1 else None
    current = None
    if now_path and pin.state != "non-utf8":
        current = (history.root / now_path).read_text(encoding="utf-8").splitlines()
    return {"found": pin.found, "state": pin.state, "commit": pin.commits[0]["sha"] if pin.commits else "",
            "now_path": now_path, "moved_to": pin.moved_to, "hunks": [],
            "_pinned": pin.text.splitlines() if pin.text is not None else None, "_current": current,
            "_numbers": _git_lines(pin.raw) if pin.raw is not None else None}


def _place(citation: str, name: str, path: str, first: int, last: int, view: dict) -> dict:
    entry: dict[str, Any] = {
        "citation": citation, "path": path, "first": first, "last": last, "class": "",
        "now_path": view["now_path"], "now": None, "suggest": None, "resolves": None,
        "candidates": [], "anchored": None, "similarity": None,
        "pinned_text": [], "current_text": [],
    }
    pinned, current = view["_pinned"], view["_current"]
    if pinned is None:   # the pinned text itself is gone: unrecoverable, shallow or incomplete
        entry["class"] = view["found"]
        return entry
    if hs._cited_lines(citation, {path: pinned}):
        entry["class"] = "invalid"   # it never resolved, even in the version it pinned
        return entry
    entry["pinned_text"] = pinned[first - 1:last]
    if current is None:   # not UTF-8 now, renamed to several files (never picked), or deleted
        entry["class"] = "non-utf8" if view["state"] == "non-utf8" else \
            "ambiguous" if len(view["moved_to"]) > 1 else "deleted"
        return entry
    entry.update(classify(pinned, first, last, current))
    if entry["now"]:
        a, b = entry["now"]
        moved_file = view["now_path"] != path
        if moved_file and entry["class"] == "unchanged":
            entry["class"] = "moved"
        label = view["now_path"] if moved_file else name
        entry["current_text"] = current[a - 1:b]
        entry["suggest"] = f"{label}:{a}" if a == b else f"{label}:{a}-{b}"
        entry["resolves"] = not hs._cited_lines(entry["suggest"], {view["now_path"]: current})
    return entry


def cite(root: Path, ident: str) -> dict:
    ledger, data = hs.load(root)
    caps = ledger["capabilities"]
    ident = _row_id(ident, caps)
    item = next((r for r in data["reviews"] if isinstance(r, dict) and r.get("id") == ident), None)
    if item is None:
        raise UnknownRow(f"{ident} has no review: nothing is pinned, so nothing can be cited")
    evidence = {entry["path"]: entry for entry in item["evidence"]}
    pinned = list(evidence)
    history = History(root, data.get("base_sha", ""))
    files: dict[str, dict] = {}
    citations: list[dict] = []
    ignored: list[str] = []
    for match in hs.CITATION.finditer(f"{item['summary']}\n{item['remaining']}"):
        citation = match.group(0)
        path = _resolve(citation, pinned)
        if path is None:
            ignored.append(citation)
            continue
        if path not in files:
            files[path] = _view(history, evidence[path])
        first = int(match.group(2))
        citations.append(_place(citation, match.group(1), path, first, int(match.group(3) or first),
                                files[path]))
    for path, view in files.items():
        ranges = [(c["first"], c["last"]) for c in citations if c["path"] == path]
        view["hunks"] = _hunks(history, path, view, ranges)
        del view["_pinned"], view["_current"], view["_numbers"]
    return {"id": ident, "name": caps[int(ident[1:]) - 1].get("name", ""), "recorded": item["status"],
            "citations": citations, "ignored": ignored, "files": files}


# --- stamp: the only write -------------------------------------------------------------------

def _serialize(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _patch_items(patch: Any) -> list[dict]:
    if not isinstance(patch, list):
        raise Refused("the patch must be a JSON list of reviews")
    if not patch:
        raise Refused("the patch is empty: there is nothing to stamp")
    for item in patch:
        if not isinstance(item, dict) or set(item) != set(PATCH_FIELDS):
            raise Refused(f"each patch entry needs exactly the fields {', '.join(PATCH_FIELDS)}")
        ident, status, remaining = item["id"], item["status"], item["remaining"]
        if status in ("excluded", "needs_review"):
            raise Refused(f"{ident}: a patch cannot record {status}; scope and staleness are derived")
        if status in ("partial", "missing") and isinstance(remaining, str) and not remaining.strip():
            raise Refused(f"{ident}: a {status} row must name what is left; remaining is "
                          "empty or whitespace-only")
        if not isinstance(item["evidence"], list) or not all(isinstance(p, str) for p in item["evidence"]):
            raise Refused(f"{ident}: evidence must be a list of repository paths; hashes are recomputed")
    return patch


def _pin(root: Path, ident: str, name: str) -> dict:
    try:   # hs's own path rules run before anything is hashed
        hs._evidence(root, {"path": name, "sha256": "0" * 64})
    except UnicodeDecodeError as exc:
        raise Refused(f"{ident}: {name} is not UTF-8 text; hermes_status cannot hash it") from exc
    except ValueError as exc:
        raise Refused(f"{ident}: {name}: {exc}") from exc
    file = root / name
    if not file.is_file():
        raise Refused(f"{ident}: evidence {name} is not a file in the working tree")
    return {"path": name, "sha256": _evidence_digest(file)}


def _generated(root: Path, reviews: dict[str, dict], rows: list[dict], result: dict) -> None:
    """Refuse evidence that this stamp rewrites or `hermes_status.py write` regenerates:
    the records file and hs.reports()'s pages. Its pin would be stale on arrival."""
    generated = {(root / name).resolve() for name in (hs.ASSESSMENT, *hs.reports(rows, result))}
    for ident, review in reviews.items():
        for entry in review["evidence"]:
            if (root / entry["path"]).resolve() in generated:
                raise Refused(f"{ident}: evidence {entry['path']} is generated (by this stamp, or by "
                              "`hermes_status.py write`), so its pin would be stale on arrival")


def _prefixes(name: str) -> list[str]:
    """Every leading part of the repository path `name`, shortest first, itself last."""
    parts = name.split("/")
    return ["/".join(parts[:k]) for k in range(1, len(parts) + 1)]


def _index_links(root: Path, names: list[str]) -> set[str]:
    """The paths git's index records as symlinks (mode 120000) at or under any leading part
    of `names`; _symlink asks only about the leading parts themselves.

    A checkout without symlinks (core.symlinks=false, Windows' default) writes a committed
    link as a plain text file holding its target's path, so only the index still knows.
    """
    wanted = dict.fromkeys(prefix for name in names for prefix in _prefixes(name))
    out = git(root, "ls-files", "-s", "-z", "--", *wanted).stdout.decode("utf-8", "replace")
    records = (record.partition("\t") for record in out.split("\0"))   # "<mode> <object> <stage>\t<path>"
    return {path for meta, _, path in records if meta.split(" ", 1)[0] == "120000"}


def _symlink(root: Path, name: str, links: set[str]) -> str:
    """The first leading part of the repository path `name` that is a symlink, or "": one
    this checkout holds as a link, or one the index records as a link (`links`)."""
    return next((prefix for prefix in _prefixes(name) if prefix in links or (root / prefix).is_symlink()), "")


def _uncommitted(root: Path, base: str, reviews: dict[str, dict]) -> list[str]:
    """Evidence whose pinned bytes the commit `base` does not hold at that path.

    Evidence reached through a symlink, untracked or gitignored refuses outright: git holds
    a link's target path, not the text hermes_status hashes (and a checkout without
    symlinks writes the link as a text file, which the index still records as a link), and
    no commit can hold an untracked file. What comes back (an uncommitted edit, a staged new
    file, a base_sha that predates the file) reads stale on every checkout but this one, so
    the caller refuses it unless told otherwise.
    """
    names = list(dict.fromkeys(entry["path"] for review in reviews.values() for entry in review["evidence"]))

    def owner(name: str) -> str:
        return next(ident for ident, review in reviews.items()
                    if any(entry["path"] == name for entry in review["evidence"]))

    links = _index_links(root, names)
    for name in names:
        link = _symlink(root, name, links)
        if link:
            raise Refused(f"{owner(name)}: evidence {name} is reached through the symlink {link}: "
                          "git holds the link, not the text hermes_status hashes, so no pin through it "
                          "can hold on another checkout; pin the file it points to instead")

    def listed(*flags: str) -> set[str]:   # (check-ignore would reject --literal-pathspecs)
        return set(git(root, "ls-files", "-z", *flags, "--", *names).stdout.decode("utf-8", "replace").split("\0"))

    tracked, ignored = listed("--cached"), listed("--others", "--ignored", "--exclude-standard")
    history = History(root)
    held: dict[str, str | None] = {}
    for name in names:
        if name not in tracked:
            raise Refused(f"{owner(name)}: evidence {name} is "
                          f"{'gitignored' if name in ignored else 'untracked'}: "
                          "no commit holds it, so every other checkout would read the row stale")
        blob = git(root, "rev-parse", "--verify", "--quiet", f"{base}:{name}",
                   ok=(0, 1, 128)).stdout.decode("utf-8", "replace").strip()
        data = history._cat([blob]).get(blob) if blob else None
        held[name] = blob_digest(data) if data is not None else None
    return list(dict.fromkeys(entry["path"] for review in reviews.values() for entry in review["evidence"]
                              if held[entry["path"]] != entry["sha256"]))


def _write_atomic(target: Path, payload: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def stamp(root: Path, patch: Any, *, base_sha: str | None = None, assessed_at: str | None = None,
          dry_run: bool = False, allow_uncommitted: bool = False) -> dict:
    """Insert or replace the patched reviews, or raise Refused and write nothing.

    Evidence is hashed from the working tree; unless `allow_uncommitted`, every pinned file
    must also be exactly what the recorded base_sha holds, so a clean checkout of that
    commit reads the rows as stamped. What was allowed anyway comes back as "uncommitted".
    """
    target = root / hs.ASSESSMENT
    raw = target.read_bytes()
    ledger, data = hs.load(root)
    if _serialize(data) != raw:
        raise Refused(f"{hs.ASSESSMENT} does not round-trip through json.dumps(ensure_ascii=False, "
                      "indent=2); rewriting it would change bytes outside the patched reviews")
    caps = ledger["capabilities"]
    reviews: dict[str, dict] = {}
    for item in _patch_items(patch):
        ident = item["id"]
        if not isinstance(ident, str) or not ROW.fullmatch(ident) or not 1 <= int(ident[1:]) <= len(caps):
            raise Refused(f"unknown row: {ident!r}")
        if ident in reviews:
            raise Refused(f"{ident} appears twice in the patch")
        reviews[ident] = {
            "id": ident, "row_sha256": hs.digest(caps[int(ident[1:]) - 1]), "status": item["status"],
            "summary": item["summary"], "remaining": item["remaining"],
            "evidence": [_pin(root, ident, name) for name in item["evidence"]],
        }
    try:
        kept = [review for review in data["reviews"] if review.get("id") not in reviews]
        frozen = _serialize([kept, data.get("scope_reopenings")])
        result = dict(data)   # same key order; untouched values stay the very same objects
        result["reviews"] = sorted([*kept, *reviews.values()], key=lambda review: review["id"])
    except (AttributeError, KeyError, TypeError) as exc:
        raise Refused(f"the recorded reviews are malformed: {exc}") from exc
    result["base_sha"] = base_sha if base_sha is not None else \
        git(root, "rev-parse", "--verify", "HEAD").stdout.decode().strip()
    result["assessed_at"] = assessed_at if assessed_at is not None else \
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = {row["id"]: row for row in hs.assess(ledger, result, root)}
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise Refused(f"hermes_status would refuse the result: {exc}") from exc
    for ident in reviews:
        if rows[ident]["basis"] != "reviewed":
            raise Refused(f"{ident} would come out {rows[ident]['basis']} (stale on arrival), "
                          "not reviewed")
    _generated(root, reviews, list(rows.values()), result)
    untouched = [review for review in result["reviews"] if review["id"] not in reviews]
    if _serialize([untouched, result.get("scope_reopenings")]) != frozen:
        raise Refused("the stamp would rewrite reviews it was not given, or scope_reopenings")
    uncommitted = _uncommitted(root, result["base_sha"], reviews)
    if uncommitted and not allow_uncommitted:
        raise Refused(f"base_sha {result['base_sha'][:12]} does not hold what these files hold now "
                      f"(uncommitted?): {', '.join(uncommitted)}; commit them first, or pass "
                      "--allow-uncommitted and commit them before anyone else reads the records")
    payload = _serialize(result)
    diff = list(difflib.unified_diff(raw.decode("utf-8").split("\n"), payload.decode("utf-8").split("\n"),
                                     f"{hs.ASSESSMENT} (now)", f"{hs.ASSESSMENT} (stamped)", lineterm="", n=1))
    if not dry_run:
        _write_atomic(target, payload)
    return {"stamped": list(reviews), "base_sha": result["base_sha"],
            "assessed_at": result["assessed_at"], "written": not dry_run, "diff": diff,
            "uncommitted": uncommitted}


# --- rendering and CLI -----------------------------------------------------------------------

def _short(sha: str) -> str:
    return sha[:12]


def _render_pin(pin: dict) -> list[str]:
    state = {"current": "holds (unchanged since it was pinned)", "drifted": "drifted",
             "absent": "absent from the working tree", "non-utf8": "not UTF-8 text now"}[pin["state"]]
    lines = [f"  {pin['path']}: {state}"]
    if pin["state"] == "current":
        return lines
    if pin["removed_in"]:
        where = "renamed to " + ", ".join(pin["moved_to"]) if pin["moved_to"] else "deleted"
        lines.append(f"    {where} in {_short(pin['removed_in'])}")
    lines.append(f"    pinned {_short(pin['pinned'])}  current {_short(pin['current'] or '-')}")
    if pin["found"] == "found":
        lines.append(f"    pin found: blob {', '.join(_short(b) for b in pin['blobs'])}, "
                     f"in {len(pin['commits']) + pin['more_commits']} commit(s)")
        for commit in pin["commits"]:
            flags = ["on HEAD" if commit["on_head"] else "NOT on HEAD"]
            if commit["predates_base"]:
                flags.append("older than the last restamp base")
            if commit["branches"]:
                flags.append("on " + ", ".join(commit["branches"]))
            lines.append(f"      {_short(commit['sha'])} {commit['date']} {commit['subject'][:72]} "
                         f"[{'; '.join(flags)}]")
        if pin["more_commits"]:
            lines.append(f"      ... and {pin['more_commits']} more")
    elif pin["found"] == "unrecoverable":
        lines.append(f"    pin UNRECOVERABLE: none of the {pin['searched']} blob(s) this path held on any "
                     "branch hashes to it (an uncommitted tree?): re-read the row in full, do not remap")
    elif pin["found"] == "shallow":
        lines.append(f"    pin not in the {pin['searched']} blob(s) searched, but this clone is shallow: "
                     "run `git fetch --unshallow` before trusting that")
    else:
        lines.append(f"    pin not in the {pin['searched']} blob(s) searched, but some blobs are missing "
                     "from this clone: fetch them before calling it unrecoverable")
    if pin["non_utf8"]:
        lines.append(f"    ({pin['non_utf8']} historical blob(s) are not UTF-8 and can match no pin)")
    return lines


def render_drift(report: list[dict]) -> str:
    out: list[str] = []
    for row in report:
        basis = f"{row['basis']}; " if row["basis"] else ""
        recorded = f"recorded {row['recorded']}" if row["recorded"] else "no review"
        out.append(f"{row['id']} {row['status'] or '?'} ({basis}{recorded}): {row['name']}")
        if row["assess_error"]:
            out.append(f"  hermes_status cannot assess the records: {row['assess_error']}")
        if row["recorded"] is None:
            out.append("  no review yet: nothing was pinned; this row needs a fresh assessment, not a remap")
        for pin in row["pins"]:
            out.extend(_render_pin(pin))
    return "\n".join(out)


def _span(pair: list[int]) -> str:
    return str(pair[0]) if pair[0] == pair[1] else f"{pair[0]}-{pair[1]}"


def _render_citation(item: dict) -> list[str]:
    head = f"    [{item['class']}] {item['citation']}"
    if item["suggest"] and item["suggest"] != item["citation"]:
        head += f" -> {item['suggest']}"
    if item["suggest"] and item["resolves"] is False:   # even when the numbers stay the same
        head += " (would NOT resolve)"
    if item["similarity"] is not None:
        head += f" (similarity {item['similarity']})"
    if item["class"] in ("unchanged", "moved") and item["anchored"] is False:
        head += " (neighbours differ: confirm by reading)"
    if item["class"] == "edited" and item["anchored"] is False:
        head += " (away from its anchors: confirm by reading)"
    if item["candidates"]:
        head += " candidates " + ", ".join(_span(c) for c in item["candidates"]) + ": not guessed"
    lines = [head]
    lines.extend(f"      pinned {item['first'] + k:>5} | {text}" for k, text in enumerate(item["pinned_text"][:6]))
    if item["class"] == "edited":   # unchanged and moved text is the pinned text, by definition
        lines.extend(f"      now    {item['now'][0] + k:>5} | {text}"
                     for k, text in enumerate(item["current_text"][:6]))
    return lines


def render_cite(report: dict) -> str:
    out = [f"{report['id']} (recorded {report['recorded']}): {report['name']}",
           f"  {len(report['citations'])} citation(s) resolve to pinned files; ignored, exactly as "
           f"hermes_status ignores them: {', '.join(report['ignored']) or 'none'}"]
    for path, view in report["files"].items():
        source = {"holds": "the pin holds", "found": f"pinned version from {_short(view['commit'])}"}.get(
            view["found"], f"pinned version {view['found']}")
        if view["now_path"] != path:
            source += f"; now at {view['now_path']}" if view["now_path"] else \
                f"; renamed to {', '.join(view['moved_to'])}: not guessed" if len(view["moved_to"]) > 1 else \
                "; gone from the working tree"
        out.extend(["", f"  {path}: {source}"])
        for item in report["citations"]:
            if item["path"] == path:
                out.extend(_render_citation(item))
        if view["hunks"]:
            out.append(f"    git diff {_short(view['commit'])} (working tree), hunks touching cited lines:")
            out.extend(f"      {line}" for hunk in view["hunks"] for line in hunk.split("\n"))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=None, help="repository root (default: this checkout)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    subs = parser.add_subparsers(dest="command", required=True)
    drift_cmd = subs.add_parser("drift", parents=[common], help="where the pinned bytes went (read-only)")
    drift_cmd.add_argument("ids", nargs="*", metavar="ID")
    drift_cmd.add_argument("--all-stale", action="store_true", help="every row hermes_status demoted")
    drift_cmd.add_argument("--json", action="store_true")
    cite_cmd = subs.add_parser("cite", parents=[common], help="where each citation sits now (read-only)")
    cite_cmd.add_argument("id", metavar="ID")
    cite_cmd.add_argument("--json", action="store_true")
    stamp_cmd = subs.add_parser("stamp", parents=[common], help="write re-read reviews (the only write)")
    stamp_cmd.add_argument("--patch", type=Path, required=True, help="JSON list of reviews")
    stamp_cmd.add_argument("--base-sha", help="default: git rev-parse HEAD")
    stamp_cmd.add_argument("--assessed-at", help="default: now, UTC, %%Y-%%m-%%dT%%H:%%M:%%SZ")
    stamp_cmd.add_argument("--dry-run", action="store_true", help="show the change, write nothing")
    stamp_cmd.add_argument("--allow-uncommitted", action="store_true",
                           help="pin evidence that base_sha does not hold (each file is listed as UNCOMMITTED)")
    ns = parser.parse_args(argv)
    if ns.command == "drift" and bool(ns.ids) == ns.all_stale:
        parser.error("drift takes row ids or --all-stale, not both and not neither")
    root = (ns.root or hs.REPO).resolve()
    try:
        if ns.command == "drift":
            report = drift(root, ns.ids, all_stale=ns.all_stale)
            print(json.dumps(report, ensure_ascii=False, indent=2) if ns.json else render_drift(report))
        elif ns.command == "cite":
            report = cite(root, ns.id)
            print(json.dumps(report, ensure_ascii=False, indent=2) if ns.json else render_cite(report))
        else:
            patch = json.loads(ns.patch.read_text(encoding="utf-8"))
            done = stamp(root, patch, base_sha=ns.base_sha, assessed_at=ns.assessed_at, dry_run=ns.dry_run,
                         allow_uncommitted=ns.allow_uncommitted)
            verb = "stamped" if done["written"] else "would stamp"
            print(f"{verb} {', '.join(done['stamped'])} in {hs.ASSESSMENT} "
                  f"(base_sha {done['base_sha']}, assessed_at {done['assessed_at']})")
            if done["uncommitted"]:
                print(f"WARNING: base_sha {done['base_sha']} does not hold these pinned bytes; every other "
                      "checkout reads their rows stale until they are committed:")
                print("\n".join(f"  UNCOMMITTED {name}" for name in done["uncommitted"]))
            if done["written"]:
                print("next: python3.12 scripts/hermes_status.py write && python3.12 scripts/hermes_status.py check")
            else:
                print("\n".join(done["diff"]))
        return 0
    except Refused as exc:
        print(f"refused, nothing written: {exc}", file=sys.stderr)
        return 1
    except UnknownRow as exc:
        print(str(exc).strip("'\""), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, GitError) as exc:
        print(f"hermes_restamp error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
