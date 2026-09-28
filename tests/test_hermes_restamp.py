"""A restamp must re-find the exact bytes a review hashed, map its citations honestly,
and refuse to write anything hermes_status would refuse — or would leave stale.

Every fixture is a throwaway git repository isolated from the machine's git config
(this sandbox signs commits globally), shaped like `sample` in
test_hermes_sprint_status.py but with real history behind it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import hermes_restamp as hr
from scripts import hermes_status as hs

CAPS = [
    {"name": "Inherited parity", "cluster": "core", "decision": "keep", "nerva_state": "parity"},
    {"name": "Command registry", "cluster": "core", "decision": "update", "nerva_state": "superior"},
    {"name": "Formerly excluded", "cluster": "ui", "decision": "skip", "nerva_state": "superior"},
    {"name": "Renamed module", "cluster": "ui", "decision": "copy", "nerva_state": "missing"},
    {"name": "Stable capability", "cluster": "core", "decision": "keep", "nerva_state": "parity"},
    {"name": "Also excluded", "cluster": "ui", "decision": "skip", "nerva_state": "parity"},
]
TAIL = [f"CONSTANT_{i} = {i}" for i in range(12)]
V1 = [
    '"""Example module the fixture review pinned."""', "",   # 1-2
    "def alpha():", '    return "alpha"', "", "",            # 3-6
    "def beta(value):", "    return compute(value)", "", "",  # 7-10
    "def gamma():", "    return None", "", "",               # 11-14
    "def doomed_helper():", '    return "doomed"', "", "",   # 15-18
    "def omega():", '    return "omega"', "", "",            # 19-22
    *TAIL,                                                   # 23-34
]
V2 = [
    '"""Example module the fixture review pinned."""', "",   # 1-2
    "import os", "", "",                                     # 3-5
    "def delta():", "    return None", "", "",               # 6-9
    "def epsilon():", "    return None", "", "",             # 10-13
    "def alpha():", '    return "alpha"', "", "",            # 14-17
    "def beta(value):", "    return compute(value, strict=True)", "", "",  # 18-21
    "def omega():", '    return "omega"', "", "",            # 22-25
    *TAIL,                                                   # 26-37
]
V3 = V2[:-1] + ["CONSTANT_11 = 110"]   # a change far from every citation
STUB = ['"""Stub module."""', "def stub():", "    raise NotImplementedError"]
GONE = ["def gone():", "    return 'gone'"]
FILES = {
    "agents/core/example.py": V1,
    "tests/test_example.py": ["def test_example():", "    assert True"],
    "agents/core/old_name.py": STUB,
    "agents/core/gone.py": GONE,
    "agents/core/stable.py": ['"""Stable capability."""', "def stable():", "    return True"],
    "agents/web/stable.py": ['"""Stable web surface."""', "def serve():", "    return 200"],
    "tests/test_stable.py": ["def test_stable():", "    assert True"],
}
H002_SUMMARY = (
    "The registry lives at example.py:3-4 and agents/core/example.py:8; the null path is "
    "agents/core/example.py:12 and the helper agents/core/example.py:15-16. The module doc is "
    "example.py:1, pinned by test_example.py:1; agents/core/elsewhere.py:9999 was never pinned."
)
H004_SUMMARY = "Only a stub exists at old_name.py:2; the helper gone.py:1 was dropped."
H005_SUMMARY = (
    "agents/core/stable.py:2 does the work and test_stable.py:1 covers it; stable.py:1 names two "
    "pinned files and agents/core/nowhere.py:5 was never pinned."
)
REASON = "Readmis în obiectivul de paritate completă — inclusiv fostele excluderi."
EXAMPLE = "agents/core/example.py"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def put(root: Path, name: str, content: list[str] | bytes) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else ("\n".join(content) + "\n").encode())
    return path


def digest_of(tmp_path: Path, content: list[str] | bytes) -> str:
    """The hash hermes_status would record for a file with this content."""
    return hs.file_digest(put(tmp_path / "scratch", "file.txt", content))


def save(root: Path, data: dict) -> None:
    put(root, hs.ASSESSMENT, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def repin(root: Path, ident: str, path: str, sha: str) -> None:
    data = hs.load(root)[1]
    review = next(item for item in data["reviews"] if item["id"] == ident)
    next(entry for entry in review["evidence"] if entry["path"] == path)["sha256"] = sha
    save(root, data)


def review(root: Path, ident: str, status: str, summary: str, remaining: str, paths: list[str]) -> dict:
    return {"id": ident, "row_sha256": hs.digest(CAPS[int(ident[1:]) - 1]), "status": status,
            "summary": summary, "remaining": remaining,
            "evidence": [{"path": p, "sha256": hs.file_digest(root / p)} for p in paths]}


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def isolated_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def repo(tmp_path, isolated_git):
    """v1 pinned by three reviews; v2 moves, edits and deletes; v3 edits far away."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false"), ("core.autocrlf", "false")):
        git(root, "config", key, value)
    ledger = {"generated": "2026-09-07", "capabilities": CAPS}
    put(root, hs.LEDGER, json.dumps(ledger, ensure_ascii=False, indent=2).splitlines())
    for name, lines in FILES.items():
        put(root, name, lines)
    reopen = [{"id": ident, "row_sha256": hs.digest(CAPS[int(ident[1:]) - 1]),
               "decided_at": "2026-09-27T00:00:00Z", "reason": REASON} for ident in ("H006", "H003")]
    data = {
        "schema_version": 2, "inventory_count": len(CAPS), "inventory_sha256": hs.digest(ledger),
        "base_sha": "a" * 40, "assessed_at": "2026-09-20T10:00:00Z",
        "reviews": [
            review(root, "H002", "partial", H002_SUMMARY, "Event delivery is still missing.",
                   [EXAMPLE, "tests/test_example.py"]),
            review(root, "H004", "missing", H004_SUMMARY, "The whole capability is still missing.",
                   ["agents/core/old_name.py", "agents/core/gone.py"]),
            review(root, "H005", "equivalent", H005_SUMMARY, "",
                   ["agents/core/stable.py", "agents/web/stable.py", "tests/test_stable.py"]),
        ],
        "scope_reopenings": reopen,   # deliberately not sorted: a stamp must not reorder it
    }
    save(root, data)
    assert [r["basis"] for r in hs.assess(ledger, data, root)] == [
        "baseline_2026-09-07", "reviewed", "scope_reopened", "reviewed", "reviewed", "scope_reopened"]
    c1 = commit(root, "v1: every review current")
    put(root, EXAMPLE, V2)
    git(root, "mv", "agents/core/old_name.py", "agents/core/new_name.py")
    git(root, "rm", "-q", "agents/core/gone.py")
    c2 = commit(root, "v2: move, edit, delete")
    put(root, EXAMPLE, V3)
    data["base_sha"] = c2   # the last restamp's base is newer than the v1 pins
    save(root, data)
    c3 = commit(root, "v3: an edit far from every citation")
    return SimpleNamespace(root=root, ledger=ledger, c1=c1, c2=c2, c3=c3, tmp=tmp_path)


def pins(report: dict) -> dict[str, dict]:
    return {pin["path"]: pin for pin in report["pins"]}


def cited(report: dict) -> dict[str, dict]:
    return {item["citation"]: item for item in report["citations"]}


# --- hashing: hermes_status's own rule, applied to git blobs ---------------------------------

@pytest.mark.parametrize("data", [
    b"", b"plain\n", b"a\r\nb\r\n", b"a\rb\r", b"mixed\r\nlone\rlf\n", b"\xef\xbb\xbfbom\r\n",
    b"x" * 8191 + b"\r\n" + b"y\r\n",   # a CRLF split across the reader's 8 KiB chunk
    "diacritice ț ș\r\n".encode(),
])
def test_blob_digest_is_exactly_hermes_status_file_digest(tmp_path, data):
    assert hr.blob_digest(data) == hs.file_digest(put(tmp_path, "blob.bin", data))


def test_line_endings_never_change_the_digest_but_bytes_do():
    lf, crlf, cr = b"one\ntwo\n", b"one\r\ntwo\r\n", b"one\rtwo\r"
    assert hr.blob_digest(lf) == hr.blob_digest(crlf) == hr.blob_digest(cr)
    assert hashlib.sha256(crlf).hexdigest() != hr.blob_digest(crlf)
    assert hr.blob_digest(b"\xff\xfe not utf-8\n") is None


# --- drift ---------------------------------------------------------------------------------

def test_drift_finds_a_pin_older_than_the_last_restamp_base(repo):
    [report] = hr.drift(repo.root, ["H002"])
    assert report["id"] == "H002" and report["status"] == "needs_review"
    example = pins(report)[EXAMPLE]
    assert example["state"] == "drifted" and example["found"] == "found"
    assert example["current"] == hs.file_digest(repo.root / EXAMPLE) != example["pinned"]
    assert [c["sha"] for c in example["commits"]] == [repo.c1]
    assert example["commits"][0]["on_head"] is True
    assert example["commits"][0]["predates_base"] is True
    held = pins(report)["tests/test_example.py"]
    assert held["state"] == "current" and held["found"] == "holds" and held["commits"] == []


def test_drift_finds_a_pin_that_only_exists_on_another_branch(repo):
    git(repo.root, "checkout", "-q", "-b", "side", repo.c1)
    side_text = V1[:7] + ["    return compute(value, side=True)"] + V1[8:]
    put(repo.root, EXAMPLE, side_text)
    side = commit(repo.root, "side-only version")
    git(repo.root, "checkout", "-q", "main")
    repin(repo.root, "H002", EXAMPLE, digest_of(repo.tmp, side_text))
    example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert example["found"] == "found"
    assert [c["sha"] for c in example["commits"]] == [side]
    assert example["commits"][0]["on_head"] is False
    assert "side" in example["commits"][0]["branches"]


