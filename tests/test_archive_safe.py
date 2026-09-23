"""H503 — one archive-safety module for every surface that unpacks or produces an archive.

Hermes keeps this logic in a single file on purpose: a second transfer surface with its
own extractor is how a weaker one ships. Nerva had two (backup tar restore, marketplace
zip install), each correct against ``../`` and neither against the rest of the list.
These tests pin the shared module directly; the backup and marketplace suites pin that
their entry points actually go through it.
"""
import ast
import io
import os
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


# ── existing content in the destination (an in-place --force restore) ──
def _dir(name):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    return (info, None)


def test_extract_replaces_a_link_at_the_final_component_instead_of_writing_through_it(tmp_path):
    # dest/alias.txt -> dest/real.txt; the archive holds both as regular files. Writing
    # alias.txt THROUGH the link used to clobber real.txt with alias.txt's content.
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "real.txt").write_text("REAL-original")
    (dest / "alias.txt").symlink_to(dest / "real.txt")
    asafe.extract_tar(_tar([_file("real.txt", b"REAL-from-backup"),
                            _file("alias.txt", b"ALIAS-from-backup")]), dest, limits=_BIG)
    assert (dest / "real.txt").read_bytes() == b"REAL-from-backup"
    assert not (dest / "alias.txt").is_symlink()
    assert (dest / "alias.txt").read_bytes() == b"ALIAS-from-backup"


def test_extract_replaces_a_link_to_an_outside_file_without_touching_it(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside, untouched")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "key").symlink_to(outside)
    asafe.extract_tar(_tar([_file("key", b"from the archive")]), dest, limits=_BIG)
    assert outside.read_text() == "outside, untouched"
    assert not (dest / "key").is_symlink()
    assert (dest / "key").read_bytes() == b"from the archive"


def test_extract_does_not_write_through_a_hardlink_already_in_dest(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "a.bin").write_bytes(b"shared inode")
    os.link(dest / "a.bin", dest / "b.bin")
    asafe.extract_tar(_tar([_file("a.bin", b"A"), _file("b.bin", b"B")]), dest, limits=_BIG)
    assert (dest / "a.bin").read_bytes() == b"A"
    assert (dest / "b.bin").read_bytes() == b"B"


@pytest.mark.parametrize("existing, second", [
    ("file", "tokens/note.txt"),       # a file where a directory is needed
    ("file", "tokens/"),               # an explicit directory member over a file
    ("dir", "tokens"),                 # a directory where a file goes
    ("inroot-link", "tokens/note.txt"),  # a path that crosses a link already in dest
])
def test_extract_refuses_a_type_conflict_with_existing_content_before_writing(tmp_path, existing,
                                                                             second):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "first.txt").write_text("live, must survive a refused restore")
    if existing == "file":
        (dest / "tokens").write_text("a file")
    elif existing == "dir":
        (dest / "tokens").mkdir()
    else:
        (dest / "real").mkdir()
        (dest / "tokens").symlink_to(dest / "real", target_is_directory=True)
    member = _dir(second.rstrip("/")) if second.endswith("/") else _file(second)
    with pytest.raises(ArchiveRejected) as exc:
        asafe.extract_tar(_tar([_file("first.txt", b"from the archive"), member]), dest,
                          limits=_BIG)
    assert exc.value.partial is False                   # refused in the pre-scan
    assert (dest / "first.txt").read_text() == "live, must survive a refused restore"
    assert not (dest / "real" / "note.txt").exists()


def test_free_space_clamp_credits_the_files_the_archive_replaces(tmp_path, monkeypatch):
    # An in-place restore: the 3000 bytes being overwritten free their own blocks.
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(asafe.shutil, "disk_usage", lambda _p: usage(100_000, 99_000, 1000))
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "big.bin").write_bytes(b"o" * 3000)
    asafe.extract_tar(_tar([_file("big.bin", b"n" * 3000)]), dest, limits=_BIG)
    assert (dest / "big.bin").read_bytes() == b"n" * 3000
    # ...but a NEW 3000-byte file still does not fit in 1000 bytes of free space
    with pytest.raises(ArchiveRejected, match="free space"):
        asafe.extract_tar(_tar([_file("other.bin", b"n" * 3000)]), dest, limits=_BIG)
    assert not (dest / "other.bin").exists()


