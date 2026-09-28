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
    assert hr.main(["--root", str(repo.root), "drift", "H999"]) == 1
    assert "unknown row" in capsys.readouterr().err


# --- cite ----------------------------------------------------------------------------------

def test_cite_classifies_unchanged_moved_edited_deleted_and_ambiguous_lines(repo):
    report = cited(hr.cite(repo.root, "H002"))
    assert report["example.py:1"]["class"] == "unchanged" and report["example.py:1"]["now"] == [1, 1]
    moved = report["example.py:3-4"]
    assert moved["class"] == "moved" and moved["now"] == [14, 15] and moved["anchored"] is True
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


@pytest.mark.parametrize("line,shown", [(30, False), (31, True)])
def test_a_hunk_is_shown_exactly_when_it_reaches_a_cited_line(repo, line, shown):
    # v3 changed only pinned line 34, so git's hunk (3 lines of context) covers 31-34.
    data = hs.load(repo.root)[1]
    next(r for r in data["reviews"] if r["id"] == "H002")["summary"] = (
        f"Only the constant at agents/core/example.py:{line} is cited.")
    save(repo.root, data)
    hunks = hr.cite(repo.root, "H002")["files"][EXAMPLE]["hunks"]
    assert ("+CONSTANT_11 = 110" in "\n".join(hunks)) is shown


@pytest.mark.parametrize("start,count,shown", [
    (2, 3, False), (3, 3, True), (10, 3, True), (11, 3, False),   # a cited range of 5-10
    (4, 0, False), (5, 0, True), (9, 0, True), (10, 0, False),    # lines inserted after `start`
])
def test_hunk_overlap_boundaries(start, count, shown):
    assert hr._overlaps(start, count, 5, 10) is shown


def test_cite_follows_a_renamed_file_and_reports_a_deleted_one(repo):
    report = cited(hr.cite(repo.root, "H004"))
    renamed = report["old_name.py:2"]
    assert renamed["class"] == "moved" and renamed["now_path"] == "agents/core/new_name.py"
    assert renamed["now"] == [2, 2] and renamed["suggest"] == "agents/core/new_name.py:2"
    assert report["gone.py:1"]["class"] == "deleted"


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


def test_stamp_refuses_a_file_it_could_not_rewrite_byte_identically(repo, capsys):
    target = repo.root / hs.ASSESSMENT
    compact = json.dumps(json.loads(target.read_bytes()), ensure_ascii=False).encode()
    target.write_bytes(compact)
    assert stamp(repo, [reread_h002()]) == 1
    assert "round-trip" in capsys.readouterr().err and target.read_bytes() == compact


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