def test_drift_reports_unrecoverable_only_after_searching_every_branch(repo):
    git(repo.root, "branch", "other", repo.c2)
    repin(repo.root, "H002", EXAMPLE, digest_of(repo.tmp, ["never", "committed"]))
    example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert example["found"] == "unrecoverable" and example["commits"] == []
    assert example["searched"] == 3   # the v1, v2 and v3 blobs, all hashed, none matched


def test_a_shallow_clone_never_claims_unrecoverable(repo, tmp_path):
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", repo.root.as_uri(), str(shallow)],
                   check=True, capture_output=True)
    example = pins(hr.drift(shallow, ["H002"])[0])[EXAMPLE]
    assert example["found"] == "shallow"


def test_crlf_lone_cr_and_non_utf8_blobs_are_hashed_like_the_working_tree(repo):
    crlf, lone_cr = b"crlf version\r\nline two\r\n", b"lone cr version\rline two\r"
    put(repo.root, EXAMPLE, crlf)
    c4 = commit(repo.root, "CRLF blob")
    put(repo.root, EXAMPLE, lone_cr)
    c5 = commit(repo.root, "lone-CR blob")
    put(repo.root, EXAMPLE, b"\xff\xfe not utf-8\n")
    commit(repo.root, "non-UTF-8 blob")
    stale = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert stale["state"] == "non-utf8"          # the working tree itself cannot be hashed
    put(repo.root, EXAMPLE, V3)
    commit(repo.root, "restore")
    for raw, text, where in ((crlf, ["crlf version", "line two"], c4),
                             (lone_cr, ["lone cr version", "line two"], c5)):
        pin = digest_of(repo.tmp, text)
        assert hashlib.sha256(raw).hexdigest() != pin   # a raw sha256 would never find it
        repin(repo.root, "H002", EXAMPLE, pin)
        example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
        assert [c["sha"] for c in example["commits"]] == [where]
        assert example["non_utf8"] == 1


def test_drift_finds_a_pin_that_only_a_merge_result_held(repo):
    # Each side changes a different end of the file; the clean merge holds a blob neither
    # parent ever had, and only a per-parent diff of the merge commit shows it.
    git(repo.root, "checkout", "-q", "-b", "side")
    put(repo.root, EXAMPLE, ["# side header", *V3])
    commit(repo.root, "side: a header")
    git(repo.root, "checkout", "-q", "main")
    put(repo.root, EXAMPLE, [*V3, "MAIN = 1"])
    commit(repo.root, "main: a trailer")
    git(repo.root, "merge", "-q", "--no-edit", "side")
    merge = git(repo.root, "rev-parse", "HEAD")
    merged = ["# side header", *V3, "MAIN = 1"]
    assert (repo.root / EXAMPLE).read_text(encoding="utf-8") == "\n".join(merged) + "\n"
    put(repo.root, EXAMPLE, V3)
    commit(repo.root, "after the merge")
    repin(repo.root, "H002", EXAMPLE, digest_of(repo.tmp, merged))
    example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert example["found"] == "found" and [c["sha"] for c in example["commits"]] == [merge]


def test_drift_finds_a_pin_on_a_side_branch_that_a_merge_discarded(repo):
    # `merge -s ours` keeps main's file, so the merge is TREESAME to its first parent and
    # default history simplification never walks the (deleted) side branch behind it.
    # Mutation note (N01, dropping --full-history): equivalent. --diff-merges=separate
    # already switches history simplification off (git 2.43: this history, a side edit
    # later reverted, and two sides reaching the same file all read the same without it);
    # the flag stays because the spec names it and it costs nothing.
    git(repo.root, "checkout", "-q", "-b", "side")
    side_text = [*V3, "SIDE = 1"]
    put(repo.root, EXAMPLE, side_text)
    side = commit(repo.root, "side: an edit the merge discards")
    git(repo.root, "checkout", "-q", "main")
    git(repo.root, "merge", "-q", "-s", "ours", "--no-edit", "side")
    git(repo.root, "branch", "-q", "-D", "side")
    repin(repo.root, "H002", EXAMPLE, digest_of(repo.tmp, side_text))
    example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert example["found"] == "found" and [c["sha"] for c in example["commits"]] == [side]
    assert example["commits"][0]["on_head"] is True   # reachable through the merge's second parent


def test_drift_finds_a_pin_held_only_by_a_remote_tracking_ref(repo):
    git(repo.root, "checkout", "-q", "-b", "side", repo.c1)
    side_text = V1[:7] + ["    return compute(value, remote=True)"] + V1[8:]
    put(repo.root, EXAMPLE, side_text)
    side = commit(repo.root, "a version only origin has")
    git(repo.root, "checkout", "-q", "main")
    git(repo.root, "update-ref", "refs/remotes/origin/side", side)
    git(repo.root, "branch", "-q", "-D", "side")
    repin(repo.root, "H002", EXAMPLE, digest_of(repo.tmp, side_text))
    example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert example["found"] == "found" and [c["sha"] for c in example["commits"]] == [side]
    assert example["commits"][0]["on_head"] is False
    assert example["commits"][0]["branches"] == ["origin/side"]


def test_drift_follows_renames_and_deletes(repo):
    report = pins(hr.drift(repo.root, ["H004"])[0])
    renamed, gone = report["agents/core/old_name.py"], report["agents/core/gone.py"]
    assert renamed["state"] == "absent" and renamed["moved_to"] == ["agents/core/new_name.py"]
    assert renamed["removed_in"] == repo.c2
    assert [c["sha"] for c in renamed["commits"]] == [repo.c1]
    assert gone["state"] == "absent" and gone["moved_to"] == [] and gone["removed_in"] == repo.c2
    assert gone["found"] == "found"


def test_drift_all_stale_names_exactly_the_rows_hermes_status_demoted(repo, capsys):
    ledger, data = hs.load(repo.root)
    stale = [r["id"] for r in hs.assess(ledger, data, repo.root) if r["basis"] == "stale_evidence"]
    assert stale == ["H002", "H004"]
    assert hr.main(["--root", str(repo.root), "drift", "--all-stale", "--json"]) == 0
    assert [row["id"] for row in json.loads(capsys.readouterr().out)] == stale
    assert hr.main(["--root", str(repo.root), "drift", "--all-stale"]) == 0
    out = capsys.readouterr().out
    assert "H002" in out and "H004" in out and "H005" not in out
    assert repo.c1[:12] in out and "renamed to agents/core/new_name.py" in out


def test_drift_explains_a_reopened_row_and_refuses_an_unknown_one(repo, capsys):
    assert hr.main(["--root", str(repo.root), "drift", "H003"]) == 0
    assert "no review" in capsys.readouterr().out
    for command in ("drift", "cite"):
        for ident in ("H999", "H000", f"H{len(CAPS) + 1:03}", "H2"):   # H000 would name the last row
            assert hr.main(["--root", str(repo.root), command, ident]) == 1, (command, ident)
            assert "unknown row" in capsys.readouterr().err


def test_the_commits_that_hold_a_pin_are_listed_newest_first(repo, monkeypatch):
    # v1 came back later (a revert), so two commits introduced the pinned blob. The list is cut
    # at SHOWN, so the newest must come first; commit dates decide it, not the order git gave.
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2030-01-01T00:00:00Z")
    put(repo.root, EXAMPLE, V1)
    back = commit(repo.root, "bring v1 back")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2030-01-02T00:00:00Z")
    put(repo.root, EXAMPLE, V3)
    commit(repo.root, "and v3 again")
    example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert [c["sha"] for c in example["commits"]] == [back, repo.c1]
    assert [c["date"] for c in example["commits"]][0] == "2030-01-01"


def test_a_clone_missing_blobs_never_claims_unrecoverable(repo, capsys):
    # The v2 blob is gone from the object store (a partial or damaged clone): the pin might be
    # that very blob, so it is "incomplete", with a hint to fetch, never "unrecoverable".
    blob = git(repo.root, "rev-parse", f"{repo.c2}:{EXAMPLE}")
    loose = repo.root / ".git" / "objects" / blob[:2] / blob[2:]   # the fixture never packs
    loose.chmod(0o644)
    loose.unlink()
    repin(repo.root, "H002", EXAMPLE, digest_of(repo.tmp, ["never", "committed"]))
    example = pins(hr.drift(repo.root, ["H002"])[0])[EXAMPLE]
    assert (example["found"], example["searched"], example["commits"]) == ("incomplete", 3, [])
    assert hr.main(["--root", str(repo.root), "drift", "H002"]) == 0
    assert "some blobs are missing from this clone" in capsys.readouterr().out


def test_a_git_failure_exits_2_and_never_a_traceback(repo, monkeypatch, capsys):
    monkeypatch.setenv("GIT_DIR", str(repo.tmp / "no-such-git-dir"))   # every git command now fails
    for command in ("drift", "cite"):
        assert hr.main(["--root", str(repo.root), command, "H002"]) == 2
        assert capsys.readouterr().err.startswith("hermes_restamp error: git ")


# --- cite ----------------------------------------------------------------------------------