def test_a_failure_while_writing_is_marked_partial(tmp_path, monkeypatch):
    tar = _tar([_file("a.txt", b"a"), _file("b.txt", b"b")])
    real = tar.extractfile
    calls = []

    def _broken(member):
        calls.append(member.name)
        if member.name == "b.txt":
            raise tarfile.ReadError("unexpected end of data")
        return real(member)

    monkeypatch.setattr(tar, "extractfile", _broken)
    with pytest.raises(ArchiveRejected, match="corrupt") as exc:
        asafe.extract_tar(tar, tmp_path / "dest", limits=_BIG)
    assert exc.value.partial is True                    # a.txt was already written
    assert calls == ["a.txt", "b.txt"]


# ── tar header payloads and corrupt streams ─────────────────────────
def _gz_header_bomb(path: Path, kind: bytes, size: int) -> Path:
    """A gzip'd tar whose first header declares a *size*-byte PAX / GNU long-name payload."""
    import gzip
    info = tarfile.TarInfo("bomb")
    info.type = kind
    info.size = size
    with gzip.open(path, "wb") as gz:
        gz.write(info.tobuf(format=tarfile.USTAR_FORMAT))
        chunk = b"0" * (1024 * 1024)
        for _ in range(size // len(chunk)):
            gz.write(chunk)
    return path


@pytest.mark.parametrize("kind", [tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME,
                                  tarfile.GNUTYPE_LONGLINK])
def test_an_oversized_tar_header_payload_is_refused_before_it_is_read(tmp_path, kind):
    import tracemalloc
    arc = _gz_header_bomb(tmp_path / "bomb.tar.gz", kind, 48 * 1024 * 1024)
    tracemalloc.start()
    try:
        with pytest.raises(ArchiveRejected, match="header"):
            asafe.extract_tar_path(arc, tmp_path / "dest", limits=_BIG)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"read {peak} bytes of a header into memory"
    assert not (tmp_path / "dest").exists() or not any((tmp_path / "dest").iterdir())


def test_the_tarfile_hooks_the_header_guard_relies_on_exist():
    # _GuardedTarInfo overrides tarfile internals; a Python that renames them must fail
    # here, loudly, rather than quietly dropping the header caps.
    for name in ("_proc_member", "_proc_gnusparse_00", "_proc_gnusparse_01", "_proc_gnusparse_10"):
        assert callable(getattr(tarfile.TarInfo, name, None)), name
    assert issubclass(asafe._GuardedTarInfo, tarfile.TarInfo)


def test_sparse_members_are_refused(tmp_path):
    info = tarfile.TarInfo("holes.bin")
    info.type = tarfile.GNUTYPE_SPARSE
    raw = io.BytesIO(info.tobuf(format=tarfile.GNU_FORMAT) + b"\0" * 1024)
    arc = tmp_path / "gnu-sparse.tar"
    arc.write_bytes(raw.getvalue())
    with pytest.raises(ArchiveRejected, match="sparse"):
        asafe.extract_tar_path(arc, tmp_path / "dest", limits=_BIG)

    pax = io.BytesIO()
    with tarfile.open(fileobj=pax, mode="w", format=tarfile.PAX_FORMAT) as tar:
        tar.addfile(tarfile.TarInfo("first.txt"), io.BytesIO(b""))
        sparse = tarfile.TarInfo("ok.txt")
        sparse.size = 1
        sparse.pax_headers = {"GNU.sparse.major": "1", "GNU.sparse.minor": "0",
                              "GNU.sparse.name": "holes.bin", "GNU.sparse.realsize": "10"}
        tar.addfile(sparse, io.BytesIO(b"1"))
    arc2 = tmp_path / "pax-sparse.tar"
    arc2.write_bytes(pax.getvalue())
    with pytest.raises(ArchiveRejected, match="sparse"):
        asafe.extract_tar_path(arc2, tmp_path / "dest2", limits=_BIG)


@pytest.mark.parametrize("damage", ["not-a-tar", "truncated", "bad-crc"])
def test_a_corrupt_archive_is_rejected_not_crashed_on(tmp_path, damage):
    import gzip
    good = io.BytesIO()
    with tarfile.open(fileobj=good, mode="w:gz") as tar:
        for i in range(3):
            data = os.urandom(20_000)
            info = tarfile.TarInfo(f"f{i}.bin")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    raw = good.getvalue()
    if damage == "not-a-tar":
        raw = gzip.compress(b"this is not a tar archive" * 100)
    elif damage == "truncated":
        raw = raw[: len(raw) // 2]
    else:  # flip the gzip trailer's CRC32: only a read to the end of the stream sees it
        raw = raw[:-8] + bytes([raw[-8] ^ 0xFF]) + raw[-7:]
    arc = tmp_path / "damaged.tar.gz"
    arc.write_bytes(raw)
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveRejected, match="corrupt") as exc:
        asafe.extract_tar_path(arc, dest, limits=_BIG)
    assert exc.value.partial is False
    assert not dest.exists() or not any(dest.iterdir())


def _three_member_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name in ("a.txt", "b.txt", "c.txt"):
            info = tarfile.TarInfo(name)
            info.size = len(name)
            tar.addfile(info, io.BytesIO(name.encode()))
    return buf.getvalue()


def test_a_corrupt_header_part_way_through_is_refused_not_taken_as_the_end(tmp_path):
    # tarfile's default treats a bad header after the first as the end of the archive:
    # a.txt would extract, b.txt and c.txt would silently not exist.
    raw = bytearray(_three_member_tar())
    raw[2 * 512 + 148] ^= 0xFF                 # b.txt's header checksum (a.txt: header + data)
    dest = tmp_path / "dest"
    with tarfile.open(fileobj=io.BytesIO(bytes(raw)), mode="r") as tar, \
            pytest.raises(ArchiveRejected, match="corrupt"):
        asafe.extract_tar(tar, dest, limits=_BIG)
    assert not (dest / "a.txt").exists()


def test_data_after_the_end_of_archive_marker_is_refused(tmp_path):
    raw = _three_member_tar() + b"appended after the end-of-archive marker"
    dest = tmp_path / "dest"
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar, \
            pytest.raises(ArchiveRejected, match="corrupt"):
        asafe.extract_tar(tar, dest, limits=_BIG)
    assert not dest.exists() or not any(dest.iterdir())


def test_ordinary_long_names_in_pax_and_gnu_headers_still_extract(tmp_path):
    # Header payloads a real archive carries (a long or non-ASCII name) are nowhere near
    # the cap; main-era backups are PAX, current ones GNU.
    long_name = "media/" + "ț" * 60 + "/" + "a" * 120 + ".txt"   # every part under NAME_MAX
    for fmt in (tarfile.PAX_FORMAT, tarfile.GNU_FORMAT):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=fmt) as tar:
            info = tarfile.TarInfo(long_name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"ok"))
        arc = tmp_path / f"long-{fmt}.tar"
        arc.write_bytes(buf.getvalue())
        written = asafe.extract_tar_path(arc, tmp_path / f"dest-{fmt}", limits=_BIG)
        assert written == [tuple(long_name.split("/"))]


