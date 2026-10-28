"""Native drive classification preserves scoped files and honest reader refusal."""
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agents.core import video_analysis as video
from agents.core.file_tools import FileScopeError
from agents.core.tool_rpc import ToolRPCValidationError


@pytest.fixture
def windows_host(monkeypatch):
    # Only the consumer's platform seam changes; the runner's OS stays intact.
    monkeypatch.setattr(video, "os", SimpleNamespace(name="nt"))


@pytest.mark.parametrize("source", [r"C:\clips\movie.mp4", "c:/clips/movie.mp4", r"D:\clips\space name.MP4"])
def test_native_absolute_drive_path_reaches_the_existing_scope(windows_host, source):
    resolved = PureWindowsPath(source)
    scope = SimpleNamespace(resolve=Mock(return_value=resolved))

    assert video._source(source, scope) == ("file", resolved, "video/mp4")
    scope.resolve.assert_called_once_with(source)


@pytest.mark.parametrize("source", ["C:movie.mp4", "c:../movie.mp4", "file:///C:/movie.mp4", "ftp://media.example/movie.mp4", "data:video/mp4;base64,eA=="])
def test_other_schemes_and_drive_relative_inputs_stay_refused(windows_host, source):
    scope = SimpleNamespace(resolve=Mock())

    with pytest.raises(ToolRPCValidationError, match="bad_video_url"):
        video._source(source, scope)
    scope.resolve.assert_not_called()


@pytest.mark.parametrize("source", [r"C:\clips\movie.mp4", "c:/clips/movie.mp4"])
def test_a_drive_from_another_platform_is_still_not_a_url(monkeypatch, source):
    monkeypatch.setattr(video, "os", SimpleNamespace(name="posix"))
    scope = SimpleNamespace(resolve=Mock())

    with pytest.raises(ToolRPCValidationError, match="bad_video_url"):
        video._source(source, scope)
    scope.resolve.assert_not_called()


def test_a_native_drive_path_cannot_bypass_a_scope_refusal(windows_host):
    scope = SimpleNamespace(resolve=Mock(side_effect=FileScopeError("outside_scope")))

    with pytest.raises(ToolRPCValidationError, match="outside_scope"):
        video._source(r"C:\outside\movie.mp4", scope)
    scope.resolve.assert_called_once_with(r"C:\outside\movie.mp4")


def test_native_windows_reader_still_refuses_before_any_filesystem_probe(windows_host):
    scope = SimpleNamespace(root_for=Mock())

    with pytest.raises(video.VideoPolicyRefused, match="require POSIX descriptors"):
        video._read_scoped(Path("movie.mp4"), scope)
    scope.root_for.assert_not_called()


def test_http_video_keeps_its_remote_classification(windows_host):
    scope = SimpleNamespace(resolve=Mock())
    source = "https://media.example/movie.mp4"

    assert video._source(source, scope) == ("url", source, "video/mp4")
    scope.resolve.assert_not_called()


def test_http_credentials_are_still_refused_on_windows(windows_host):
    scope = SimpleNamespace(resolve=Mock())

    with pytest.raises(ToolRPCValidationError, match="bad_video_url"):
        video._source("https://user:password@media.example/movie.mp4", scope)
    scope.resolve.assert_not_called()