def test_cite_classifies_unchanged_moved_edited_deleted_and_ambiguous_lines(repo):
    report = cited(hr.cite(repo.root, "H002"))
    assert report["example.py:1"]["class"] == "unchanged" and report["example.py:1"]["now"] == [1, 1]
    moved = report["example.py:3-4"]
    # Only the neighbour below agrees (v2 put epsilon() above alpha): placed, but flagged.
    assert moved["class"] == "moved" and moved["now"] == [14, 15] and moved["anchored"] is False
    assert moved["suggest"] == "example.py:14-15" and moved["resolves"] is True
    edited = report["agents/core/example.py:8"]
    assert edited["class"] == "edited" and edited["now"] == [19, 19]
    assert edited["pinned_text"] == ["    return compute(value)"]
    assert edited["current_text"] == ["    return compute(value, strict=True)"]
    ambiguous = report["agents/core/example.py:12"]
    assert ambiguous["class"] == "ambiguous" and ambiguous["now"] is None
    assert ambiguous["candidates"] == [[7, 7], [11, 11]] and ambiguous["suggest"] is None
    deleted = report["agents/core/example.py:15-16"]
    assert deleted["class"] == "deleted" and deleted["now"] is None
    assert report["test_example.py:1"]["class"] == "unchanged"


def test_cite_prints_only_the_diff_hunks_that_touch_cited_lines(repo, capsys):
    report = hr.cite(repo.root, "H002")
    example = report["files"][EXAMPLE]
    assert example["commit"] == repo.c1
    hunks = "\n".join(example["hunks"])
    assert "-    return compute(value)" in hunks and "+    return compute(value, strict=True)" in hunks
    assert "CONSTANT_11" not in hunks          # that hunk touches no cited line
    assert report["files"]["tests/test_example.py"]["hunks"] == []   # the pin holds: nothing to diff
    assert hr.main(["--root", str(repo.root), "cite", "H002"]) == 0
    out = capsys.readouterr().out
    for label in ("[unchanged]", "[moved]", "[edited]", "[deleted]", "[ambiguous]", "@@ -"):
        assert label in out
    assert "agents/core/elsewhere.py:9999" in out   # listed as ignored, never classified
    assert "example.py:3-4 -> example.py:14-15 (neighbours differ: confirm by reading)" in out


@pytest.mark.parametrize("lines,shown", [("30", False), ("31", True), ("25-30", False), ("25-31", True)])
def test_a_hunk_is_shown_exactly_when_it_reaches_a_cited_line(repo, lines, shown):
    # v3 changed only pinned line 34, so git's hunk (3 lines of context) covers 31-34; a
    # range reaches it by its last line alone.
    data = hs.load(repo.root)[1]
    next(r for r in data["reviews"] if r["id"] == "H002")["summary"] = (
        f"Only the constants at agents/core/example.py:{lines} are cited.")
    save(repo.root, data)
    hunks = hr.cite(repo.root, "H002")["files"][EXAMPLE]["hunks"]
    assert ("+CONSTANT_11 = 110" in "\n".join(hunks)) is shown


def test_a_citation_that_never_resolved_in_a_drifted_file_is_reported_invalid(repo, capsys):
    # Past the pinned file's end, or on a blank line of it: hermes_status rejects both.
    data = hs.load(repo.root)[1]
    next(r for r in data["reviews"] if r["id"] == "H002")["summary"] = (
        "Beyond the pinned end: agents/core/example.py:999; blank: agents/core/example.py:2.")
    save(repo.root, data)
    report = hr.cite(repo.root, "H002")
    assert {c["citation"]: (c["class"], c["now"]) for c in report["citations"]} == {
        "agents/core/example.py:999": ("invalid", None), "agents/core/example.py:2": ("invalid", None)}
    assert hr.main(["--root", str(repo.root), "cite", "H002"]) == 0
    assert "[invalid] agents/core/example.py:999" in capsys.readouterr().out


def test_a_crlf_working_tree_shows_only_the_hunks_that_changed(repo):
    # hermes_status reads CRLF as LF, so the diff must too, or every line is a change.
    put(repo.root, EXAMPLE, ("\r\n".join(V3) + "\r\n").encode())
    report = hr.cite(repo.root, "H002")
    assert cited(report)["agents/core/example.py:8"]["class"] == "edited"
    hunks = "\n".join(report["files"][EXAMPLE]["hunks"])
    assert "-    return compute(value)" in hunks and "+    return compute(value, strict=True)" in hunks
    assert "CONSTANT_11" not in hunks


def test_hunks_are_matched_on_git_line_numbers_past_unicode_line_separators(repo):
    # str.splitlines (hermes_status's numbering) also breaks at U+2028; git breaks at \n only.
    sep, name = " ", "agents/core/unicode.py"
    v1 = [f"S{i} = 'a{sep}b'" for i in range(1, 6)] + [f"L{i} = {i}" for i in range(6, 31)]
    v1[17] = f"L18 = 'x{sep}y'"   # a separator inside the cited hunk's context, too
    put(repo.root, name, v1)
    commit(repo.root, "a file with line separators inside its lines")
    git_line = v1.index("L20 = 20") + 1
    hs_line = "\n".join(v1).splitlines().index("L20 = 20") + 1
    assert (git_line, hs_line) == (20, 26)
    data = hs.load(repo.root)[1]
    item = next(r for r in data["reviews"] if r["id"] == "H002")
    item["summary"] = f"The value lives at unicode.py:{hs_line}."
    item["evidence"] = [{"path": name, "sha256": hs.file_digest(repo.root / name)}]
    save(repo.root, data)
    v2 = [{"L20 = 20": "L20 = 200", "L28 = 28": "L28 = 280"}.get(line, line) for line in v1]
    put(repo.root, name, v2)   # two separate hunks: the cited one at git line 20, another at 28
    report = hr.cite(repo.root, "H002")
    assert cited(report)[f"unicode.py:{hs_line}"]["pinned_text"] == ["L20 = 20"]
    [hunk] = report["files"][name]["hunks"]
    lines = hunk.split("\n")
    assert lines[0].startswith("@@ -17,7 +17,7 @@")
    assert lines[1:] == [" L17 = 17", f" L18 = 'x{sep}y'", " L19 = 19", "-L20 = 20", "+L20 = 200",
                         " L21 = 21", " L22 = 22", " L23 = 23"]


@pytest.mark.parametrize("start,count,shown", [
    (2, 3, False), (3, 3, True), (10, 3, True), (11, 3, False),   # a cited range of 5-10
    (4, 0, False), (5, 0, True), (9, 0, True), (10, 0, False),    # lines inserted after `start`
])
def test_hunk_overlap_boundaries(start, count, shown):
    assert hr._overlaps(start, count, 5, 10) is shown


def test_cite_follows_a_renamed_file_and_reports_a_deleted_one(repo):
    full = hr.cite(repo.root, "H004")
    report = cited(full)
    renamed = report["old_name.py:2"]
    assert renamed["class"] == "moved" and renamed["now_path"] == "agents/core/new_name.py"
    assert renamed["now"] == [2, 2] and renamed["suggest"] == "agents/core/new_name.py:2"
    assert report["gone.py:1"]["class"] == "deleted"
    # A pure rename changes no line: the diff follows it to its new path, so there is no hunk.
    assert full["files"]["agents/core/old_name.py"]["hunks"] == []
    put(repo.root, "agents/core/new_name.py", ['"""Stub module, edited."""', *STUB[1:]])
    commit(repo.root, "edit the renamed file's first line")
    [hunk] = hr.cite(repo.root, "H004")["files"]["agents/core/old_name.py"]["hunks"]
    assert hunk.split("\n") == ["@@ -1,3 +1,3 @@", '-"""Stub module."""', '+"""Stub module, edited."""',
                                " def stub():", "     raise NotImplementedError"]


def test_a_file_renamed_to_several_places_is_not_guessed(repo, monkeypatch, capsys):
    # git records one rename per deleted path, but should the trail ever fork, no branch of it
    # is picked: every citation of the file is ambiguous, and its header names both places.
    put(repo.root, "agents/core/other_name.py", STUB)
    commit(repo.root, "a second copy of the stub")
    old, places = "agents/core/old_name.py", ["agents/core/new_name.py", "agents/core/other_name.py"]
    whereabouts = hr.History.whereabouts

    def forked(self, path, hops=5):
        return (repo.c2, places) if path == old else whereabouts(self, path, hops)

    monkeypatch.setattr(hr.History, "whereabouts", forked)
    report = hr.cite(repo.root, "H004")
    placed = cited(report)["old_name.py:2"]
    assert (placed["class"], placed["now_path"], placed["suggest"]) == ("ambiguous", None, None)
    assert report["files"][old]["moved_to"] == places and report["files"][old]["hunks"] == []
    assert hr.main(["--root", str(repo.root), "cite", "H004"]) == 0
    assert f"renamed to {', '.join(places)}: not guessed" in capsys.readouterr().out


def test_a_file_renamed_twice_is_followed_to_where_it_lives_now(repo):
    git(repo.root, "mv", "agents/core/new_name.py", "agents/core/newest_name.py")
    commit(repo.root, "rename it again")
    renamed = pins(hr.drift(repo.root, ["H004"])[0])["agents/core/old_name.py"]
    assert renamed["moved_to"] == ["agents/core/newest_name.py"] and renamed["removed_in"] == repo.c2
    placed = cited(hr.cite(repo.root, "H004"))["old_name.py:2"]
    assert placed["class"] == "moved" and placed["now_path"] == "agents/core/newest_name.py"
    assert placed["suggest"] == "agents/core/newest_name.py:2"


def test_unpinned_and_ambiguous_names_are_ignored_exactly_as_hermes_status_ignores_them(repo):
    item = next(r for r in hs.load(repo.root)[1]["reviews"] if r["id"] == "H005")
    text = f"{item['summary']}\n{item['remaining']}"
    # With empty stand-ins every citation hs resolves "misses", and every one it ignores does not.
    screened = hs._cited_lines(text, {entry["path"]: [] for entry in item["evidence"]})
    report = hr.cite(repo.root, "H005")
    assert [c["citation"] for c in report["citations"]] == screened
    assert screened == ["agents/core/stable.py:2", "test_stable.py:1"]
    assert report["ignored"] == ["stable.py:1", "agents/core/nowhere.py:5"]
    assert all(c["class"] == "unchanged" for c in report["citations"])


