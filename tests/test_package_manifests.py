"""Release channels — the two ways a package manager ships a broken install.

`brew install nerva` is a different product from "clone the repo and read
INSTALL.md", and it is the same build either way. What makes it dangerous is that
a mistake here is discovered on a *stranger's machine*, at install time, by
someone who has no idea what went wrong. So each test is one such mistake:

  · a placeholder or stale sha256 renders as a perfectly valid manifest and fails
    on download — so a missing checksum is a REFUSAL here, never an empty string;
  · a prerelease promoted to `stable` because a version regex was loose is how a
    knowingly-unfinished build reaches everyone who typed `brew upgrade`;
  · a version that is not a version, coerced rather than refused, produces a
    manifest pointing at a URL that does not exist;
  · one component deciding "prerelease" differently from another is how a tag
    lands in both channels, or neither.

Hermetic: a tmp_path dist directory. No network, no manager, no release.
"""

from __future__ import annotations

import json

import pytest

from scripts.gen_package_manifests import (
    LATEST,
    STABLE,
    WINGET_ID,
    WINGET_SCHEMA,
    ManifestError,
    channel_for,
    parse_version,
    read_checksums,
    render_cask,
    render_winget,
    write_manifests,
)

TAR = "a" * 64
ZIP = "b" * 64


@pytest.fixture
def dist(tmp_path):
    """A built release, as scripts/build_release.sh leaves it."""
    (tmp_path / "SHA256SUMS").write_text(
        f"{TAR}  jarvis-1.1.0.tar.gz\n"
        f"{ZIP}  jarvis-1.1.0.zip\n"
        f"{'c' * 64}  SBOM.json\n"
        f"{'d' * 64}  NOTICE\n",
        encoding="utf-8",
    )
    return tmp_path


# ── the checksum comes from the build ────────────────────────────────────────

def test_the_cask_carries_the_checksum_the_build_actually_produced():
    """A placeholder renders as a valid manifest and fails on a user's machine
    with "checksum mismatch" — the worst place to find a release-tooling bug."""
    cask = render_cask(version="1.1.0", repo="o/r", sha256=TAR, filename="jarvis-1.1.0.tar.gz")
    assert f'sha256 "{TAR}"' in cask
    assert "PLACEHOLDER" not in cask.upper()


