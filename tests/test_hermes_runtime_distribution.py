import hashlib
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path

import pytest

from agents.core.hermes_runtime import distribution
from scripts import hermes_runtime


def _archive(path: Path, entries: dict[str, bytes], *, symlink: str | None = None) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(f"hermes-agent-test/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if symlink:
            info = tarfile.TarInfo(f"hermes-agent-test/{symlink}")
            info.type = tarfile.SYMTYPE
            info.linkname = "../../escape"
            tar.addfile(info)


def test_pin_is_fixed_complete_donor() -> None:
    pin = distribution.load_pin()
    assert pin["commit"] == "0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7"
    assert len(pin["archive_sha256"]) == 64
    assert len(pin["source_sha256"]) == 64
    assert len(pin["tree_sha1"]) == 40
    assert pin["license"] == "MIT"


def test_verify_source_rejects_changed_bytes_and_extra_python(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "LICENSE").write_text("test license")
    tree = distribution._git_tree_sha1(source)
    sha256 = distribution._source_sha256(source)
    monkeypatch.setattr(distribution, "load_pin", lambda: {"tree_sha1": tree, "source_sha256": sha256, "commit": "test"})
    assert distribution.verify_source(source)["tree_sha1"] == tree
    (source / "LICENSE").write_text("changed")
    with pytest.raises(ValueError, match="identity"):
        distribution.verify_source(source)
    (source / "LICENSE").write_text("test license")
    (source / "shadow.py").write_text("print('hi')")
    with pytest.raises(ValueError, match="identity"):
        distribution.verify_source(source)


def test_sha256_source_identity_rejects_mutation_when_git_id_matches(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("safe")
    tree = distribution._git_tree_sha1(source)
    digest = distribution._source_sha256(source)
    monkeypatch.setattr(distribution, "load_pin", lambda: {"tree_sha1": tree, "source_sha256": digest, "commit": "test"})
    monkeypatch.setattr(distribution, "_git_tree_sha1", lambda path: tree)
    (source / "main.py").write_text("unsafe")
    with pytest.raises(ValueError, match="identity"):
        distribution.verify_source(source)


def test_source_rejects_added_git_hooks(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("safe")
    tree = distribution._git_tree_sha1(source)
    digest = distribution._source_sha256(source)
    monkeypatch.setattr(distribution, "load_pin", lambda: {"tree_sha1": tree, "source_sha256": digest, "commit": "test"})
    (source / ".git" / "hooks").mkdir(parents=True)
    (source / ".git" / "hooks" / "pre-commit").write_text("echo hijack")
    with pytest.raises(ValueError, match="Git metadata"):
        distribution.verify_source(source)


def test_archive_rejects_path_escape_and_symlink(tmp_path) -> None:
    archive = tmp_path / "bad.tar.gz"
    _archive(archive, {"../escape": b"bad"})
    with pytest.raises(ValueError, match="archive"):
        distribution._extract_archive(archive, tmp_path / "out", "hermes-agent-test")
    _archive(archive, {"LICENSE": b"MIT"}, symlink="link")
    with pytest.raises(ValueError, match="archive"):
        distribution._extract_archive(archive, tmp_path / "out2", "hermes-agent-test")


def test_archive_hash_checked_before_extraction(tmp_path, monkeypatch) -> None:
    archive = tmp_path / "source.tar.gz"
    _archive(archive, {"LICENSE": b"MIT"})
    monkeypatch.setattr(distribution, "load_pin", lambda: {
        "archive_url": archive.as_uri(), "archive_sha256": "0" * 64,
        "archive_root": "hermes-agent-test", "tree_sha1": "0" * 40,
    })
    with pytest.raises(ValueError, match="archive hash"):
        distribution.prepare_source(tmp_path / "source")
    assert not (tmp_path / "source").exists()


def test_clean_environment_never_inherits_operator_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "operator-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "operator-secret")
    env = distribution.runtime_environment(tmp_path / "home")
    assert env["HERMES_HOME"] == str(tmp_path / "home")
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "PYTHONPATH" not in env


def test_pm_proxy_environment_excludes_embedded_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://user:password@proxy.example:8080")
    env = distribution.runtime_environment(tmp_path / "home", for_install=True)
    assert env["HTTPS_PROXY"] == "http://proxy.example:8080"
    assert "HTTP_PROXY" not in env
    assert "HTTPS_PROXY" not in distribution.runtime_environment(tmp_path / "home")


def test_pm_can_use_public_ca_bundle_without_inheriting_other_tls_settings(tmp_path, monkeypatch) -> None:
    certificate = tmp_path / "ca.pem"
    certificate.write_text("public certificate")
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    monkeypatch.setenv("SSL_KEY_FILE", "secret-key")
    env = distribution.runtime_environment(tmp_path / "home", for_install=True)
    assert env["SSL_CERT_FILE"] == str(certificate)
    assert "SSL_KEY_FILE" not in env


def test_selected_python_must_be_managed_314(tmp_path) -> None:
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir()
    home.mkdir()
    outsider = tmp_path / "python"
    outsider.write_text("fake")
    with pytest.raises(ValueError, match="managed"):
        distribution.validate_python(outsider, source, home)


def test_selected_python_rejects_other_managed_generation(tmp_path) -> None:
    source, home = tmp_path / "source", tmp_path / "home"
    source.mkdir()
    key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16]
    install = home / "installs" / key
    venv = install / "environments" / "other" / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = test")
    (venv / "bin/python").write_text("fake")
    (install / "facts.json").write_text(json.dumps({"packages": {"venv": {"environment": str(install / "environments/selected/venv")}}}))
    with pytest.raises(ValueError, match="selected PM environment"):
        distribution.validate_python(venv / "bin/python", source, home)


def test_selected_python_rejects_unsupported_interpreter(tmp_path) -> None:
    source, home = tmp_path / "source", tmp_path / "home"
    source.mkdir()
    key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:16]
    install = home / "installs" / key
    venv = install / "environments" / "selected" / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = test")
    tools = home / "tools"
    tools.mkdir(parents=True)
    shutil.copy2(sys.executable, tools / "python")
    (venv / "bin/python").symlink_to(tools / "python")
    (install / "facts.json").write_text(json.dumps({"packages": {"venv": {"environment": str(venv)}}}))
    with pytest.raises(ValueError, match="Python 3.14"):
        distribution.validate_python(venv / "bin/python", source, home)


def test_cli_descriptor_is_private_and_names_fixed_layout(tmp_path) -> None:
    descriptor = hermes_runtime._write_descriptor(tmp_path, tmp_path / "source", tmp_path / "home", tmp_path / "home/python")
    content = json.loads(descriptor.read_text())
    assert content["source"] == str(tmp_path / "source")
    assert content["home"] == str(tmp_path / "home")
    assert content["python"] == str(tmp_path / "home/python")
    assert content["source_sha256"] == distribution.load_pin()["source_sha256"]
    assert descriptor.stat().st_mode & 0o777 == 0o600