def test_a_repeated_line_is_placed_only_when_both_neighbours_agree():
    pinned = ["def gamma():", "    return None", "", "def omega():"]
    current = ["def delta():", "    return None", "", "def x():", "    pass", "",
               "def gamma():", "    return None", "", "def omega():"]
    placed = hr.classify(pinned, 2, 2, current)
    assert placed["class"] == "moved" and placed["now"] == [8, 8] and placed["anchored"] is True
    for spot, text in ((6, "def renamed_gamma():"), (9, "def renamed_omega():")):
        one_side = [text if i == spot else line for i, line in enumerate(current)]
        guessed = hr.classify(pinned, 2, 2, one_side)   # one agreeing neighbour is not enough
        assert guessed["class"] == "ambiguous" and guessed["candidates"] == [[2, 2], [8, 8]]


@pytest.mark.parametrize("current,expected", [
    (["def a():", "    one()", "    two()", "def b():"], ("unchanged", [2, 3])),
    (["import os", "", "def a():", "    one()", "    two()", "def b():"], ("moved", [4, 5])),
    (["def a():", "    one(changed=True)", "    two()", "def b():"], ("edited", [2, 3])),
    (["def a():", "    pass", "def b():"], ("deleted", None)),
])
def test_classify_reports_exact_one_based_lines(current, expected):
    pinned = ["def a():", "    one()", "    two()", "def b():"]
    result = hr.classify(pinned, 2, 3, current)
    assert (result["class"], result["now"]) == expected


def test_a_long_block_is_compared_line_by_line():
    body = ["    x = 1", "    y = 2", "    z = 3", "    w = 4", "    return x + y + z + w"]
    pinned = ["def a():", *body, "def b():"]
    current = ["import os", "", "def a():", body[0], "    y = 20", *body[2:], "def b():"]
    result = hr.classify(pinned, 2, 6, current)
    assert (result["class"], result["now"], result["similarity"]) == ("edited", [4, 8], 0.8)
    reindented = ["def a():", "    if True:", *("    " + line for line in body), "def b():"]
    result = hr.classify(pinned, 2, 6, reindented)   # indentation alone is not an edit
    assert (result["class"], result["now"], result["similarity"]) == ("edited", [3, 7], 1.0)


def test_a_block_rewritten_in_place_is_ambiguous_not_deleted():
    body = [f"    {name} = {value}" for name, value in zip("abcdef", range(1, 7), strict=True)]
    pinned = ["def f():", *body, "def g():"]
    current = ["def f():", "    try:", "        a = 10", "        log()", "        b = 2", "        check()",
               "        c = 30", "        audit()", "        d = 4", "        more()", "        e = 50",
               "        f = 60", "    finally:", "        close()", "def g():"]
    result = hr.classify(pinned, 2, 7, current)
    assert result["class"] == "ambiguous" and result["candidates"] == [[2, 14]] and result["now"] is None
    gone = ["def f():", "    pass", "def g():"]
    assert hr.classify(pinned, 2, 7, gone)["class"] == "deleted"
    # Rewritten in place and also copied, lightly edited, past a long unchanged tail that
    # keeps the anchors where they were: both places are answers.
    head, tail = [f"HEADER_{i} = {i}" for i in range(5)], [f"TRAILER_{i} = {i}" for i in range(5)]
    copy = ["def f_old():", *("    c = 300" if line == "    c = 3" else line for line in body)]
    result = hr.classify([*head, *pinned, *tail], 7, 12, [*head, *current, *tail, *copy])
    assert result["class"] == "ambiguous" and result["candidates"] == [[7, 19], [27, 32]]


def test_every_copy_of_a_rewritten_block_that_scores_within_tie_is_a_candidate():
    head, tail = [f"HEADER_{i} = {i}" for i in range(5)], [f"TRAILER_{i} = {i}" for i in range(5)]
    pinned = [*head, "def f():", "    a = 1", "    b = 2", "    c = 3", "def g():", *tail]
    rewritten = ["def f():", "    with lock:", "        prepare_everything_first()", "        b = 2",
                 "        finalize_the_whole_thing()", "def g():"]
    copies = ["def f_old():", "    a = 1", "    b = 2", "    c = 30", "",
              "def f_older():", "    a = 1", "    b = 2", "    c = 3000"]   # 0.98 and 0.95: a tie
    result = hr.classify(pinned, 7, 9, [*head, *rewritten, *tail, *copies])
    assert result["class"] == "ambiguous" and result["now"] is None
    assert result["candidates"] == [[7, 10], [18, 20], [23, 25]]


def test_an_unchanged_file_places_every_citation_where_it_was():
    # The pin holds: repeated lines with identical neighbours are no reason to doubt it.
    same = ["def test_x(client):", "    r = client.get('/a')", "    assert r.ok", "    r = client.get('/a')",
            "    assert r.ok", "    r = client.get('/a')", "    assert r.ok"]
    result = hr.classify(same, 3, 3, list(same))
    assert (result["class"], result["now"], result["candidates"]) == ("unchanged", [3, 3], [])
    assert result["anchored"] is True   # every neighbour is where it was


@pytest.mark.parametrize("scored,chosen", [
    ([(0.8, 4, 3), (0.8, 5, 2)], [(0.8, 5, 2)]),   # an exact tie: the window of the cited length
    ([(0.8, 4, 2), (0.8, 3, 2)], [(0.8, 3, 2)]),   # then the earlier window
    ([(0.8, 3, 2), (0.9, 4, 2), (0.7, 6, 2)], [(0.9, 4, 2), (0.7, 6, 2)]),   # best first, overlaps dropped
])
def test_spots_break_exact_ties_by_the_cited_length_then_the_earlier_window(scored, chosen):
    assert hr._spots(scored, 2) == chosen


MOVED_V1 = ["def a():", "    return 1", "", "def b(value):", "    total = compute(value, mode='fast')",
            "    return total", "", "def c():", "    x = 1", "    y = 2", "    return x + y", ""]
MOVED_V2 = ["def a():", "    return 1", "", "def c():", "    x = 1", "    y = 2", "    return x + y", "",
            "def b(value):", "    total = compute(value, mode='safe')", "    return total", ""]


@pytest.mark.parametrize("first,last,now", [(5, 5, [10, 10]), (4, 6, [9, 11])])
def test_a_block_moved_and_edited_is_found_away_from_its_anchors_not_deleted(first, last, now):
    # b() moved below c() and one argument changed: nothing resembles it between its old
    # anchors, but most of it is still in the file, verbatim.
    result = hr.classify(MOVED_V1, first, last, MOVED_V2)
    assert (result["class"], result["now"], result["anchored"]) == ("edited", now, False)
    twice = [*MOVED_V2, "def b(value):", "    total = compute(value, mode='safe')", "    return total"]
    result = hr.classify(MOVED_V1, first, last, twice)   # two equally good places: not guessed
    assert result["class"] == "ambiguous" and result["now"] is None
    assert result["candidates"] == [now, [now[0] + 4, now[1] + 4]]
    item = {**result, "citation": f"m.py:{first}", "suggest": None, "resolves": None, "first": first,
            "pinned_text": MOVED_V1[first - 1:last], "current_text": []}
    assert "not guessed" in hr._render_citation(item)[0]


def test_away_from_its_anchors_only_a_vouched_place_counts():
    # doomed_helper() was deleted; alpha() and epsilon() have its shape, and "return None"
    # still flanks epsilon, but one unchanged line is not enough to call a place its new home.
    assert hr.classify(V1, 15, 16, V3)["class"] == "deleted"
    # A closer look-alike that nothing vouches for (a stray copy with a trailing space, first
    # in the file) neither wins nor hides the place that its neighbours vouch for.
    stray = ["    total = compute(value, mode='fast') ", "", *MOVED_V2]
    result = hr.classify(MOVED_V1, 5, 5, stray)
    assert (result["class"], result["now"], result["anchored"]) == ("edited", [12, 12], False)


def test_an_edit_found_away_from_its_anchors_is_flagged():
    result = hr.classify(MOVED_V1, 5, 5, MOVED_V2)
    item = {**result, "citation": "m.py:5", "suggest": "m.py:10", "resolves": True, "first": 5,
            "pinned_text": [MOVED_V1[4]], "current_text": [MOVED_V2[9]]}
    assert "(away from its anchors: confirm by reading)" in hr._render_citation(item)[0]


def test_a_unique_copy_is_not_placed_over_an_edit_where_the_line_was():
    # gamma()'s line was edited in place; a new delta() happens to hold the old text.
    pinned = ["def gamma():", "    return None", "", "def omega():", "    return 'omega'"]
    current = ["def gamma():", "    return 0", "", "def delta():", "    return None", "", "def omega():",
               "    return 'omega'"]
    result = hr.classify(pinned, 2, 2, current)
    assert result["class"] == "ambiguous" and result["candidates"] == [[2, 2], [5, 5]]
    assert result["now"] is None
    # The same copy with no rival where the line was is placed, flagged: one neighbour differs.
    moved = ["def omega():", "    return 'omega'", "", "def gamma():", "    return None"]
    result = hr.classify(pinned, 2, 2, moved)
    assert (result["class"], result["now"], result["anchored"]) == ("moved", [5, 5], False)
    # Both neighbours agreeing is what anchors a copy.
    both = ["import os", "", "def gamma():", "    return None", "", "def omega():", "    return 'omega'"]
    result = hr.classify(pinned, 2, 2, both)
    assert (result["class"], result["now"], result["anchored"]) == ("moved", [4, 4], True)


