"""H503 — one archive-safety module for every surface that unpacks or produces an archive.

Hermes keeps this logic in a single file on purpose: a second transfer surface with its
own extractor is how a weaker one ships. Nerva had two (backup tar restore, marketplace
zip install), each correct against ``../`` and neither against the rest of the list.
These tests pin the shared module directly; the backup and marketplace suites pin that
their entry points actually go through it.
"""
import io
import os
import re
import stat
import sys
import tarfile
import zipfile
from collections import namedtuple
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core import archive_safe as asafe  # noqa: E402
from agents.core.archive_safe import ArchiveLimits, ArchiveRejected  # noqa: E402

_BIG = ArchiveLimits(max_members=1000, max_bytes=10 * 1024 * 1024)


# ── name normalisation ─────────────────────────────────────────────
@pytest.mark.parametrize("name, parts", [
    ("a.txt", ("a.txt",)),
    ("dir/sub/a.txt", ("dir", "sub", "a.txt")),
    ("dir\\sub\\a.txt", ("dir", "sub", "a.txt")),     # Windows-authored separator is folded
    ("./dir/a.txt", ("dir", "a.txt")),                  # `tar -C x .` style prefix
    ("dir/", ("dir",)),                                 # zip directory marker
    ("v1..2.txt", ("v1..2.txt",)),                      # dots inside a name are not traversal
])
def test_normalize_accepts_ordinary_names(name, parts):
    assert asafe.normalize_member(name) == parts


@pytest.mark.parametrize("name", [
    "",
    "/etc/passwd",                 # POSIX-absolute
    "\\Windows\\evil.dll",         # Windows root-relative, absolute once folded
    "C:/Windows/evil.dll",         # drive-lettered
    "c:evil.txt",                  # drive-relative
    "C:\\evil.txt",
    "\\\\server\\share\\x",        # UNC
    "//server/share/x",
    "../escape.txt",
    "..\\escape.txt",              # the separator a POSIX parse would not see
    "a/../../escape.txt",
    "a/..",
    "a//b.txt",                    # an empty interior part is an anomaly, not a path
    "a/\x00b.txt",
    ".",
])
def test_normalize_rejects_escaping_or_anomalous_names(name):
    with pytest.raises(ArchiveRejected):
        asafe.normalize_member(name)


def test_archive_rejected_is_a_value_error():
    # Both HTTP entry points map ValueError to a refusal; keep that contract.
    assert issubclass(ArchiveRejected, ValueError)