def test_header_payloads_are_capped_in_total_too(tmp_path, monkeypatch):
    monkeypatch.setattr(asafe, "_MAX_HEADER_TOTAL", 2048)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for i in range(6):
            info = tarfile.TarInfo(f"{i}/" + "/".join(["n" * 100] * 4))  # a ~420-byte PAX record
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    arc = tmp_path / "many-headers.tar"
    arc.write_bytes(buf.getvalue())
    with pytest.raises(ArchiveRejected, match="in total"):
        asafe.extract_tar_path(arc, tmp_path / "dest", limits=_BIG)


def test_a_member_name_the_destination_cannot_hold_is_a_refusal(tmp_path):
    with pytest.raises(ArchiveRejected, match="too long"):
        asafe.extract_tar(_tar([_file("ok.txt"), _file("n" * 300)]), tmp_path / "dest",
                          limits=_BIG)
    assert not (tmp_path / "dest" / "ok.txt").exists()


def test_a_non_zip_upload_is_rejected_not_crashed_on(tmp_path):
    with pytest.raises(ArchiveRejected, match="corrupt"):
        asafe.extract_zip_bytes(b"PK\x03\x04 not really a zip", tmp_path / "dest", limits=_BIG)


def test_extract_zip_bytes_reports_the_files_it_wrote_in_archive_order(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pkg\\SKILL.md", "# S\n")
        z.writestr("pkg/", "")
        z.writestr("pkg/main.py", "x = 1\n")
    names = asafe.extract_zip_bytes(buf.getvalue(), tmp_path / "dest", limits=_BIG)
    assert names == [("pkg", "SKILL.md"), ("pkg", "main.py")]


# ── consolidation: no second extractor ─────────────────────────────
# Modules that may import tarfile / zipfile at all. Every one except archive_safe only
# WRITES archives, and the scan below keeps it that way: an archive opened for reading,
# or any extract-family call, outside archive_safe fails this suite.
_ARCHIVE_IMPORTS_ALLOWED = {
    "agents/core/archive_safe.py",
    "agents/core/backup.py",                  # writes the backup tar
    "agents/core/skills/marketplace.py",      # writes the published skill zip
    "agents/core/routers/artifact_store.py",  # writes a download zip
    "agents/core/media_export.py",            # writes a media bundle zip
}
_ARCHIVE_MODULES = {"tarfile", "zipfile"}
_THIRD_PARTY_EXTRACTORS = {"py7zr", "rarfile", "patoolib", "libarchive", "pyunpack"}
_ALWAYS_EXTRACTORS = {"extractall", "extractfile", "_extract_member", "_extract_one",
                      "unpack_archive"}
_ARCHIVE_OPENERS = {"tarfile.open", "TarFile.open", "tarfile.TarFile", "tarfile.TarFile.open",
                    "TarFile", "zipfile.ZipFile", "ZipFile", "zipfile.PyZipFile", "PyZipFile"}
_WRITE_MODES = ("w", "x", "a")


def _call_name(func) -> str:
    """Dotted name of a call target: ``tarfile.open``, ``ZipFile``, ``tar.extract``."""
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def _opens_for_reading(call: ast.Call) -> bool:
    """A ``tarfile.open`` / ``ZipFile`` call whose mode is not provably a write mode."""
    if _call_name(call.func) not in _ARCHIVE_OPENERS:
        return False
    mode = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if mode is None and len(call.args) > 1:
        mode = call.args[1]
    if mode is None:
        return True  # both default to reading
    return not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)
                and mode.value.startswith(_WRITE_MODES))