@pytest.mark.parametrize("pinned,first,last,current", [
    (["def f():", "    x = 1", "    return x"], 2, 2,
     ["def f():", "    x = 1", "    y = 2", "    return x"]),
    (["import os", "import sys", "", "def f():"], 2, 2,
     ["import os", "import sys", "import json", "", "def f():"]),
    (["ROUTES = {", '    "/a": a,', "}"], 2, 2,
     ["ROUTES = {", '    "/a": a,', '    "/b": b,', "}"]),
    (["def test_x(r):", "    assert r.status == 200", "", "def test_y():"], 2, 2,
     ["def test_x(r):", "    assert r.status == 200", '    assert r.body == "ok"', "", "def test_y():"]),
    (["def f():", "    a = load(1)", "    b = load(2)", "    return a + b"], 2, 3,
     ["def f():", "    a = load(1)", "    b = load(2)", "    c = load(3)", "    return a + b"]),
    # Both neighbours edited around it, or one edited and a look-alike added below it.
    (["CONFIG = {", '    "alpha": 1,', '    "beta": 2,', '    "gamma": 3,', "}"], 3, 3,
     ["CONFIG = {", '    "alpha": 10,', '    "beta": 2,', '    "gamma": 30,', "}"]),
    (["def f():", "    x = 1", "    y = 2", "def g():"], 3, 3,
     ["def f():", "    x = 10", "    y = 2", "    z = 3", "def g():"]),
], ids=["assignment", "import", "dict entry", "assert", "two lines", "dict, both edited", "edited and added"])
def test_lines_still_at_their_numbers_stay_unchanged_whatever_was_added_beside_them(pinned, first, last, current):
    # The cited text still sits at the cited numbers, so nothing needs remapping: a look-alike
    # beside it is no rival for "where the lines were". A neighbour changed, though, so the
    # place is not anchored, and cite says so.
    assert current[first - 1:last] == pinned[first - 1:last]
    result = hr.classify(pinned, first, last, current)
    assert (result["class"], result["now"], result["candidates"]) == ("unchanged", [first, last], [])
    assert result["anchored"] is False


def test_a_line_at_its_numbers_whose_neighbours_differ_is_flagged():
    # a() was deleted and b() moved up: line 2 holds the very text, but it is b()'s line now.
    # No edit sits where a()'s line was, so nothing competes and it stays unchanged, flagged.
    pinned = ["def a():", "    return None", "", "def b():", "    return None"]
    current = ["def b():", "    return None"]
    result = hr.classify(pinned, 2, 2, current)
    assert (result["class"], result["now"], result["anchored"]) == ("unchanged", [2, 2], False)
    item = {**result, "citation": "m.py:2", "suggest": "m.py:2", "resolves": True, "first": 2,
            "pinned_text": [pinned[1]], "current_text": [current[1]]}
    assert hr._render_citation(item)[0] == "    [unchanged] m.py:2 (neighbours differ: confirm by reading)"
    kept = hr.classify(pinned, 2, 2, [*pinned, "", "def c():"])   # both neighbours kept: no flag
    assert (kept["class"], kept["now"], kept["anchored"]) == ("unchanged", [2, 2], True)
    assert hr._render_citation({**item, **kept})[0] == "    [unchanged] m.py:2"


MIRROR_V1 = ["def test_a():", "    assert run() == 1", "", "def test_b():", "    assert run() == 2"]
MIRROR_V2 = ["def test_new():", "    assert run() == 1", "", "def test_a():", "    assert run() == 10", "",
             "def test_b():", "    assert run() == 2"]


@pytest.mark.parametrize("pinned,current,rival", [
    (MIRROR_V1, MIRROR_V2, [5, 5]),
    (["def gamma():", "    return None", "", "def omega():", "    return 'omega'"],
     ["def delta():", "    return None", "", "def gamma():", "    return 0", "", "def omega():", "    return 'omega'"],
     [5, 5]),
    (["export function load(ok) {", "  if (!ok) return null;", "  return fetchOne();", "}"],
     ["export function loadAll(ok) {", "  if (!ok) return null;", "  return fetchAll();", "}",
      "export function load(ok) {", "  if (!ok) return undefined;", "  return fetchOne();", "}"], [6, 6]),
], ids=["test copied above itself, original edited", "delta() above gamma(), gamma() edited", "TypeScript guard"])
def test_an_edit_both_neighbours_still_flank_is_a_rival_for_a_copy_at_the_cited_numbers(pinned, current, rival):
    # A function copied above itself, then the original (now lower) edited: the cited text is
    # still at the cited numbers, but it belongs to the copy, while the line the citation meant
    # is the edit that both of its pinned neighbours still flank. git's own diff reads it the
    # same misleading way (the copy as unchanged context), so it is never guessed.
    assert current[1] == pinned[1]
    result = hr.classify(pinned, 2, 2, current)
    assert (result["class"], result["now"], result["candidates"]) == ("ambiguous", None, [[2, 2], rival])


def test_a_copy_at_the_cited_numbers_is_ambiguous_end_to_end(repo, capsys):
    name = "tests/test_mirror.py"
    put(repo.root, name, MIRROR_V1)
    commit(repo.root, "mirror v1")
    data = hs.load(repo.root)[1]
    item = next(r for r in data["reviews"] if r["id"] == "H002")
    item["summary"] = "test_a pins the result at tests/test_mirror.py:2."
    item["evidence"] = [{"path": name, "sha256": hs.file_digest(repo.root / name)}]
    save(repo.root, data)
    put(repo.root, name, MIRROR_V2)
    commit(repo.root, "copy test_a above itself as test_new, then edit test_a")
    [placed] = hr.cite(repo.root, "H002")["citations"]
    assert (placed["class"], placed["suggest"], placed["candidates"]) == ("ambiguous", None, [[2, 2], [5, 5]])
    assert hr.main(["--root", str(repo.root), "cite", "H002"]) == 0
    assert "[ambiguous] tests/test_mirror.py:2 candidates 2, 5: not guessed" in capsys.readouterr().out


@pytest.mark.parametrize("current,rival", [
    (["def delta():", "    return None", "def gamma():", "    return 0", "", "def omega():", "    pass"], [4, 4]),
    (["def delta():", "    return None", "", "def gamma():", "    return 0", "    log()", "    audit()", "",
      "def omega():", "    pass"], [5, 5]),
], ids=["the edit keeps both neighbours", "the edit keeps one"])
def test_a_copy_that_moved_up_is_not_placed_over_an_edit_where_the_line_was(current, rival):
    # The mirror of the gamma()/delta() case: the imports went, so the exact copy in delta()
    # moved UP past the cited numbers, and gamma()'s own line was edited in place. Away from
    # the cited numbers an edit flanked as well as the copy is a rival, not only one flanked
    # by both neighbours (the second case keeps gamma() above it and loses omega() below).
    pinned = ["import a", "import b", "", "def gamma():", "    return None", "", "def omega():", "    pass"]
    result = hr.classify(pinned, 5, 5, current)
    assert (result["class"], result["now"], result["candidates"]) == ("ambiguous", None, [[2, 2], rival])


def test_an_edit_that_kept_no_neighbour_is_a_rival_for_a_copy_that_kept_none_either():
    # Every CONFIG value was bumped and a stray copy of the old retries entry landed in LIMITS:
    # neither the copy nor the edit kept a pinned neighbour, so neither is flanked better.
    pinned = ["CONFIG = {", '    "timeout_seconds": 30,', '    "max_retries": 3,', '    "backoff_factor": 2.0,', "}",
              "", "LIMITS = {", '    "burst": 9,', "}"]
    current = ["CONFIG = {", '    "timeout_seconds": 60,', '    "max_retries": 5,', '    "backoff_factor": 1.5,', "}",
               "", "LIMITS = {", '    "burst": 9,', '    "max_retries": 3,', "}"]
    result = hr.classify(pinned, 3, 3, current)
    assert (result["class"], result["now"], result["candidates"]) == ("ambiguous", None, [[3, 3], [9, 9]])


def test_a_whitespace_only_line_is_no_neighbour():
    # Line 3 holds only spaces, so it is blank: def b() is the neighbour below, and only the
    # second copy keeps it. Counted as a line, the spaces would anchor the first copy instead.
    pinned = ["def a():", "    return None", "    ", "def b():", "    pass"]
    current = ["def a():", "    return None", "    ", "def c():", "    pass", "", "def a():", "    return None", "",
               "def b():"]
    result = hr.classify(pinned, 2, 2, current)
    assert (result["class"], result["now"], result["anchored"]) == ("moved", [8, 8], True)


@pytest.mark.parametrize("width,searched", [(hr.MAX_REGION, True), (hr.MAX_REGION + 1, False)])
def test_a_region_of_exactly_max_region_lines_is_still_searched(width, searched):
    # The cited line's edit sits among `width` lines between its anchors; the exact copy far
    # below kept neither neighbour. Up to MAX_REGION lines the edit itself is found.
    pinned = ["def top():", "    value = compute(alpha, beta)", "def bottom():", "", "def tail():", "    pass"]
    steps = [f"    step_{i}()" for i in range(width - 1)]
    current = ["def top():", *steps[:200], "    value = compute(alpha, gamma)", *steps[200:], "def bottom():",
               "", "def tail():", "    pass", "", "def moved():", "    value = compute(alpha, beta)"]
    result = hr.classify(pinned, 2, 2, current)
    copy = [len(current), len(current)]
    assert result["class"] == "ambiguous"
    assert result["candidates"] == ([[202, 202], copy] if searched else [[2, width + 1], copy])