# ── tar helpers ────────────────────────────────────────────────────
def _tar(members) -> tarfile.TarFile:
    """Build an in-memory tar from (TarInfo, bytes|None) pairs and reopen it for reading."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode="r")


def _file(name, data=b"x"):
    return (tarfile.TarInfo(name), data)


def _special(name, kind, linkname=""):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    return (info, None)


def test_extract_tar_writes_regular_files_and_dirs(tmp_path):
    d = tarfile.TarInfo("sub")
    d.type = tarfile.DIRTYPE
    tar = _tar([(d, None), _file("sub/a.txt", b"hello"), _file("b.txt", b"yo")])
    count = asafe.extract_tar(tar, tmp_path / "dest", limits=_BIG)
    assert count == 2
    assert (tmp_path / "dest" / "sub" / "a.txt").read_bytes() == b"hello"
    assert (tmp_path / "dest" / "b.txt").read_bytes() == b"yo"


@pytest.mark.parametrize("kind, label", [
    (tarfile.SYMTYPE, "symlink"),
    (tarfile.LNKTYPE, "hardlink"),
    (tarfile.CHRTYPE, "device"),
    (tarfile.BLKTYPE, "device"),
    (tarfile.FIFOTYPE, "fifo"),
])
def test_extract_tar_raises_on_links_and_special_members_before_writing(tmp_path, kind, label):
    # The regular file comes FIRST: a skip-and-continue extractor would already have
    # written it, and then quietly dropped the link — a partial tree reported as fine.
    tar = _tar([_file("first.txt", b"written?"), _special("bad", kind, linkname="/etc/passwd")])
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveRejected, match=label):
        asafe.extract_tar(tar, dest, limits=_BIG)
    assert not (dest / "first.txt").exists()          # validated before a byte is written


def test_extract_tar_rejects_traversal_and_windows_names(tmp_path):
    for evil in ("../escape.txt", "..\\escape.txt", "C:/x.txt", "/abs.txt"):
        tar = _tar([_file("ok.txt"), _file(evil)])
        dest = tmp_path / f"dest-{abs(hash(evil))}"
        with pytest.raises(ArchiveRejected):
            asafe.extract_tar(tar, dest, limits=_BIG)
        assert not (dest / "ok.txt").exists()
    assert not (tmp_path / "escape.txt").exists()


def test_extract_tar_member_count_cap(tmp_path):
    tar = _tar([_file(f"f{i}.txt") for i in range(6)])
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveRejected, match="members"):
        asafe.extract_tar(tar, dest, limits=ArchiveLimits(max_members=5, max_bytes=10_000))
    assert not any(dest.iterdir())


def test_extract_tar_byte_cap_raises_before_writing_past_it(tmp_path):
    tar = _tar([_file("a.bin", b"a" * 600), _file("b.bin", b"b" * 600)])
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveRejected, match="bytes"):
        asafe.extract_tar(tar, dest, limits=ArchiveLimits(max_members=10, max_bytes=1000))
    assert not any(dest.iterdir())                     # nothing written, not 1000 bytes of it


def test_extract_tar_byte_cap_is_also_counted_while_streaming(tmp_path, monkeypatch):
    # Declared sizes pass the pre-scan; the running counter is the second line.
    tar = _tar([_file("a.bin", b"a" * 600)])
    real = tar.extractfile

    def _lying(member):
        return io.BytesIO(real(member).read() * 3)     # yields more than it declared

    monkeypatch.setattr(tar, "extractfile", _lying)
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveRejected, match="bytes"):
        asafe.extract_tar(tar, dest, limits=ArchiveLimits(max_members=10, max_bytes=1000))
    assert not (dest / "a.bin").exists()               # the partial file is removed


def test_extract_budget_is_clamped_to_free_space(tmp_path, monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(asafe.shutil, "disk_usage", lambda _p: usage(10_000, 9_900, 100))
    tar = _tar([_file("a.bin", b"a" * 500)])
    with pytest.raises(ArchiveRejected, match="free space"):
        asafe.extract_tar(tar, tmp_path / "dest", limits=_BIG)


def test_extract_tar_rejects_file_directory_conflicts_and_duplicates(tmp_path):
    def _dir(name):
        info = tarfile.TarInfo(name)
        info.type = tarfile.DIRTYPE
        return (info, None)

    for members in (
        [_file("a"), _file("a/b.txt")],               # a file used as a directory
        [_file("a/b.txt"), _file("a")],               # ...in either order
        [_file("a"), _dir("a")],                      # an explicit dir entry over a file
        [_dir("a"), _file("a")],
        [_file("dup.txt", b"1"), _file("dup.txt", b"2")],
    ):
        dest = tmp_path / f"d{len(list(tmp_path.iterdir()))}"
        with pytest.raises(ArchiveRejected):
            asafe.extract_tar(_tar(members), dest, limits=_BIG)
        assert not dest.exists() or not any(dest.iterdir())


def test_extract_tar_refuses_to_write_through_a_preexisting_link_in_dest(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "tokens").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArchiveRejected):
        asafe.extract_tar(_tar([_file("tokens/x.txt")]), dest, limits=_BIG)
    assert not (outside / "x.txt").exists()


# ── zip ────────────────────────────────────────────────────────────
def _zip(entries) -> zipfile.ZipFile:
    """entries: (name, data) or (ZipInfo, data)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            z.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


def _zip_symlink(name, target):
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return (info, target)


def test_extract_zip_writes_files_and_folds_backslashes(tmp_path):
    zf = _zip([("SKILL.md", "# S\n"), ("pkg\\main.py", "x = 1\n"), ("assets/", "")])
    count = asafe.extract_zip(zf, tmp_path / "dest", limits=_BIG)
    assert count == 2
    assert (tmp_path / "dest" / "pkg" / "main.py").read_text() == "x = 1\n"
    assert (tmp_path / "dest" / "assets").is_dir()


@pytest.mark.parametrize("evil", ["..\\evil.txt", "C:/x.txt", "c:evil.txt", "/abs.txt",
                                  "\\\\server\\share\\x.txt", "a/../../evil.txt"])
def test_extract_zip_rejects_escaping_names(tmp_path, evil):
    zf = _zip([("ok.txt", "ok"), (evil, "pwned")])
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveRejected):
        asafe.extract_zip(zf, dest, limits=_BIG)
    assert not dest.exists() or not any(dest.iterdir())