def _archive_offenders(rel: str, source: str) -> list[str]:
    """Every way *source* could unpack an archive without going through archive_safe."""
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            if node.module.endswith("archive_safe") or any(
                    alias.name == "archive_safe" for alias in node.names):
                imported.add("archive_safe")
    # ``.extract(`` is a common method name (knowledge.extract, re matches); it only
    # counts in a module that handles archives at all.
    handles_archives = bool(imported & (_ARCHIVE_MODULES | {"archive_safe"}))
    out = []
    if imported & _ARCHIVE_MODULES and rel not in _ARCHIVE_IMPORTS_ALLOWED:
        out.append(f"{rel}: imports {sorted(imported & _ARCHIVE_MODULES)} (go through archive_safe)")
    for mod in sorted(imported & _THIRD_PARTY_EXTRACTORS):
        out.append(f"{rel}: imports the third-party extractor {mod}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        last = name.rsplit(".", 1)[-1]
        if last in _ALWAYS_EXTRACTORS or (last == "extract" and handles_archives):
            out.append(f"{rel}:{node.lineno}: {name}(...)")
        elif _opens_for_reading(node):
            out.append(f"{rel}:{node.lineno}: {name}(...) opens an archive for reading")
    return out


_PRODUCT_ROOTS = ("agents", "scripts", "skills", "services", "worldview")
_VENDORED = {"node_modules", ".venv", "venv", "site-packages", "__pycache__"}


def _product_python():
    yield from sorted(repo_root.glob("*.py"))
    for top in _PRODUCT_ROOTS:
        for path in sorted((repo_root / top).rglob("*.py")):
            if _VENDORED.isdisjoint(path.relative_to(repo_root).parts):
                yield path


@pytest.mark.parametrize("probe", [
    "import tarfile\ndef f(tar, m, d):\n    tar.extract(m, d)\n",
    "import zipfile\ndef f(zf, n, d):\n    zf.extract(n, d)\n",
    "from agents.core import archive_safe\ndef f(t, m, d):\n    t.extract(m, d)\n",
    "import zipfile, io\ndef f(b, p):\n    with zipfile.ZipFile(io.BytesIO(b)) as z:\n"
    "        open(p, 'wb').write(z.read('x'))\n",
    "import tarfile\ndef f(p):\n    return tarfile.open(p, 'r:gz')\n",
    "import shutil\ndef f(a, d):\n    shutil.unpack_archive(a, d)\n",
    "import py7zr\n",
])
def test_the_extractor_guard_catches_every_unpacking_shape(probe):
    assert _archive_offenders("agents/core/probe.py", probe), probe


def test_the_extractor_guard_leaves_writers_and_unrelated_extract_alone():
    writer = ("import zipfile, tarfile, io\n"
              "def f(b, fo):\n"
              "    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('a', 'b')\n"
              "    with tarfile.open(fileobj=fo, mode='w:gz') as t: pass\n")
    assert _archive_offenders("agents/core/backup.py", writer) == []
    unrelated = "def f(self):\n    self.knowledge.extract(self.messages)\n"
    assert _archive_offenders("agents/core/ingestion/pipeline.py", unrelated) == []


def test_archive_safe_is_the_only_extractor_in_the_product():
    """A second transfer surface with its own extractor is how a weaker one ships."""
    offenders = []
    for path in _product_python():
        rel = path.relative_to(repo_root).as_posix()
        if rel == "agents/core/archive_safe.py" or rel.startswith("agents/web/v2/"):
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            offenders.extend(_archive_offenders(rel, source))
        except SyntaxError:
            continue  # not Python this interpreter parses (a template); nothing to run
    assert offenders == [], "archive extraction outside agents/core/archive_safe.py:\n" + "\n".join(offenders)


# ── lot-1 verification: names the filesystem refuses, repeats a caller owns ──
def _tar_file(path: Path, members) -> Path:
    with tarfile.open(path, "w") as tar:
        for info, data in members:
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_an_over_long_component_deep_in_a_new_tree_is_refused_before_writing(tmp_path):
    # The existing-path walk stops at the first missing directory, so a component too
    # long for the filesystem under a NEW directory used to fail at write time — after
    # the members before it had landed, as a bare OSError.
    dest = tmp_path / "dest"
    members = [_file("ok.txt", b"ok"), _file("newdir/" + "n" * 300 + "/f.txt", b"f")]
    with pytest.raises(ArchiveRejected, match="too long") as exc:
        asafe.extract_tar(_tar(members), dest, limits=_BIG)
    assert exc.value.partial is False
    assert not dest.exists() or not any(dest.iterdir())


def test_a_write_the_destination_refuses_is_a_named_partial_refusal(tmp_path, monkeypatch):
    real = asafe._write_capped

    def _denied(src, target, written, budget, name):
        if name == "b.txt":
            raise PermissionError(13, "Permission denied")
        return real(src, target, written, budget, name)

    monkeypatch.setattr(asafe, "_write_capped", _denied)
    with pytest.raises(ArchiveRejected, match="could not write") as exc:
        asafe.extract_tar(_tar([_file("a.txt", b"a"), _file("b.txt", b"b")]),
                          tmp_path / "dest", limits=_BIG)
    assert exc.value.partial is True                    # a.txt was already written


def test_a_repeated_member_the_caller_owns_is_written_once_last_wins(tmp_path):
    arc = _tar_file(tmp_path / "a.tar", [_file("m.json", b"old"), _file("a.txt", b"a"),
                                         _file("m.json", b"new")])
    stale: list = []
    written = asafe.extract_tar_path(arc, tmp_path / "dest", limits=_BIG,
                                     last_wins=("m.json",), superseded=stale)
    assert written == [("a.txt",), ("m.json",)]
    assert stale == [("m.json",)]
    assert (tmp_path / "dest" / "m.json").read_bytes() == b"new"


@pytest.mark.parametrize("members", [
    [("a.txt", b"1"), ("a.txt", b"2")],                  # a repeat nobody owns
    [("x/m.json", b"1"), ("x/m.json", b"2")],            # the owned name, but not top-level
])
def test_last_wins_never_lets_any_other_repeat_through(tmp_path, members):
    arc = _tar_file(tmp_path / "a.tar", [_file(name, data) for name, data in members])
    with pytest.raises(ArchiveRejected, match="duplicate"):
        asafe.extract_tar_path(arc, tmp_path / "dest", limits=_BIG, last_wins=("m.json",))
    assert not (tmp_path / "dest").exists() or not any((tmp_path / "dest").iterdir())