def test_a_look_alike_inserted_right_above_a_line_is_ambiguous_by_design():
    # A known, conservative outcome: "/z" inserted above "/a" reads exactly like "/a" edited
    # into "/z" with a fresh "/a" added below it, so the line is not guessed to have moved.
    # (It also pins the skip window: a rival that touches the exact copy is still a rival.)
    pinned = ["ROUTES = {", '    "/a": a,', "}"]
    current = ["ROUTES = {", '    "/z": z,', '    "/a": a,', "}"]
    result = hr.classify(pinned, 2, 2, current)
    assert result["class"] == "ambiguous" and result["candidates"] == [[2, 2], [3, 3]]
    assert result["now"] is None


def test_every_place_between_the_anchors_is_scored_not_only_the_best_so_far():
    # Two edits between f()'s anchors, each flanked as well as the exact copy in h(): one
    # scores 0.97, the later one far less. Both are rivals, so a scan that stopped scoring
    # windows below the best so far would lose the second.
    pinned = ["def f():", "    value = compute(alpha, beta)", "def g():", "    return 1"]
    current = ["def f():", "    value = compute(alpha, betx)", "    more()", "    value = compute(gamma, delta)",
               "def g():", "    return 1", "", "def h():", "    value = compute(alpha, beta)", "def g():"]
    result = hr.classify(pinned, 2, 2, current)
    assert result["class"] == "ambiguous" and result["candidates"] == [[2, 2], [4, 4], [9, 9]]


def test_an_exact_copy_is_not_placed_when_the_lines_between_its_anchors_are_too_many_to_search():
    # 450 lines now sit where the cited line was, and one of them is its edit; the exact copy
    # far away keeps neither neighbour. A region wider than MAX_REGION is a rewrite, as in
    # _nearest: it is not searched, and all of it stays a candidate beside the copy.
    pinned = ["def top():", "    value = compute(alpha, beta)", "def bottom():", "", "def tail():", "    pass"]
    steps = [f"    step_{i}()" for i in range(hr.MAX_REGION + 50)]
    current = ["def top():", *steps[:200], "    value = compute(alpha, gamma)", *steps[200:], "def bottom():",
               "", "def tail():", "    pass", "", "def moved():", "    value = compute(alpha, beta)"]
    result = hr.classify(pinned, 2, 2, current)
    assert result["class"] == "ambiguous" and result["now"] is None
    assert result["candidates"] == [[2, len(steps) + 2], [len(current), len(current)]]


def test_a_copy_that_kept_a_neighbour_is_searched_around_between_anchors_of_any_width():
    # The shape of H472's worker.py:44 on the real repository: the imports above grew, so the
    # constant moved down, still under its logger line, and 400+ lines were added below it
    # (the alignment anchors it between its logger line and the blank line above the tail).
    # Only windows flanked as well as the copy compete, so any width is cheap to search.
    tail = ["# executor(task) -> dict", "Executor = Callable", "Notifier = Callable", "", "", "class Worker:",
            "    def run(self):", "        return self.step()"]
    pinned = ["from .queue import Task, TaskQueue", "", "logger = get_logger()", "", "BUDGET = 4", "", *tail]
    added = [f"    step_{i}()" for i in range(hr.MAX_REGION + 10)]
    current = ["from .queue import (", "    Task,", "    TaskQueue,", ")", "", "logger = get_logger()", "",
               "BUDGET = 4", "", "# refusal vocabulary", "def refuse():", *added, "", *tail]
    lo, hi, _ = hr._region(pinned, 4, 5, current)
    assert hi - lo > hr.MAX_REGION
    result = hr.classify(pinned, 5, 5, current)
    assert (result["class"], result["now"], result["anchored"]) == ("moved", [8, 8], False)
    # An edit that the executor comment still flanks, however far down, is a rival.
    edited = [*current[:-len(tail) - 1], "BUDGET = 40", "", *tail]
    result = hr.classify(pinned, 5, 5, edited)
    assert result["class"] == "ambiguous" and result["candidates"] == [[8, 8], [422, 422]]
    assert edited[421] == "BUDGET = 40"


def test_a_flanked_window_is_a_rival_even_where_an_unflanked_one_scores_higher():
    # f()'s line was edited in place and more() added after it: the one-line window scores
    # best but nothing flanks it, while the two-line window keeps g() below it, as the exact
    # copy in h() does. Flanking is judged before places are chosen, so the edit competes.
    pinned = ["def f():", "    value = compute(alpha, beta)", "def g():", "    return 1"]
    current = ["def f():", "    other()", "    value = compute(alpha, betx)", "    more()", "def g():",
               "    return 1", "", "def h():", "    value = compute(alpha, beta)", "def g():"]
    result = hr.classify(pinned, 2, 2, current)
    assert result["class"] == "ambiguous" and result["candidates"] == [[3, 4], [9, 9]]


@pytest.mark.parametrize("pinned,first,last,current", [
    # TypeScript: load()'s guard is gone; save() keeps one of the very same shape.
    (["export function load(ok: boolean) {", "  if (!ok) {", "    return null;", "  }", "  return fetchAll();", "}",
      "", "export function save(valid: boolean) {", "  if (!valid) {", "    return null;", "  }",
      "  return store();", "}"], 2, 4,
     ["export function load() {", "  return fetchAll();", "}", "", "export function save(valid: boolean) {",
      "  if (!valid) {", "    return null;", "  }", "  return store();", "}"]),
    # Python: start()'s warm-up is gone; stop() keeps a try/except/pass of the same shape.
    (["def start():", "    try:", "        warm_cache()", "    except Exception:", "        pass", "    serve()", "",
      "def stop():", "    try:", "        flush()", "    except Exception:", "        pass"], 2, 5,
     ["def start():", "    serve()", "", "def stop():", "    try:", "        flush()", "    except Exception:",
      "        pass"]),
    # One line, deleted: stop()'s warning resembles it and sits between the same generic
    # neighbours (`except Exception:` above, `raise` below), which vouch for nothing.
    (["def start():", "    try:", "        warm_cache()", "    except Exception:",
      '        log.warning("start: cache cold")', "        raise", "", "def stop():", "    try:", "        flush()",
      "    except Exception:", '        log.warning("stop: flush failed")', "        raise"], 5, 5,
     ["def start():", "    serve()", "", "def stop():", "    try:", "        flush()", "    except Exception:",
      '        log.warning("stop: flush failed")', "        raise"]),
    # TypeScript again, but save()'s guard sits one level deeper, inside try {}: indentation
    # does not make `return null;` or `}` distinct.
    (["export function load(ok: boolean) {", "  if (!ok) {", "    return null;", "  }", "  return fetchAll();", "}",
      "", "export function save(valid: boolean) {", "  try {", "    if (!valid) {", "      return null;", "    }",
      "    return store();", "  } catch (e) {", "    return undefined;", "  }", "}"], 2, 4,
     ["export function load(ok: boolean) {", "  return fetchAll();", "}", "", "export function save(valid: boolean) {",
      "  try {", "    if (!valid) {", "      return null;", "    }", "    return store();", "  } catch (e) {",
      "    return undefined;", "  }", "}"]),
], ids=["braces", "try-except", "generic neighbours", "nested braces"])
def test_generic_lines_never_vouch_for_a_place_away_from_the_anchors(pinned, first, last, current):
    # `}`, `return null;`, `try:` and `pass` occur more than once in the pinned file: finding
    # them again proves nothing, so a same-shaped block elsewhere is not where these lines went.
    result = hr.classify(pinned, first, last, current)
    assert (result["class"], result["now"]) == ("deleted", None)


def test_only_non_blank_text_that_occurs_once_in_the_pinned_file_can_vouch():
    lines = ["def f():", "    pass", "", "def g():", "    pass", "  }", "  }"]   # one blank line, too
    assert hr._distinct(lines) == {"def f():", "def g():"}
    # Indentation aside: a `}` closing a nested block is the same generic text as any other.
    assert hr._distinct(["  }", "    }", "x = 1"]) == {"x = 1"}


def test_a_missing_line_past_the_file_edge_never_vouches():
    # Above line 1 and below the last line there is no neighbour: two missing ones are not an
    # unchanged line that agrees (and must not be read as text).
    pinned = ["import os", "import sys", "def main():"]
    assert hr._vouched(pinned, 0, 2, list(pinned), 0, 2, hr._distinct(pinned)) == 3   # 2 own lines, 1 below
    assert hr._vouched(["import os"], 0, 1, ["import os"], 0, 1, {"import os"}) == 1
    # End to end: a block at the top of both files, searched for away from its anchors.
    result = hr.classify(["    }", "import os", "    y = 2", "    def m(self):"], 1, 3,
                         ["    y = 2", "im_ort os", "    def m(self):"])
    assert (result["class"], result["now"], result["candidates"]) == ("ambiguous", None, [[1, 2]])


def test_one_unchanged_line_and_one_neighbour_vouch_together_even_reindented():
    # c()'s tail moved into a class above it and was re-indented: "y = 2" is still there, and
    # "return self.v" still sits above it. Two distinct unchanged lines vouch for the place.
    pinned = ["def c():", "    return total", "        return self.v", "    y = 2"]
    current = ["        return self.v", "        y = 2", "def c():", "    return total"]
    result = hr.classify(pinned, 4, 4, current)
    assert (result["class"], result["now"], result["anchored"]) == ("edited", [2, 2], False)


def test_two_edits_scoring_alike_are_ambiguous():
    pinned = ["def f():", "    value = compute(alpha, b0)", "    return value"]
    current = ["def f():", "    value = compute(alpha, b1)", "    value = compute(alpha, b2)", "    return value"]
    result = hr.classify(pinned, 2, 2, current)
    assert result["class"] == "ambiguous" and result["candidates"] == [[2, 2], [3, 3]]