def test_extract_zip_raises_on_symlink_entry(tmp_path):
    zf = _zip([("ok.txt", "ok"), _zip_symlink("link", "/etc/passwd")])
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveRejected, match="symlink"):
        asafe.extract_zip(zf, dest, limits=_BIG)
    assert not (dest / "ok.txt").exists()


def test_extract_zip_raises_on_special_file_entry(tmp_path):
    info = zipfile.ZipInfo("pipe")
    info.create_system = 3
    info.external_attr = (stat.S_IFIFO | 0o644) << 16
    with pytest.raises(ArchiveRejected, match="fifo"):
        asafe.extract_zip(_zip([(info, "")]), tmp_path / "dest", limits=_BIG)


def test_extract_zip_rejects_encrypted_entries(tmp_path):
    zf = _zip([("a.txt", "x")])
    zf.infolist()[0].flag_bits |= 0x1
    with pytest.raises(ArchiveRejected, match="encrypted"):
        asafe.extract_zip(zf, tmp_path / "dest", limits=_BIG)


def test_extract_zip_member_and_byte_caps(tmp_path):
    many = _zip([(f"f{i}.txt", "x") for i in range(6)])
    with pytest.raises(ArchiveRejected, match="members"):
        asafe.extract_zip(many, tmp_path / "d1", limits=ArchiveLimits(max_members=5, max_bytes=10_000))
    # A classic bomb shape: tiny compressed, large declared.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("zeros.bin", b"\0" * 200_000)
    buf.seek(0)
    bomb = zipfile.ZipFile(buf)
    with pytest.raises(ArchiveRejected, match="bytes"):
        asafe.extract_zip(bomb, tmp_path / "d2", limits=ArchiveLimits(max_members=5, max_bytes=100_000))
    assert not (tmp_path / "d2" / "zeros.bin").exists()


# ── producing side ─────────────────────────────────────────────────
def test_atomic_write_replaces_only_on_success(tmp_path):
    target = tmp_path / "archive.bin"
    target.write_bytes(b"previous good archive")
    with pytest.raises(RuntimeError), asafe.atomic_write(target) as fh:
        fh.write(b"half of the new one")
        raise RuntimeError("disk full")
    assert target.read_bytes() == b"previous good archive"   # the old one survives
    assert [p.name for p in tmp_path.iterdir()] == ["archive.bin"]  # no temp debris

    with asafe.atomic_write(target) as fh:
        fh.write(b"new archive")
    assert target.read_bytes() == b"new archive"
    assert [p.name for p in tmp_path.iterdir()] == ["archive.bin"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_atomic_write_is_owner_only(tmp_path):
    target = tmp_path / "secret.bin"
    with asafe.atomic_write(target) as fh:
        fh.write(b"x")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_collect_regular_files_skips_links(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("a")
    (root / "sub" / "b.txt").write_text("b")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (root / "planted").symlink_to(outside / "secret.txt")
    (root / "planted_dir").symlink_to(outside, target_is_directory=True)
    files, skipped = asafe.collect_regular_files(root)
    assert [p.relative_to(root).as_posix() for p in files] == ["a.txt", "sub/b.txt"]
    assert skipped == 2


# ── consolidation: no second extractor ─────────────────────────────
_EXTRACTOR = re.compile(r"\.extractall\(|\.extractfile\(|unpack_archive\(|\._extract_member\(")


_PRODUCT_ROOTS = ("agents", "scripts", "skills", "services", "worldview")
_VENDORED = {"node_modules", ".venv", "venv", "site-packages", "__pycache__"}


def _product_python():
    yield from sorted(repo_root.glob("*.py"))
    for top in _PRODUCT_ROOTS:
        for path in sorted((repo_root / top).rglob("*.py")):
            if _VENDORED.isdisjoint(path.relative_to(repo_root).parts):
                yield path


def test_archive_safe_is_the_only_extractor_in_the_product():
    """A second transfer surface with its own extractor is how a weaker one ships."""
    offenders = []
    for path in _product_python():
        rel = path.relative_to(repo_root).as_posix()
        if rel == "agents/core/archive_safe.py" or rel.startswith("agents/web/v2/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _EXTRACTOR.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == [], "archive extraction outside agents/core/archive_safe.py:\n" + "\n".join(offenders)