def test_a_missing_checksum_is_a_refusal_not_an_empty_string(tmp_path):
    (tmp_path / "SHA256SUMS").write_text(f"{TAR}  something-else.tar.gz\n", encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        write_manifests(dist=tmp_path, version="1.1.0", repo="o/r", out=tmp_path / "out")
    assert exc.value.reason == "checksum_not_found"


def test_a_missing_checksums_file_is_a_refusal(tmp_path):
    with pytest.raises(ManifestError) as exc:
        read_checksums(tmp_path / "nope")
    assert exc.value.reason == "checksums_missing"


def test_a_checksums_file_with_no_hashes_is_a_refusal(tmp_path):
    """An empty parse and a file full of unparseable lines look the same to a
    caller that only checks for an exception on the open()."""
    (tmp_path / "SHA256SUMS").write_text("this is not a checksum file\n", encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        read_checksums(tmp_path / "SHA256SUMS")
    assert exc.value.reason == "checksums_empty"


def test_both_sha256sum_and_bsd_shasum_output_parse(tmp_path):
    """The build script picks whichever the runner has; a parser that knew only
    one would silently return nothing on the other."""
    (tmp_path / "SHA256SUMS").write_text(
        f"{TAR}  plain.tar.gz\n{ZIP} *binary.zip\n", encoding="utf-8"
    )
    sums = read_checksums(tmp_path / "SHA256SUMS")
    assert sums == {"plain.tar.gz": TAR, "binary.zip": ZIP}


def test_a_truncated_hash_is_not_treated_as_a_hash(tmp_path):
    (tmp_path / "SHA256SUMS").write_text("abc123  short.tar.gz\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        read_checksums(tmp_path / "SHA256SUMS")


# ── a prerelease never becomes stable ────────────────────────────────────────

@pytest.mark.parametrize("version", ["1.1.0", "v1.1.0", "2.0.0", "0.1.0"])
def test_a_plain_release_is_stable(version):
    assert channel_for(version) == STABLE


@pytest.mark.parametrize(
    "version",
    ["1.1.0-rc1", "v1.1.0-rc.1", "2.0.0-beta.1", "1.0.0-alpha", "1.0.0-0"],
)
def test_a_prerelease_is_never_promoted_to_stable(version):
    """Promoting an rc because a regex was loose is how a knowingly-unfinished
    build reaches everyone who typed `brew upgrade`."""
    assert channel_for(version) == LATEST


def test_the_channel_and_the_manifest_agree_about_prerelease(dist, tmp_path):
    """One component deciding "prerelease" differently from another is how a tag
    lands in both channels, or in neither."""
    (dist / "SHA256SUMS").write_text(
        f"{TAR}  jarvis-1.1.0-rc1.tar.gz\n{ZIP}  jarvis-1.1.0-rc1.zip\n", encoding="utf-8"
    )
    summary = write_manifests(
        dist=dist, version="v1.1.0-rc1", repo="o/r", out=tmp_path / "out"
    )
    assert summary["channel"] == LATEST
    assert summary["prerelease"] is True
    assert summary["version"] == "1.1.0-rc1"


# ── a version that is not a version ──────────────────────────────────────────

@pytest.mark.parametrize(
    "bad", ["1.1", "1.1.0.0", "", "latest", "v", "1.1.0-", "one.two.three", "1.1.0rc1"]
)
def test_a_malformed_version_is_refused_not_coerced(bad):
    """A guess produces a manifest pointing at a URL that does not exist."""
    with pytest.raises(ManifestError) as exc:
        parse_version(bad)
    assert exc.value.reason == "invalid_version"


def test_a_leading_v_is_accepted_because_that_is_how_tags_are_written():
    assert parse_version("v1.1.0") == ("1.1.0", "")


@pytest.mark.parametrize("padded", ["1.1.0 ", " v1.1.0", "\n1.1.0\n"])
def test_surrounding_whitespace_is_tolerated_not_treated_as_a_new_version(padded):
    """The version arrives from a shell variable that can carry a newline.
    Trimming that is tolerance; it does not change WHICH version is meant, which
    is what the refusals above are actually guarding."""
    assert parse_version(padded) == ("1.1.0", "")


# ── the manifests say what a manager will read ───────────────────────────────

def test_the_cask_points_at_the_release_asset_for_its_own_version():
    cask = render_cask(version="1.1.0", repo="o/r", sha256=TAR, filename="jarvis-1.1.0.tar.gz")
    assert "https://github.com/o/r/releases/download/v1.1.0/jarvis-1.1.0.tar.gz" in cask
    assert 'version "1.1.0"' in cask


def test_the_cask_is_stage_only_because_nerva_runs_from_source():
    """A formula would need a build phase there is nothing for; pretending
    otherwise produces one that fails Homebrew's audit."""
    cask = render_cask(version="1.1.0", repo="o/r", sha256=TAR, filename="x.tar.gz")
    assert "stage_only true" in cask
    assert "./install.sh" in cask


def test_the_cask_tells_the_user_it_binds_to_loopback():
    cask = render_cask(version="1.1.0", repo="o/r", sha256=TAR, filename="x.tar.gz")
    assert "127.0.0.1" in cask


def test_the_winget_manifest_has_all_three_documents():
    docs = render_winget(version="1.1.0", repo="o/r", sha256=ZIP, filename="x.zip")
    assert set(docs) == {"installer", "locale.en-US", "version"}
    assert {d["ManifestType"] for d in docs.values()} == {
        "installer", "defaultLocale", "version"
    }


def test_every_winget_document_agrees_on_the_identifier_and_version():
    """Three documents that disagree are rejected on submission, which is a
    slower and more confusing failure than one caught here."""
    docs = render_winget(version="1.1.0", repo="o/r", sha256=ZIP, filename="x.zip")
    assert {d["PackageIdentifier"] for d in docs.values()} == {WINGET_ID}
    assert {d["PackageVersion"] for d in docs.values()} == {"1.1.0"}
    assert {d["ManifestVersion"] for d in docs.values()} == {WINGET_SCHEMA}


def test_the_winget_installer_carries_an_uppercase_sha256():
    """winget's schema requires uppercase; a lowercase digest fails validation on
    submission rather than at generation time."""
    docs = render_winget(version="1.1.0", repo="o/r", sha256=ZIP, filename="x.zip")
    assert docs["installer"]["Installers"][0]["InstallerSha256"] == ZIP.upper()


def test_the_schema_version_is_pinned_not_latest():
    """A manifest written against a schema nobody has published is rejected on
    submission — a slower failure than a refusal here."""
    assert WINGET_SCHEMA.count(".") == 2


# ── what a run writes ────────────────────────────────────────────────────────

def test_a_full_generation_writes_every_file(dist, tmp_path):
    out = tmp_path / "out"
    summary = write_manifests(dist=dist, version="1.1.0", repo="o/r", out=out)
    for name in summary["files"]:
        assert (out / name).is_file()
    assert (out / "channel.json").is_file()


def test_the_channel_file_records_the_checksums_that_were_used(dist, tmp_path):
    out = tmp_path / "out"
    write_manifests(dist=dist, version="1.1.0", repo="o/r", out=out)
    recorded = json.loads((out / "channel.json").read_text())
    assert recorded["cask_sha256"] == TAR
    assert recorded["winget_sha256"] == ZIP.upper()
    assert recorded["channel"] == STABLE


def test_the_written_yaml_is_readable_back(dist, tmp_path):
    """The writer is hand-rolled — the release step runs before any project
    dependency is installed — so what it emits has to be checked, not assumed."""
    out = tmp_path / "out"
    write_manifests(dist=dist, version="1.1.0", repo="o/r", out=out)
    text = (out / f"{WINGET_ID}.installer.yaml").read_text(encoding="utf-8")
    assert f"PackageIdentifier: {WINGET_ID}" in text
    assert "InstallerType: zip" in text
    assert ZIP.upper() in text
    assert "Installers:" in text
    assert "- Architecture: x64" in text


def test_a_value_with_a_colon_is_quoted(dist, tmp_path):
    """An unquoted URL would parse as a nested mapping and the manifest would be
    silently wrong rather than rejected."""
    out = tmp_path / "out"
    write_manifests(dist=dist, version="1.1.0", repo="o/r", out=out)
    text = (out / f"{WINGET_ID}.installer.yaml").read_text(encoding="utf-8")
    assert '"https://github.com/o/r/releases/download/v1.1.0/jarvis-1.1.0.zip"' in text


def test_nothing_is_written_when_a_checksum_is_missing(tmp_path):
    """A partial write leaves a directory that looks like a successful run."""
    (tmp_path / "SHA256SUMS").write_text(f"{TAR}  jarvis-1.1.0.tar.gz\n", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(ManifestError):
        write_manifests(dist=tmp_path, version="1.1.0", repo="o/r", out=out)
    assert not (out / "channel.json").exists()


# ── the CLI ──────────────────────────────────────────────────────────────────

def test_the_cli_exits_non_zero_on_a_refusal(tmp_path, capsys):
    from scripts.gen_package_manifests import main

    code = main(["--dist", str(tmp_path), "--version", "1.1.0", "--out", str(tmp_path / "o")])
    assert code == 1
    assert "checksums_missing" in capsys.readouterr().err


def test_the_cli_prints_the_summary_on_success(dist, tmp_path, capsys):
    from scripts.gen_package_manifests import main

    code = main(
        ["--dist", str(dist), "--version", "v1.1.0", "--repo", "o/r",
         "--out", str(tmp_path / "o")]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["channel"] == STABLE


# ── the release workflow, and the Dockerfile it publishes ────────────────────

def _workflow():
    from pathlib import Path as _P

    import yaml

    repo = _P(__file__).resolve().parent.parent
    return yaml.safe_load((repo / ".github/workflows/release.yml").read_text(encoding="utf-8"))


def _dockerfile() -> str:
    from pathlib import Path as _P

    repo = _P(__file__).resolve().parent.parent
    return (repo / "Dockerfile").read_text(encoding="utf-8")


def test_the_channel_is_decided_once_and_passed_downstream():
    """Two jobs each working out whether a tag is a prerelease is how one lands
    in both channels, or in neither — the same failure the generator guards."""
    wf = _workflow()
    assert set(wf["jobs"]["release"]["outputs"]) == {"channel", "version"}
    image_steps = wf["jobs"]["image"]["steps"]
    tags = next(s for s in image_steps if s.get("name") == "Build and push")["with"]["tags"]
    assert "needs.release.outputs.channel" in tags
    assert "needs.release.outputs.version" in tags
    # and nothing in the image job recomputes it
    assert not any("channel_for" in str(step) for step in image_steps)


def test_the_manifests_are_attached_to_the_release():
    """A manifest that exists only in a CI log is a manifest nobody can install
    from."""
    wf = _workflow()
    step = next(
        s for s in wf["jobs"]["release"]["steps"] if s.get("name") == "Create GitHub Release"
    )
    assert "dist/packaging/*" in step["with"]["files"]


def test_the_image_only_publishes_for_a_real_tag_push():
    """A workflow_dispatch dry run must not push an image; "dry run" that pushed
    to a registry would be a dry run in name only."""
    wf = _workflow()
    assert wf["jobs"]["image"]["if"] == "github.event_name == 'push'"


def test_the_image_job_waits_for_the_release_to_build():
    wf = _workflow()
    assert wf["jobs"]["image"]["needs"] == "release"


def test_the_image_binds_loopback_by_default():
    """An image that bound 0.0.0.0 would put a personal AI on whatever network
    the container joined — the exact thing the bind guard exists to prevent."""
    assert "JARVIS_HOST=127.0.0.1" in _dockerfile()


def test_the_image_never_publishes_a_port_itself():
    """Publishing one would reach past the loopback bind; the compose file uses
    host networking on purpose."""
    assert "EXPOSE" not in _dockerfile()


def test_the_image_installs_from_the_hash_pinned_lockfile():
    """An image built today and one built next year must contain the same code."""
    assert "--require-hashes -r requirements-beta.lock" in _dockerfile()


def test_the_data_root_is_a_volume_not_a_layer():
    """Personal state baked into an image is personal state pushed to a registry."""
    docker = _dockerfile()
    assert 'VOLUME ["/data"]' in docker
    assert "JARVIS_HOME=/data" in docker


def test_no_credential_is_a_build_argument():
    """A secret in a build argument is a secret in the image history.

    Checked against the INSTRUCTIONS only — the comments deliberately discuss
    ARGs and secrets, and a test that matched those would be a test of the prose
    rather than of the image.
    """
    instructions = "\n".join(
        line for line in _dockerfile().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ).upper()
    assert "ARG " not in instructions
    for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"):
        assert word not in instructions
