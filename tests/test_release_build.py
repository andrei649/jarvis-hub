"""H23.13 — release-artifact build is correct, reproducible, and leak-free.

Exercises scripts/build_release.sh + scripts/gen_sbom.py against the real repo
(no network, no external tools beyond git/tar/sha256sum/python).
"""

import hashlib
import importlib.util
import json
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _version() -> str:
    txt = (REPO / "agents" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', txt).group(1)


def _load_gen_sbom():
    spec = importlib.util.spec_from_file_location("gen_sbom", REPO / "scripts" / "gen_sbom.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_release_produces_complete_bundle(tmp_path):
    out = tmp_path / "dist"
    subprocess.run(["bash", "scripts/build_release.sh", str(out)], cwd=REPO, check=True)
    ver = _version()

    tar = out / f"jarvis-{ver}.tar.gz"
    zipf = out / f"jarvis-{ver}.zip"
    sbom = out / "SBOM.json"
    notice = out / "NOTICE"
    sums = out / "SHA256SUMS"
    for p in (tar, zipf, sbom, notice, sums):
        assert p.exists(), f"missing artifact: {p.name}"

    # Every checksum in SHA256SUMS matches the actual file (integrity contract).
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split()
        actual = hashlib.sha256((out / name).read_bytes()).hexdigest()
        assert actual == digest, f"checksum mismatch for {name}"

    # Tarball is single-prefixed and carries real source.
    with tarfile.open(tar) as tf:
        names = tf.getnames()
    rel = [n[len(f"jarvis-{ver}/") :] for n in names if n.startswith(f"jarvis-{ver}/")]
    assert "agents/web.py" in rel
    # ...and never leaks secrets / runtime data / build junk.
    assert ".env" not in rel  # the real secret file (.env.example is fine)
    leaked = [
        s
        for s in rel
        if s.startswith(("memory_logs/", "agents/data/", ".venv/", "backups/"))
        or "node_modules/" in s
        or s.endswith(".db")
    ]
    assert not leaked, f"forbidden paths leaked into bundle: {leaked[:5]}"

    # Zip is a valid archive.
    with zipfile.ZipFile(zipf) as zf:
        assert zf.testzip() is None

    # SBOM is valid CycloneDX carrying this version + components with purls.
    doc = json.loads(sbom.read_text())
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["metadata"]["component"]["version"] == ver
    assert doc["components"], "SBOM has no components"
    assert all(c.get("purl") for c in doc["components"])
    assert notice.read_text().strip()


def test_gen_sbom_parses_requirements_deterministically():
    mod = _load_gen_sbom()
    comps = mod.parse_requirements(
        "# comment line\n"
        "fastapi==0.110.0\n"
        "httpx>=0.27\n"
        "-r other.txt\n"
        "--hash=sha256:abc\n"
        "\n"
        "uvicorn[standard]==0.29.0 ; python_version>='3.12'\n"
    )
    names = [n for n, _ in comps]
    assert names == sorted(names)  # deterministic ordering
    d = dict(comps)
    assert set(d) == {"fastapi", "httpx", "uvicorn"}
    assert d["fastapi"] == "0.110.0"
    assert d["uvicorn"] == "0.29.0"  # extras + env marker stripped

    sbom = mod.build_sbom(comps, "1.2.3")
    assert sbom["specVersion"] == "1.5"
    assert sbom["components"][0]["purl"].startswith("pkg:pypi/")
    assert "1.2.3" in mod.build_notice(comps, "1.2.3")