def test_a_gap_wider_than_max_region_is_a_rewrite_not_a_location():
    pinned = ["def top():", "    value = compute(alpha, beta)", "def bottom():"]
    steps = [f"    step_{i}()" for i in range(hr.MAX_REGION + 50)]
    current = ["def top():", *steps, "    value = compute(alpha, gamma)", "def bottom():"]
    result = hr.classify(pinned, 2, 2, current)
    assert result["class"] == "ambiguous" and result["candidates"] == [[2, len(steps) + 2]]


def test_a_suggestion_that_would_not_resolve_is_flagged():
    # The best window starts on a blank line, and hermes_status rejects a citation there.
    pinned = ["def f():", "    a = compute(1)", "    b = compute(2)", "def g():"]
    current = ["def f():", "", "    b = compute(2)", "def g():"]
    view = {"_pinned": pinned, "_current": current, "now_path": "m.py", "state": "drifted", "found": "found"}
    entry = hr._place("m.py:2-3", "m.py", "m.py", 2, 3, view)
    assert (entry["class"], entry["now"], entry["resolves"]) == ("edited", [2, 3], False)
    assert "(would NOT resolve)" in hr._render_citation(entry)[0]


# --- stamp ---------------------------------------------------------------------------------

def write_patch(tmp_path: Path, items: list[dict]) -> Path:
    path = tmp_path / "patch.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def reread_h002(**changes) -> dict:
    item = {"id": "H002", "status": "partial",
            "summary": "Re-read at HEAD: the registry is example.py:14-15 and beta agents/core/example.py:18-19.",
            "remaining": "Event delivery is still missing; strict mode needs a test.",
            "evidence": [EXAMPLE, "tests/test_example.py"]}
    item.update(changes)
    return item


def fresh_h003() -> dict:
    return {"id": "H003", "status": "missing",
            "summary": "Nothing governed exists yet; read agents/core/stable.py:2 to confirm the absence.",
            "remaining": "Build the governed shape behind the Action Kernel, with tests.",
            "evidence": ["agents/core/stable.py"]}


def stamp(repo, items, *extra: str) -> int:
    return hr.main(["--root", str(repo.root), "stamp", "--patch", str(write_patch(repo.tmp, items)), *extra])


def review_block(item: dict) -> str:
    return textwrap.indent(json.dumps(item, ensure_ascii=False, indent=2), "    ")


def test_stamp_rewrites_only_the_patched_reviews(repo, capsys):
    target = repo.root / hs.ASSESSMENT
    before = target.read_text(encoding="utf-8")
    old = {item["id"]: item for item in json.loads(before)["reviews"]}
    assert stamp(repo, [reread_h002(), fresh_h003()]) == 0
    assert "stamped H002, H003" in capsys.readouterr().out
    after = target.read_text(encoding="utf-8")
    data = json.loads(after)
    assert after == json.dumps(data, ensure_ascii=False, indent=2) + "\n" and "completă —" in after
    assert [item["id"] for item in data["reviews"]] == ["H002", "H003", "H004", "H005"]
    assert data["base_sha"] == git(repo.root, "rev-parse", "HEAD") == repo.c3
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["assessed_at"])
    new = {item["id"]: item for item in data["reviews"]}
    assert new["H002"]["row_sha256"] == hs.digest(CAPS[1])
    assert new["H002"]["evidence"] == [{"path": p, "sha256": hs.file_digest(repo.root / p)}
                                       for p in (EXAMPLE, "tests/test_example.py")]
    assert list(new["H003"]) == ["id", "row_sha256", "status", "summary", "remaining", "evidence"]
    for ident in ("H004", "H005"):   # untouched reviews keep their exact bytes
        assert new[ident] == old[ident] and review_block(old[ident]) in after
    tail = '"scope_reopenings"'
    assert after[after.index(tail):] == before[before.index(tail):]
    rows = {row["id"]: row for row in hs.assess(repo.ledger, data, repo.root)}
    assert rows["H002"]["basis"] == rows["H003"]["basis"] == "reviewed"
    assert rows["H004"]["basis"] == "stale_evidence"


def test_restamping_an_unchanged_review_round_trips_byte_for_byte(repo):
    target = repo.root / hs.ASSESSMENT
    before = target.read_bytes()
    data = json.loads(before)
    item = next(r for r in data["reviews"] if r["id"] == "H005")
    patch = [{"id": "H005", "status": item["status"], "summary": item["summary"],
              "remaining": item["remaining"], "evidence": [e["path"] for e in item["evidence"]]}]
    assert stamp(repo, patch, "--base-sha", data["base_sha"], "--assessed-at", data["assessed_at"]) == 0
    assert target.read_bytes() == before


def test_dry_run_shows_the_change_and_writes_nothing(repo, capsys):
    target = repo.root / hs.ASSESSMENT
    before = target.read_bytes()
    assert stamp(repo, [reread_h002()], "--dry-run") == 0
    out = capsys.readouterr().out
    assert "would stamp H002" in out and "+      \"summary\": \"Re-read at HEAD" in out
    assert target.read_bytes() == before


def _stale(monkeypatch):
    # If the recorded hash ever disagreed with what hermes_status reads back, the row would
    # land stale: a restamp that immediately needs review again must never be written.
    monkeypatch.setattr(hr, "_evidence_digest", lambda path: "0" * 64)
    return [reread_h002()]


@pytest.mark.parametrize("case,items,reason", [
    ("bad citation", lambda mp: [reread_h002(summary="Re-read: see agents/core/example.py:999.")], "citation"),
    ("equivalent with work left", lambda mp: [reread_h002(status="equivalent")], "unfinished"),
    ("whitespace remaining", lambda mp: [reread_h002(remaining=" \n\t ")], "whitespace"),
    # hermes_status accepts a whitespace-only `remaining` on a missing row; only the helper refuses it.
    ("whitespace remaining, missing", lambda mp: [reread_h002(status="missing", remaining="  ")], "whitespace"),
    ("excluded", lambda mp: [reread_h002(status="excluded", remaining="")], "excluded"),
    ("needs_review", lambda mp: [reread_h002(status="needs_review")], "needs_review"),
    ("would be stale", _stale, "stale"),
    ("missing evidence file", lambda mp: [reread_h002(evidence=["agents/core/absent.py"])], "absent.py"),
    ("evidence escapes", lambda mp: [reread_h002(evidence=["../outside.py"])], "path"),
    ("hash supplied", lambda mp: [reread_h002(evidence=[{"path": EXAMPLE, "sha256": "0" * 64}])], "paths"),
    ("unknown field", lambda mp: [reread_h002(extra=True)], "fields"),
    ("duplicate id", lambda mp: [reread_h002(), reread_h002()], "twice"),
    ("unknown row", lambda mp: [reread_h002(id="H999")], "H999"),
    ("empty patch", lambda mp: [], "empty"),
])
def test_stamp_refuses_and_writes_nothing(repo, monkeypatch, capsys, case, items, reason):
    target = repo.root / hs.ASSESSMENT
    before, listing = target.read_bytes(), sorted(os.listdir(target.parent))
    assert stamp(repo, items(monkeypatch)) == 1, case
    err = capsys.readouterr().err
    assert "refused" in err and reason in err, err
    assert target.read_bytes() == before
    assert sorted(os.listdir(target.parent)) == listing   # no temp file left behind


@pytest.mark.parametrize("reshape", [
    lambda raw: json.dumps(json.loads(raw), ensure_ascii=False).encode(),   # compact
    lambda raw: raw.rstrip(b"\n"),                                          # no final newline
])
def test_stamp_refuses_a_file_it_could_not_rewrite_byte_identically(repo, capsys, reshape):
    target = repo.root / hs.ASSESSMENT
    reshaped = reshape(target.read_bytes())
    target.write_bytes(reshaped)
    assert stamp(repo, [reread_h002()]) == 1
    assert "round-trip" in capsys.readouterr().err and target.read_bytes() == reshaped


def test_stamp_accepts_the_last_inventory_row(repo, capsys):
    last = f"H{len(CAPS):03}"   # reopened, so a review may now record it
    item = {"id": last, "status": "missing", "summary": "Nothing governs it yet; agents/core/stable.py:2 is unrelated.",
            "remaining": "Build it, with tests.", "evidence": ["agents/core/stable.py"]}
    assert stamp(repo, [item]) == 0, capsys.readouterr().err
    rows = {row["id"]: row for row in hs.assess(repo.ledger, hs.load(repo.root)[1], repo.root)}
    assert rows[last]["basis"] == "reviewed"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_stamp_keeps_the_records_file_mode(repo):
    target = repo.root / hs.ASSESSMENT
    target.chmod(0o640)   # mkstemp creates 0600: the rename must not narrow who can read the records
    assert stamp(repo, [reread_h002()]) == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


# --- stamp pins only what a commit holds -----------------------------------------------------

@pytest.mark.parametrize("case", ["edited", "staged"])
def test_stamp_refuses_uncommitted_evidence_unless_told_to_allow_it(repo, capsys, case):
    # base_sha would not hold the pinned bytes: every clean checkout would read the row stale.
    target = repo.root / hs.ASSESSMENT
    before = target.read_bytes()
    if case == "edited":
        name, items = EXAMPLE, [reread_h002()]
        put(repo.root, EXAMPLE, [*V3, "LOCAL_EDIT = 1"])
    else:
        name = "agents/core/staged.py"
        items = [reread_h002(evidence=[EXAMPLE, "tests/test_example.py", name])]
        put(repo.root, name, ["def staged():", "    return 1"])
        git(repo.root, "add", name)
    assert stamp(repo, items) == 1
    err = capsys.readouterr().err
    assert "uncommitted" in err and name in err and "--allow-uncommitted" in err
    assert target.read_bytes() == before
    assert stamp(repo, items, "--allow-uncommitted", "--dry-run") == 0
    out = capsys.readouterr().out
    assert f"UNCOMMITTED {name}" in out and "would stamp H002" in out
    assert out.index("WARNING: base_sha") < out.index(f"UNCOMMITTED {name}")   # a header says why
    assert out.index(f"UNCOMMITTED {name}") < out.index("@@")   # listed ahead of the diff
    assert target.read_bytes() == before
    assert stamp(repo, items, "--allow-uncommitted") == 0
    out = capsys.readouterr().out
    assert f"UNCOMMITTED {name}" in out and "stamped H002" in out
    recorded = next(r for r in hs.load(repo.root)[1]["reviews"] if r["id"] == "H002")
    assert {"path": name, "sha256": hs.file_digest(repo.root / name)} in recorded["evidence"]


@pytest.mark.parametrize("ignored", [True, False])
def test_stamp_refuses_untracked_or_ignored_evidence_even_when_uncommitted_is_allowed(repo, capsys, ignored):
    put(repo.root, ".gitignore", ["scratch/"])
    commit(repo.root, "ignore scratch/")
    name = "scratch/notes.py" if ignored else "agents/core/notes.py"
    put(repo.root, name, ["def notes():", "    return 'never committed'"])
    target = repo.root / hs.ASSESSMENT
    before = target.read_bytes()
    for extra in ((), ("--allow-uncommitted",)):
        assert stamp(repo, [reread_h002(evidence=[EXAMPLE, "tests/test_example.py", name])], *extra) == 1
        err = capsys.readouterr().err
        assert ("gitignored" if ignored else "untracked") in err and name in err, err
    assert target.read_bytes() == before


@pytest.mark.parametrize("base", ["c2", "unknown"])
def test_stamp_refuses_a_base_sha_that_does_not_hold_the_evidence(repo, capsys, base):
    sha = getattr(repo, base, "b" * 40)   # c2 holds v2 of example.py; the tree holds v3
    target = repo.root / hs.ASSESSMENT
    before = target.read_bytes()
    assert stamp(repo, [reread_h002()], "--base-sha", sha) == 1
    err = capsys.readouterr().err
    assert "uncommitted" in err and EXAMPLE in err and sha[:12] in err
    assert target.read_bytes() == before


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
@pytest.mark.parametrize("link,points_to,name,committed", [
    ("agents/core/example_link.py", "example.py", "agents/core/example_link.py", True),   # the file is a link
    ("agents/linked", "core", "agents/linked/example.py", True),                          # a directory on its path is
    ("example_link.py", EXAMPLE, "example_link.py", True),                                # at the top level, too
    # Not committed yet: the index knows nothing of it, the working tree does, and the link
    # (not "untracked") is what to fix.
    ("agents/linked", "core", "agents/linked/example.py", False),
])
def test_stamp_refuses_evidence_reached_through_a_symlink_and_names_the_link(repo, capsys, link, points_to, name,
                                                                             committed):
    # hermes_status hashes the target's text, git holds the link (its target's path), and a
    # checkout without symlinks writes the link as a text file: no pin through it can hold.
    (repo.root / link).symlink_to(points_to)
    if committed:
        commit(repo.root, "a committed, clean symlink")
        assert git(repo.root, "status", "--porcelain") == ""
    target = repo.root / hs.ASSESSMENT
    before = target.read_bytes()
    for extra in ((), ("--allow-uncommitted",)):
        assert stamp(repo, [reread_h002(evidence=[EXAMPLE, "tests/test_example.py", name])], *extra) == 1
        err = capsys.readouterr().err
        assert f"reached through the symlink {link}: " in err and "pin the file it points to" in err, err
        assert "uncommitted" not in err and "untracked" not in err, err
    assert target.read_bytes() == before


def test_stamp_refuses_a_symlink_checked_out_as_a_text_file(repo, capsys):
    # With core.symlinks=false (Windows' default) git writes a committed link as a text file
    # holding its target's path. That text hashes like git's blob, so nothing looks
    # uncommitted, yet every checkout with symlinks would hash example.py's text instead.
    # Only the index knows it is a link. (Built with plumbing, so it runs on Windows, too.)
    link = "agents/core/example_link.py"
    blob = subprocess.run(["git", "-C", str(repo.root), "hash-object", "-w", "--stdin"], input=b"example.py",
                          check=True, capture_output=True).stdout.decode().strip()
    git(repo.root, "update-index", "--add", "--cacheinfo", f"120000,{blob},{link}")
    git(repo.root, "commit", "-q", "-m", "a committed symlink")
    clone = repo.tmp / "no-symlinks"
    subprocess.run(["git", "clone", "-q", "-c", "core.symlinks=false", repo.root.as_uri(), str(clone)],
                   check=True, capture_output=True)
    assert not (clone / link).is_symlink() and (clone / link).read_text(encoding="utf-8") == "example.py"
    assert git(clone, "status", "--porcelain") == ""
    target = clone / hs.ASSESSMENT
    before = target.read_bytes()
    patch = write_patch(repo.tmp, [reread_h002(evidence=[EXAMPLE, "tests/test_example.py", link])])
    for extra in ((), ("--allow-uncommitted",)):
        assert hr.main(["--root", str(clone), "stamp", "--patch", str(patch), *extra]) == 1
        err = capsys.readouterr().err
        assert f"reached through the symlink {link}: " in err, err
    assert target.read_bytes() == before


LINKED = "docs/records.json"   # a symlink to the records file


@pytest.mark.parametrize("name", [hs.ASSESSMENT, "HERMES_STATUS.md", "docs/HERMES_CAPABILITIES.md", LINKED])
def test_stamp_refuses_evidence_that_the_stamp_or_its_reports_rewrite(repo, capsys, name):
    ledger, data = hs.load(repo.root)
    assert name in (hs.ASSESSMENT, LINKED) or name in hs.reports(hs.assess(ledger, data, repo.root), data)
    if name == LINKED:
        if os.name == "nt":
            pytest.skip("symlinks need privileges on Windows")
        (repo.root / LINKED).symlink_to("hermes/assessment.json")
        commit(repo.root, "link the records")
    elif name != hs.ASSESSMENT:
        put(repo.root, name, ["# written by hermes_status write"])
        commit(repo.root, f"add {name}")
    target = repo.root / hs.ASSESSMENT
    before = target.read_bytes()
    assert stamp(repo, [reread_h002(evidence=[EXAMPLE, "tests/test_example.py", name])]) == 1
    err = capsys.readouterr().err
    assert "generated" in err and name in err, err
    assert target.read_bytes() == before


# --- the real repository, read-only --------------------------------------------------------

def test_drift_and_cite_run_read_only_on_the_real_repository(capsys):
    if not (hs.REPO / ".git").exists():
        pytest.skip("not a git checkout")
    ledger, data = hs.load()
    stale = [row for row in hs.assess(ledger, data, hs.REPO) if row["basis"] == "stale_evidence"]
    if not stale:
        pytest.skip("no stale row right now")
    row = min(stale, key=lambda r: (len(r["evidence"]), r["id"]))
    target = hs.REPO / hs.ASSESSMENT
    before, mtime = target.read_bytes(), target.stat().st_mtime_ns
    assert hr.main(["drift", row["id"]]) == 0
    assert hr.main(["cite", row["id"]]) == 0
    out = capsys.readouterr().out
    assert out.count(row["id"]) >= 2 and "pinned" in out
    assert target.read_bytes() == before and target.stat().st_mtime_ns == mtime


def test_the_script_runs_standalone(repo):
    proc = subprocess.run([sys.executable, str(hs.REPO / "scripts" / "hermes_restamp.py"),
                           "--root", str(repo.root), "drift", "H002"],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    assert "H002" in proc.stdout and "drifted" in proc.stdout


# ── review round 4: file edges and a mirror whose copy holds the alignment ────


def test_file_edges_count_as_agreeing_neighbours():
    # A missing neighbour at the file edge agrees with a missing one: the mirror whose cited
    # line ends the file stays ambiguous, and a last line moved down keeps its anchor.
    result = hr.classify(["def f():", "    return compute(1)"], 2, 2,
                         ["def f_new():", "    return compute(1)", "", "def f():", "    return compute(2)"])
    assert (result["class"], result["candidates"]) == ("ambiguous", [[2, 2], [5, 5]])
    moved = hr.classify(["import os", "", "def f():", "    return compute(1)"], 4, 4,
                        ["import os", "import sys", "", "def g():", "    pass", "", "def f():", "    return compute(1)"])
    assert (moved["class"], moved["now"], moved["anchored"]) == ("moved", [8, 8], True)


@pytest.mark.parametrize("pinned,first,current,rival", [
    (["class T:", "    def test_a(self):", "        assert run() == 1", "        assert run2() == 2",
      "        assert run3() == 3"], 3,
     ["class T:", "    def test_new(self):", "        assert run() == 1", "        assert run2() == 2",
      "        assert run3() == 3", "", "    def test_a(self):", "        assert run() == 10",
      "        assert run2() == 2", "        assert run3() == 3"], [8, 8]),
    (["def test_a():", "    assert run() == 1", "    assert other() == 3"], 2,
     ["def test_new():", "    assert run() == 1", "    assert other() == 3", "", "def test_a():",
      "    assert run() == 10", "    assert other() == 3"], [6, 6]),
], ids=["class method last in file", "function last in file"])
def test_mirror_whose_copy_holds_the_alignment(pinned, first, current, rival):
    # difflib aligns the pinned tail with the copy above, so the anchored region misses the
    # edit both pinned neighbours still flank; that edit must still rival the copy.
    result = hr.classify(pinned, first, first, current)
    assert (result["class"], result["candidates"]) == ("ambiguous", [[first, first], rival])
