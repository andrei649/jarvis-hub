import copy
import hashlib
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import check_nerva_issue_movement as movement
from check_nerva_issue_movement import (
    LEGACY_BASE,
    MARKER,
    MAX_DIFF_BYTES,
    MovementError,
    PureProof,
    _fetch_current_snapshot,
    _git_environment,
    _resolve_git_executable,
    _validate_attestation,
    _validate_receipt,
    classify,
    compute_name_status_diff,
    derive_scope,
    main,
    parse_diff,
    parse_marker_json,
    run_pure_proof,
    run_repository_proof,
    strict_json,
    validate_manifest_gate,
    validate_registry_evolution,
    validate_stream_evidence_bindings,
)

BASE = "a" * 40
HEAD = "b" * 40
REPOSITORY = "andrei649/jarvis-hub"
PR_NUMBER = 849
REPO = Path(__file__).resolve().parent.parent
ACCEPTED_BOOTSTRAP_BASE = "e596920ec60f19d2e7f0937819c892746a1c42b2"


def _committed_blob(ref: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", f"{ref}:{path}"],
        cwd=REPO,
        check=True,
        capture_output=True,
    ).stdout


def binding_repository(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    for args in (
        ["init"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True)
    manifest = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"
    document = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_bytes(b'{"version":1}\n')
    document.write_bytes(b"# version 1\n")
    subprocess.run([git, "add", "docs"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    manifest.write_bytes(b'{"version":2}\n')
    document.write_bytes(b"# version 2\n")
    subprocess.run(
        [git, "commit", "-am", "candidate"], cwd=tmp_path, check=True, capture_output=True
    )
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": base, "ref": "main"},
            "head": {"sha": head, "ref": "nerva2/binding"},
            "body": "",
            "draft": False,
            "state": "open",
        },
    }
    return git, base, head, event


def grafted_unrelated_repository(tmp_path, *, linked_worktree):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    source_root = tmp_path / "source"
    source_root.mkdir()
    for args in (
        ["init"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run([git, *args], cwd=source_root, check=True, capture_output=True)

    manifest_bytes = json.dumps(candidate_manifest(), separators=(",", ":")).encode()
    for version in ("base", "head"):
        if version == "head":
            subprocess.run(
                [git, "checkout", "--orphan", "unrelated"],
                cwd=source_root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [git, "rm", "-rf", "."], cwd=source_root, check=True, capture_output=True
            )
        manifest = source_root / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"
        document = source_root / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_bytes(manifest_bytes)
        document.write_text("unchanged\n", encoding="utf-8")
        subprocess.run([git, "add", "docs"], cwd=source_root, check=True, capture_output=True)
        subprocess.run(
            [git, "commit", "-m", version], cwd=source_root, check=True, capture_output=True
        )
        commit = subprocess.run(
            [git, "rev-parse", "HEAD"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if version == "base":
            base = commit
        else:
            head = commit

    repository_root = source_root
    if linked_worktree:
        repository_root = tmp_path / "linked"
        subprocess.run(
            [git, "worktree", "add", "--detach", str(repository_root), head],
            cwd=source_root,
            check=True,
            capture_output=True,
        )
    common_dir = subprocess.run(
        [git, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    grafts = Path(common_dir) / "info/grafts"
    grafts.write_text(f"{head} {base}\n", encoding="ascii", newline="\n")
    return repository_root, base, head


def valid_gate():
    return {
        "schema_version": 1,
        "enforcement_state": "required",
        "bootstrap": {
            "source_sha": LEGACY_BASE,
            "accepted_base_sha": ACCEPTED_BOOTSTRAP_BASE,
            "legacy_manifest_sha256": (
                "ab63a42837fb69af901326ffae5052d01c787a913960e2fb6f3bebeaac10ec7f"
            ),
            "legacy_manifest_view_sha256": (
                "e4480f7c37de768ef59d64a542a2ec6c241b89d44ce89fa329a72ff987c1cfdc"
            ),
            "registry_seed_sha256": (
                "9ab8aadf4c986e6380e8421225e99de5afc585163366ebb53199eecdf58980fb"
            ),
        },
        "branch_prefix": "nerva2/",
        "attestation_start_marker": MARKER,
        "registry": [
            ".github/workflows/ci.yml",
            ".github/workflows/nerva-roadmap.yml",
            ".github/workflows/pr-auto-merge.yml",
            "BACKLOG.md",
            "GO_LIVE_PLAN.md",
            "NERVA.md",
            "README.md",
            "STATUS.md",
            "docs/nerva2/NERVA_ISSUE_MOVEMENT_V1.md",
            "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json",
            "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md",
            "docs/superpowers/plans/2026-08-07-b2-live-issue-ledger.md",
            "docs/superpowers/specs/2026-08-07-b2-live-issue-ledger-design.md",
            "project-status.json",
            "scripts/check_nerva_issue_movement.py",
            "scripts/check_nerva_program_manifest.py",
            "tests/test_nerva_issue_movement.py",
            "tests/test_nerva_program_manifest.py",
            "tests/test_pr_auto_merge_policy.py",
        ],
        "program_control_issues": [846],
        "receipt_control": {
            "mode": "point_in_time",
            "live_pr_reread_required": True,
            "fresh_exact_head_rerun_required": True,
            "fresh_owner_receipts_required": True,
            "continuous_currentness": False,
        },
        "manual_integration": {
            "issue": 847,
            "workflow_path": ".github/workflows/pr-auto-merge.yml",
            "policy_test_path": "tests/test_pr_auto_merge_policy.py",
        },
        "rollback": None,
    }


def candidate_manifest():
    return {"movement_gate": valid_gate()}


def prior_manifest():
    baseline = candidate_manifest()
    baseline["movement_gate"]["program_control_issues"] = []
    return baseline


def snapshot_proof(*, mutate_receipt=False):
    candidate = candidate_manifest()
    candidate_bytes = json.dumps(candidate, separators=(",", ":")).encode()
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    receipt_fields = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "pull_request": PR_NUMBER,
        "movement_kind": "program_control",
        "implementation_issue": 846,
        "base_sha": BASE,
        "head_sha": HEAD,
        "manifest_sha256": digest,
        "can_authorize": False,
        "can_execute": False,
        "completion_authority": False,
        "release_ready": False,
    }
    comments = {}
    roles = {}
    for role, issue, comment_id in (
        ("program", 757, 1),
        ("blocker", 778, 2),
        ("implementation", 846, 3),
    ):
        receipt = {**receipt_fields, "role": role, "issue": issue}
        body = (
            "<!-- NERVA2:MOVEMENT-RECEIPT:START -->"
            + json.dumps(receipt, separators=(",", ":"))
            + "<!-- NERVA2:MOVEMENT-RECEIPT:END -->"
        )
        roles[role] = {
            "comment_id": comment_id,
            "comment_body_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "updated_at": "2026-08-07T00:00:00Z",
        }
        comments[f"comment:{comment_id}"] = {
            "id": comment_id,
            "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{issue}",
            "body": body + ("x" if mutate_receipt and role == "program" else ""),
            "user": {"login": "andrei649"},
            "author_association": "OWNER",
            "created_at": "2026-08-07T00:00:00Z",
            "updated_at": "2026-08-07T00:00:00Z",
        }
    attestation = {
        "schema_version": 1,
        "movement_kind": "program_control",
        "repository": REPOSITORY,
        "pull_request": PR_NUMBER,
        "base_sha": BASE,
        "head_sha": HEAD,
        "manifest_sha256": digest,
        "program_issue": 757,
        "blocker_issue": 778,
        "implementation_issue": 846,
        "roles": roles,
        "can_authorize": False,
        "can_execute": False,
        "completion_authority": False,
        "release_ready": False,
    }
    body = (
        "<!-- NERVA2:MOVEMENT-ATTESTATION:START -->"
        + json.dumps(attestation, separators=(",", ":"))
        + "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
    )
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": BASE, "ref": "main"},
            "head": {"sha": HEAD, "ref": "nerva2/b2"},
            "body": body,
            "draft": False,
            "state": "open",
        },
    }
    current = json.loads(json.dumps(event["pull_request"]))
    current["base"]["repo"] = {"full_name": REPOSITORY}
    return event, candidate, candidate_bytes, {"pull_request": current, **comments}


class RestResponse:
    def __init__(
        self,
        payload,
        *,
        url,
        status=200,
        content_encoding=None,
        content_length=None,
    ):
        self.payload = payload
        self.url = url
        self.status = status
        self.headers = {}
        if content_encoding is not None:
            self.headers["Content-Encoding"] = content_encoding
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.read_sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.url

    def read(self, size):
        self.read_sizes.append(size)
        return self.payload[:size]


class RestOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_live_and_snapshot_modes_are_exclusive_and_live_reads_environment_token(
    tmp_path, monkeypatch
):
    event, _candidate, _candidate_bytes, _snapshot = snapshot_proof()
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    calls = []

    def live_transport(repository, number, *, environment):
        calls.append((repository, number, environment["GITHUB_TOKEN"]))
        return object()

    monkeypatch.setattr(movement, "_live_transport", live_transport, raising=False)
    monkeypatch.setattr(
        movement,
        "run_repository_proof",
        lambda **kwargs: PureProof("proved", {"transport": kwargs["transport"]}),
    )
    monkeypatch.setenv("GITHUB_TOKEN", "live-secret")

    assert (
        main(
            [
                "--event",
                str(event_path),
                "--base",
                BASE,
                "--head",
                HEAD,
                "--root",
                str(tmp_path),
                "--live",
            ]
        )
        == 0
    )
    assert calls == [(REPOSITORY, PR_NUMBER, "live-secret")]
    with pytest.raises(SystemExit):
        main(
            [
                "--event",
                str(event_path),
                "--base",
                BASE,
                "--head",
                HEAD,
                "--live",
                "--snapshot-dir",
                str(snapshot_dir),
            ]
        )


def test_snapshot_mode_never_reads_live_token_or_constructs_network_transport(
    tmp_path, monkeypatch
):
    event, _candidate, _candidate_bytes, _snapshot = snapshot_proof()
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    sentinel = object()
    monkeypatch.setattr(movement, "_snapshot_transport", lambda _path: sentinel)
    monkeypatch.setattr(
        movement,
        "_read_live_token",
        lambda *_args, **_kwargs: pytest.fail("snapshot mode read GITHUB_TOKEN"),
        raising=False,
    )
    monkeypatch.setattr(
        movement,
        "_live_transport",
        lambda *_args, **_kwargs: pytest.fail("snapshot mode opened network transport"),
        raising=False,
    )
    monkeypatch.setattr(
        movement,
        "run_repository_proof",
        lambda **kwargs: PureProof("proved", {"transport": kwargs["transport"]}),
    )

    assert (
        main(
            [
                "--event",
                str(event_path),
                "--base",
                BASE,
                "--head",
                HEAD,
                "--root",
                str(tmp_path),
                "--snapshot-dir",
                str(snapshot_dir),
            ]
        )
        == 0
    )


@pytest.mark.parametrize(
    ("event_mutation", "current_mutation"),
    [
        ({"body": "stale event body"}, {}),
        ({"draft": True}, {}),
        ({"state": "closed"}, {}),
        ({"base": {"sha": BASE, "ref": "stale-base-ref"}}, {}),
        ({"head": {"sha": HEAD, "ref": "nerva2/stale-event-ref"}}, {}),
    ],
)
def test_current_pr_is_fetched_first_and_must_exactly_match_event(event_mutation, current_mutation):
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    event["pull_request"].update(event_mutation)
    snapshot["pull_request"].update(current_mutation)
    calls = []

    def transport(key):
        calls.append(key)
        return snapshot[key]

    with pytest.raises(MovementError, match="current pull request does not bind event"):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=transport,
        )
    assert calls == ["pull_request"]


def test_nullable_empty_pr_bodies_are_normalized_before_exact_current_event_comparison():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    event["pull_request"]["head"]["ref"] = "feature/non-nerva"
    event["pull_request"]["body"] = None
    snapshot["pull_request"]["head"]["ref"] = "feature/non-nerva"
    snapshot["pull_request"]["body"] = None
    result = run_pure_proof(
        event=event,
        baseline_manifest=prior_manifest(),
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"",
        transport=snapshot.__getitem__,
    )
    assert result.status == "non_nerva"


def test_receipt_is_closed_world_but_rest_envelope_is_extensible():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    snapshot["comment:1"]["future_github_field"] = {"safe": True}
    result = run_pure_proof(
        event=event,
        baseline_manifest=prior_manifest(),
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
        transport=snapshot.__getitem__,
    )
    assert result.status == "proved"

    envelope = snapshot["comment:1"]
    envelope["body"] = envelope["body"].replace(
        '"schema_version":1', '"schema_version":1,"comment_id":1'
    )
    attestation = json.loads(json.dumps(snapshot["pull_request"]))
    marker = json.loads(attestation["body"].split(MARKER, 1)[1].split(movement.END_MARKER, 1)[0])
    marker["roles"]["program"]["comment_body_sha256"] = hashlib.sha256(
        envelope["body"].encode("utf-8")
    ).hexdigest()
    attestation["body"] = MARKER + json.dumps(marker, separators=(",", ":")) + movement.END_MARKER
    snapshot["pull_request"] = attestation
    with pytest.raises(MovementError, match="unknown field"):
        run_pure_proof(
            event={**event, "pull_request": dict(attestation)},
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


def test_live_transport_uses_fixed_urls_headers_bounds_and_identity_encoding():
    pr_url = f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}"
    payload = json.dumps({"state": "open"}).encode("utf-8")
    response = RestResponse(payload, url=pr_url, content_encoding="identity")
    opener = RestOpener([response])
    transport = movement._live_transport(
        REPOSITORY,
        PR_NUMBER,
        environment={"GITHUB_TOKEN": "live-secret"},
        opener=opener,
        timeout_seconds=7,
    )

    assert transport("pull_request") == {"state": "open"}
    request, timeout = opener.requests[0]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert request.full_url == pr_url
    assert request.get_method() == "GET"
    assert timeout == 7
    assert headers["authorization"] == "Bearer live-secret"
    assert headers["accept-encoding"] == "identity"
    assert headers["x-github-api-version"] == "2022-11-28"
    assert response.read_sizes == [movement.MAX_RESPONSE_BYTES + 1]


def test_live_transport_builds_only_the_fixed_comment_url_after_identifier_validation():
    pr_url = f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}"
    comment_url = f"https://api.github.com/repos/{REPOSITORY}/issues/comments/123"
    opener = RestOpener(
        [
            RestResponse(b"{}", url=pr_url),
            RestResponse(b"{}", url=comment_url),
        ]
    )
    transport = movement._live_transport(
        REPOSITORY,
        PR_NUMBER,
        environment={"GITHUB_TOKEN": "token"},
        opener=opener,
    )
    transport("pull_request")
    transport("comment:123")
    assert [request.full_url for request, _timeout in opener.requests] == [pr_url, comment_url]
    for invalid in ("comment:0", "comment:01", "comment:-1", "comment:1?redirect=1"):
        with pytest.raises(MovementError):
            transport(invalid)


@pytest.mark.parametrize(
    "response",
    [
        RestResponse(b"{}", url="https://api.github.com/changed"),
        RestResponse(
            b"{}", url=f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}", status=429
        ),
        RestResponse(
            b"{}",
            url=f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}",
            content_encoding="gzip",
        ),
        RestResponse(
            b"{" + b"x" * 300_000,
            url=f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}",
        ),
        RestResponse(
            b'{"state":',
            url=f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}",
        ),
        RestResponse(
            b"{}",
            url=f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}",
            content_length=999,
        ),
    ],
)
def test_live_transport_fails_closed_on_changed_url_status_encoding_size_and_truncation(response):
    opener = RestOpener([response])
    transport = movement._live_transport(
        REPOSITORY,
        PR_NUMBER,
        environment={"GITHUB_TOKEN": "token"},
        opener=opener,
    )
    with pytest.raises(MovementError):
        transport("pull_request")


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("secret timeout details"),
        urllib.error.URLError("secret network details"),
        urllib.error.HTTPError("https://redirect.invalid", 302, "secret", {}, io.BytesIO()),
    ],
)
def test_live_transport_sanitizes_timeout_network_http_and_redirect_failures(failure):
    opener = RestOpener([failure])
    transport = movement._live_transport(
        REPOSITORY,
        PR_NUMBER,
        environment={"GITHUB_TOKEN": "secret-token"},
        opener=opener,
    )
    with pytest.raises(MovementError) as rejected:
        transport("pull_request")
    message = str(rejected.value)
    assert "secret" not in message
    assert "redirect.invalid" not in message


def test_live_opener_disables_redirects_and_environment_proxies(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setattr(
        urllib.request,
        "getproxies",
        lambda: pytest.fail("live opener consulted environment proxy settings"),
    )
    context = ssl.create_default_context()
    opener = movement._build_live_opener(context)
    proxy_handlers = [
        handler for handler in opener.handlers if isinstance(handler, urllib.request.ProxyHandler)
    ]
    redirect_handlers = [
        handler for handler in opener.handlers if isinstance(handler, movement._NoRedirectHandler)
    ]
    assert proxy_handlers == []
    assert len(redirect_handlers) == 1
    original = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}",
        headers={"Authorization": "Bearer must-not-be-forwarded"},
    )
    assert (
        redirect_handlers[0].redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            "https://redirect.invalid/capture",
        )
        is None
    )
    unverified = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    with pytest.raises(MovementError, match="verified TLS"):
        movement._build_live_opener(unverified)


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "x" * 8_193,
        "line\rbreak",
        "line\nbreak",
        "nul\x00byte",
        "del\x7fbyte",
        "space byte",
        "non-ascii-ă",
    ],
)
def test_live_token_is_bounded_printable_ascii_and_environment_only(token):
    with pytest.raises(MovementError):
        movement._read_live_token({"GITHUB_TOKEN": token})


def test_event_file_is_read_with_a_hard_max_plus_one_bound(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_bytes(b"{}")
    sizes = []

    class Reader(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            return b"{" + b"x" * movement.MAX_EVENT_BYTES

    monkeypatch.setattr(Path, "open", lambda _self, _mode: Reader())
    assert (
        main(
            [
                "--event",
                str(event),
                "--base",
                BASE,
                "--head",
                HEAD,
                "--snapshot-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert sizes == [movement.MAX_EVENT_BYTES + 1]


def test_live_transport_bounds_identifiers_response_count_and_aggregate_bytes():
    with pytest.raises(MovementError):
        movement._live_transport(
            "owner/repo/extra",
            PR_NUMBER,
            environment={"GITHUB_TOKEN": "token"},
            opener=RestOpener([]),
        )
    with pytest.raises(MovementError):
        movement._live_transport(
            REPOSITORY,
            True,
            environment={"GITHUB_TOKEN": "token"},
            opener=RestOpener([]),
        )
    url = f"https://api.github.com/repos/{REPOSITORY}/pulls/{PR_NUMBER}"
    response = RestResponse(b"{}", url=url)
    transport = movement._live_transport(
        REPOSITORY,
        PR_NUMBER,
        environment={"GITHUB_TOKEN": "token"},
        opener=RestOpener([response] * (movement.MAX_RESPONSE_COUNT + 1)),
    )
    for _index in range(movement.MAX_RESPONSE_COUNT):
        transport("pull_request")
    with pytest.raises(MovementError, match="count"):
        transport("pull_request")

    payload = json.dumps(
        {"padding": "x" * (movement.MAX_RESPONSE_BYTES - 32)}, separators=(",", ":")
    ).encode("utf-8")
    responses = [RestResponse(payload, url=url) for _index in range(movement.MAX_RESPONSE_COUNT)]
    aggregate_transport = movement._live_transport(
        REPOSITORY,
        PR_NUMBER,
        environment={"GITHUB_TOKEN": "token"},
        opener=RestOpener(responses),
    )
    for _index in range(movement.MAX_RESPONSE_COUNT - 1):
        aggregate_transport("pull_request")
    with pytest.raises(MovementError, match="aggregate"):
        aggregate_transport("pull_request")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("id",), 999),
        (("issue_url",), "https://api.github.com/repos/andrei649/jarvis-hub/issues/999"),
        (("user", "login"), "attacker"),
        (("author_association",), "MEMBER"),
        (("created_at",), "2026-08-07T00:00:01Z"),
        (("updated_at",), "2026-08-07T00:00:01Z"),
    ],
)
def test_comment_envelope_requires_exact_identity_owner_issue_and_unedited_timestamp(path, value):
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    target = snapshot["comment:1"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


def test_snapshot_transport_has_the_same_per_response_count_and_aggregate_bounds(tmp_path):
    (tmp_path / "comments").mkdir()
    payload = json.dumps(
        {"padding": "x" * (movement.MAX_RESPONSE_BYTES - 32)}, separators=(",", ":")
    ).encode("utf-8")
    (tmp_path / "pull_request.json").write_bytes(payload)
    transport = movement._snapshot_transport(tmp_path)
    for _index in range(movement.MAX_RESPONSE_COUNT - 1):
        transport("pull_request")
    with pytest.raises(MovementError, match="offline snapshot"):
        transport("pull_request")

    (tmp_path / "pull_request.json").write_bytes(b"{" + b"x" * movement.MAX_RESPONSE_BYTES)
    oversized = movement._snapshot_transport(tmp_path)
    with pytest.raises(MovementError, match="offline snapshot"):
        oversized("pull_request")

    (tmp_path / "pull_request.json").write_bytes(b"{}")
    counted = movement._snapshot_transport(tmp_path)
    for _index in range(movement.MAX_RESPONSE_COUNT):
        counted("pull_request")
    with pytest.raises(MovementError, match="count"):
        counted("pull_request")


def test_missing_gate_rejects_without_pinned_bootstrap_bytes():
    with pytest.raises(MovementError, match="accepted bootstrap base"):
        validate_manifest_gate({}, LEGACY_BASE)
    with pytest.raises(MovementError, match="legacy manifest bytes"):
        validate_manifest_gate({}, ACCEPTED_BOOTSTRAP_BASE)


def test_duplicate_json_rejected():
    with pytest.raises(MovementError):
        strict_json('{"a":1,"a":2}')


@pytest.mark.parametrize(
    "raw",
    [
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
        '{"value":"line\\u0001break"}',
        "[" * 33 + "0" + "]" * 33,
    ],
)
def test_strict_json_rejects_hostile_scalars_and_depth(raw):
    with pytest.raises(MovementError):
        strict_json(raw, max_depth=32)


def test_strict_json_rejects_float_overflow_and_recursion_error():
    with pytest.raises(MovementError):
        strict_json("1e400")
    with pytest.raises(MovementError):
        strict_json("[" * 2_000 + "0" + "]" * 2_000, max_depth=32)


def test_diff_requires_complete_nul_records():
    assert parse_diff(b"M\0BACKLOG.md\0") == [("M", "BACKLOG.md")]
    with pytest.raises(MovementError):
        parse_diff(b"M\tBACKLOG.md")


@pytest.mark.parametrize(
    "raw",
    [
        b"R100\told\tnew\0",
        b"M\t../BACKLOG.md\0",
        b"M\tC:\\repo\\BACKLOG.md\0",
        b"M\t/absolute/path\0",
        b"M\tbad\x01path\0",
        b"M\tbad\xffpath\0",
    ],
)
def test_diff_rejects_ambiguous_or_unsafe_records_before_classification(raw):
    with pytest.raises(MovementError):
        parse_diff(raw)


def test_marker_requires_one_complete_bounded_closed_world_json_object():
    end = "<!-- NERVA2:MOVEMENT-ATTESTATION:END -->"
    body = f'prefix\n{MARKER}\n{{"schema_version":1}}\n{end}\nsuffix'
    assert parse_marker_json(body, MARKER, end, allowed_keys={"schema_version"}) == {
        "schema_version": 1
    }
    with pytest.raises(MovementError):
        parse_marker_json(body + MARKER, MARKER, end, allowed_keys={"schema_version"})
    with pytest.raises(MovementError):
        parse_marker_json(
            f'{MARKER}{{"schema_version":1,"extra":false}}{end}',
            MARKER,
            end,
            allowed_keys={"schema_version"},
        )


def test_registry_cannot_remove_or_narrow_coverage_and_new_entries_need_added_path():
    baseline = ["docs/nerva2/", "scripts/check_nerva_issue_movement.py"]
    with pytest.raises(MovementError):
        validate_registry_evolution(baseline, ["docs/nerva2/"], set())
    with pytest.raises(MovementError):
        validate_registry_evolution(baseline, ["docs/nerva2/", "docs/nerva2/private/"], set())
    validate_registry_evolution(
        baseline,
        baseline + ["tests/test_nerva_issue_movement.py"],
        {"tests/test_nerva_issue_movement.py"},
    )


def test_registry_rejects_wildcards_and_unrelated_broad_prefixes():
    with pytest.raises(MovementError):
        validate_registry_evolution([], ["docs/*.md"], {"docs/example.md"})
    with pytest.raises(MovementError):
        validate_registry_evolution([], ["docs/"], {"docs/example.md"})


def test_legacy_bootstrap_requires_exact_pinned_seed_and_real_integer_schema_version():
    gate = valid_gate()
    validate_manifest_gate({"movement_gate": gate}, ACCEPTED_BOOTSTRAP_BASE)
    gate["schema_version"] = True
    with pytest.raises(MovementError):
        validate_manifest_gate({"movement_gate": gate}, ACCEPTED_BOOTSTRAP_BASE)
    gate["schema_version"] = 1
    gate["registry"] = gate["registry"][:-1]
    with pytest.raises(MovementError):
        validate_manifest_gate({"movement_gate": gate}, ACCEPTED_BOOTSTRAP_BASE)


def test_gate_less_bootstrap_requires_accepted_base_and_exact_historical_bytes() -> None:
    manifest_bytes = _committed_blob(LEGACY_BASE, "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json")
    view_bytes = _committed_blob(LEGACY_BASE, "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md")
    legacy_manifest = strict_json(manifest_bytes)

    validate_manifest_gate(
        legacy_manifest,
        ACCEPTED_BOOTSTRAP_BASE,
        baseline_manifest_bytes=manifest_bytes,
        baseline_manifest_view_bytes=view_bytes,
    )

    for disallowed_base in (LEGACY_BASE, "f" * 40):
        with pytest.raises(MovementError, match="accepted bootstrap base"):
            validate_manifest_gate(
                legacy_manifest,
                disallowed_base,
                baseline_manifest_bytes=manifest_bytes,
                baseline_manifest_view_bytes=view_bytes,
            )
    with pytest.raises(MovementError, match="legacy manifest bytes"):
        validate_manifest_gate(
            legacy_manifest,
            ACCEPTED_BOOTSTRAP_BASE,
            baseline_manifest_bytes=manifest_bytes + b" ",
            baseline_manifest_view_bytes=view_bytes,
        )
    with pytest.raises(MovementError, match="legacy manifest view bytes"):
        validate_manifest_gate(
            legacy_manifest,
            ACCEPTED_BOOTSTRAP_BASE,
            baseline_manifest_bytes=manifest_bytes,
            baseline_manifest_view_bytes=view_bytes + b" ",
        )
    changed_semantics = copy.deepcopy(legacy_manifest)
    changed_semantics["manifest_id"] = "changed"
    with pytest.raises(MovementError, match="legacy manifest semantics"):
        validate_manifest_gate(
            changed_semantics,
            ACCEPTED_BOOTSTRAP_BASE,
            baseline_manifest_bytes=manifest_bytes,
            baseline_manifest_view_bytes=view_bytes,
        )


def test_required_gate_can_only_forward_disable_with_explicit_rollback_control() -> None:
    baseline = {"movement_gate": valid_gate()}
    candidate = copy.deepcopy(baseline)
    candidate_gate = candidate["movement_gate"]
    candidate_gate["enforcement_state"] = "safety_disabled"
    candidate_gate["program_control_issues"].append(900)
    candidate_gate["rollback"] = {
        "issue": 900,
        "rollback_of_issue": 846,
        "reason": "GitHub receipt reads are unavailable; disable before bounded cleanup.",
        "fresh_owner_receipts_required": True,
        "exact_head_checks_required": True,
    }

    validate_manifest_gate(candidate, "a" * 40)
    assert derive_scope(baseline, candidate) == {
        "kind": "program_control",
        "implementation_issue": 900,
        "stream_id": None,
        "epic_issue": None,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda gate: gate.update(rollback=None),
        lambda gate: gate["rollback"].update(issue=901),
        lambda gate: gate["rollback"].update(rollback_of_issue=839),
        lambda gate: gate["rollback"].update(reason=""),
        lambda gate: gate["rollback"].update(fresh_owner_receipts_required=False),
        lambda gate: gate["rollback"].update(exact_head_checks_required=False),
    ],
)
def test_safety_disable_rejects_missing_or_unbound_rollback_evidence(mutate) -> None:
    baseline = {"movement_gate": valid_gate()}
    candidate = copy.deepcopy(baseline)
    gate = candidate["movement_gate"]
    gate["enforcement_state"] = "safety_disabled"
    gate["program_control_issues"].append(900)
    gate["rollback"] = {
        "issue": 900,
        "rollback_of_issue": 846,
        "reason": "Disable the gate before bounded cleanup.",
        "fresh_owner_receipts_required": True,
        "exact_head_checks_required": True,
    }
    mutate(gate)

    with pytest.raises(MovementError):
        validate_manifest_gate(candidate, "a" * 40)


def test_safety_disabled_gate_cannot_return_to_required_without_new_schema() -> None:
    baseline = {"movement_gate": valid_gate()}
    disabled = copy.deepcopy(baseline)
    disabled_gate = disabled["movement_gate"]
    disabled_gate["enforcement_state"] = "safety_disabled"
    disabled_gate["program_control_issues"].append(900)
    disabled_gate["rollback"] = {
        "issue": 900,
        "rollback_of_issue": 846,
        "reason": "Disable the gate before bounded cleanup.",
        "fresh_owner_receipts_required": True,
        "exact_head_checks_required": True,
    }
    returned = copy.deepcopy(disabled)
    returned["movement_gate"]["enforcement_state"] = "required"
    returned["movement_gate"]["rollback"] = None

    with pytest.raises(MovementError):
        derive_scope(disabled, returned)


def test_compute_diff_parses_the_real_status_nul_path_nul_git_format(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    for args in (
        ["init"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True)
    path = tmp_path / "tracked.txt"
    path.write_text("one\n", encoding="utf-8")
    subprocess.run([git, "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "first"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    path.write_text("two\n", encoding="utf-8")
    subprocess.run([git, "commit", "-am", "second"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert compute_name_status_diff(base, head, git=git, cwd=tmp_path) == [("M", "tracked.txt")]


def test_compute_diff_rejects_oversized_stream_without_returning_classification():
    class Process:
        returncode = 0

        def __init__(self):
            self.stdout = __import__("io").BytesIO(b"A\0" + b"x" * MAX_DIFF_BYTES)

        def wait(self, timeout):
            return 0

        def kill(self):
            return None

    with pytest.raises(MovementError):
        compute_name_status_diff(
            "a" * 40,
            "b" * 40,
            popen_factory=lambda *_args, **_kwargs: Process(),
        )


def test_compute_diff_does_not_expose_os_error_text():
    secret = "token-not-for-logs"

    def failing_popen(*_args, **_kwargs):
        raise OSError(secret)

    with pytest.raises(MovementError) as failure:
        compute_name_status_diff("a" * 40, "b" * 40, popen_factory=failing_popen)
    assert secret not in str(failure.value)


def test_cli_rejects_event_that_is_not_bound_to_requested_base_head_and_diff(tmp_path):
    event = tmp_path / "event.json"
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    diff = tmp_path / "diff.bin"
    event.write_text(
        '{"pull_request":{"base":{"sha":"'
        + "a" * 40
        + '"},"head":{"ref":"nerva2/x","sha":"'
        + "b" * 40
        + '"}}}',
        encoding="utf-8",
    )
    baseline.write_text("{}", encoding="utf-8")
    candidate.write_text("{}", encoding="utf-8")
    diff.write_bytes(b"M\0BACKLOG.md\0")
    assert (
        main(
            [
                "--event",
                str(event),
                "--baseline-manifest",
                str(baseline),
                "--manifest",
                str(candidate),
                "--base",
                "c" * 40,
                "--head",
                "b" * 40,
                "--diff",
                str(diff),
                "--snapshot-dir",
                str(tmp_path),
            ]
        )
        == 1
    )


def test_classifier_uses_baseline_candidate_registry_union():
    assert classify(
        "feature/x",
        "",
        ["scripts/check_nerva_issue_movement.py"],
        baseline_registry=["scripts/check_nerva_issue_movement.py"],
        candidate_registry=[],
    )


def test_classifier_is_deterministic():
    assert classify("nerva2/x", "", [])
    assert classify("feature/x", MARKER, [])
    assert not classify("feature/x", "", ["src/app.py"])


def test_strict_json_normalizes_huge_integer_parser_failure():
    with pytest.raises(MovementError):
        strict_json("9" * 5_000)


def test_empty_diff_is_a_valid_zero_record_diff():
    assert parse_diff(b"") == []


def test_legacy_baseline_projects_missing_gate_but_candidate_must_materialize_it():
    event, _candidate, _candidate_bytes, _snapshot = snapshot_proof()
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest={},
            candidate_manifest_bytes=b"{}",
            base=BASE,
            head=HEAD,
            diff=b"",
        )


def test_non_draft_nerva_requires_manifest_view_and_injected_snapshot_proof():
    event, candidate, candidate_bytes, _snapshot = snapshot_proof()
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
        )


def test_offline_snapshot_proves_attestation_receipt_and_semantic_scope():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    result = run_pure_proof(
        event=event,
        baseline_manifest=prior_manifest(),
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
        transport=snapshot.__getitem__,
    )
    assert result.status == "proved"
    assert result.scope["implementation_issue"] == 846
    assert derive_scope({}, candidate)["kind"] == "program_control"


def test_attestation_digest_binds_exact_candidate_manifest_bytes():
    event, candidate, _candidate_bytes, snapshot = snapshot_proof()
    semantically_equal_bytes = json.dumps(candidate, indent=2).encode()
    with pytest.raises(MovementError, match="attestation does not bind movement proof"):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=semantically_equal_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


def test_offline_snapshot_rejects_edited_receipt_and_cross_binding():
    event, candidate, candidate_bytes, snapshot = snapshot_proof(mutate_receipt=True)
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


def test_semantic_stream_scope_derives_exactly_one_new_referenced_issue():
    baseline = {
        "movement_gate": valid_gate(),
        "streams": [
            {
                "id": "E1",
                "name": "Stream",
                "epic_issue": 759,
                "references": [{"kind": "issue", "value": 759}],
            }
        ],
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["streams"][0]["references"].append({"kind": "issue", "value": 900})
    assert derive_scope(baseline, candidate) == {
        "kind": "stream",
        "implementation_issue": 900,
        "stream_id": "E1",
        "epic_issue": 759,
    }


def test_legacy_bootstrap_preserves_real_baseline_root_data_except_gate_addition():
    baseline = {"authority": {"can_execute": False}, "streams": []}
    candidate = {**baseline, "movement_gate": valid_gate()}
    assert derive_scope(baseline, candidate)["implementation_issue"] == 846


def test_program_control_rejects_immutable_gate_transition():
    baseline = {"movement_gate": valid_gate()}
    candidate = json.loads(json.dumps(baseline))
    candidate["movement_gate"]["enforcement_state"] = "safety_disabled"
    candidate["movement_gate"]["program_control_issues"].append(900)
    with pytest.raises(MovementError):
        derive_scope(baseline, candidate)


def test_stream_scope_rejects_history_rewrite_and_building_to_done():
    baseline = {
        "movement_gate": valid_gate(),
        "streams": [
            {
                "id": "E1",
                "name": "Stream",
                "epic_issue": 759,
                "program_status": "building",
                "references": [{"kind": "issue", "value": 759}],
                "completion_evidence": [{"issue": 700}],
                "delivery_prerequisites": [],
                "blockers": [],
            }
        ],
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["streams"][0]["references"].append({"kind": "issue", "value": 900})
    candidate["streams"][0]["completion_evidence"] = []
    candidate["streams"][0]["program_status"] = "done"
    with pytest.raises(MovementError):
        derive_scope(baseline, candidate)


def test_current_snapshot_is_fetched_before_non_nerva_classification():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    event["pull_request"]["head"]["ref"] = "feature/event-stale"
    calls = []

    def transport(key):
        calls.append(key)
        return snapshot[key]

    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"",
            transport=transport,
        )
    assert calls == ["pull_request"]


def test_legacy_bootstrap_gate_rejects_any_noncanonical_control_state():
    for key, value in (
        ("enforcement_state", "safety_disabled"),
        ("program_control_issues", [999]),
        ("continuous_currentness", True),
        ("live_receipt_control", False),
    ):
        gate = valid_gate()
        gate[key] = value
        with pytest.raises(MovementError):
            validate_manifest_gate({"movement_gate": gate}, ACCEPTED_BOOTSTRAP_BASE)


def test_program_control_rejects_duplicate_or_replayed_issue_append():
    baseline = {"movement_gate": valid_gate()}
    candidate = json.loads(json.dumps(baseline))
    candidate["movement_gate"]["program_control_issues"].append(846)
    with pytest.raises(MovementError):
        derive_scope(baseline, candidate)


def test_stream_new_evidence_must_bind_current_pull_request():
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = {
        "completion_evidence": [{"issue": 900, "pull_request": 123}],
        "delivery_prerequisites": [],
    }
    with pytest.raises(MovementError):
        validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_snapshot_rejects_boolean_comment_identifier():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    snapshot["comment:1"]["id"] = True
    with pytest.raises(MovementError):
        run_pure_proof(
            event=event,
            baseline_manifest=prior_manifest(),
            candidate_manifest=candidate,
            candidate_manifest_bytes=candidate_bytes,
            base=BASE,
            head=HEAD,
            diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
            transport=snapshot.__getitem__,
        )


def test_draft_without_marker_is_receipt_free_hold_and_marker_proof_is_validated_hold():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    event["pull_request"]["draft"] = True
    snapshot["pull_request"]["draft"] = True
    proof = run_pure_proof(
        event=event,
        baseline_manifest=prior_manifest(),
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0",
        transport=snapshot.__getitem__,
    )
    assert proof.status == "draft_hold"
    event["pull_request"]["body"] = ""
    snapshot["pull_request"]["body"] = ""
    proof = run_pure_proof(
        event=event,
        baseline_manifest=prior_manifest(),
        candidate_manifest=candidate,
        candidate_manifest_bytes=candidate_bytes,
        base=BASE,
        head=HEAD,
        diff=b"",
        transport=snapshot.__getitem__,
    )
    assert proof.status == "draft_hold"


def test_new_prerequisite_accepted_evidence_must_bind_current_pr():
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = {
        "completion_evidence": [],
        "delivery_prerequisites": [
            {"source": "E0", "accepted_evidence": [{"issue": 900, "pull_request": 12}]}
        ],
    }
    with pytest.raises(MovementError):
        validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_stream_scope_allows_append_only_evidence_on_existing_prerequisite():
    baseline = {
        "movement_gate": valid_gate(),
        "streams": [
            {
                "id": "E1",
                "name": "Stream",
                "epic_issue": 759,
                "references": [{"kind": "issue", "value": 759}],
                "completion_evidence": [],
                "delivery_prerequisites": [{"source": "E0", "accepted_evidence": []}],
                "blockers": [],
            }
        ],
    }
    candidate = json.loads(json.dumps(baseline))
    candidate["streams"][0]["references"].append({"kind": "issue", "value": 900})
    candidate["streams"][0]["delivery_prerequisites"][0]["accepted_evidence"].append(
        {"issue": 900, "pull_request": 849}
    )
    assert derive_scope(baseline, candidate)["implementation_issue"] == 900


def test_diff_wait_timeout_kills_and_reaps_before_distinct_timeout():
    class Process:
        def __init__(self):
            self.stdout = __import__("io").BytesIO(b"")
            self.killed = False

        def wait(self, timeout):
            if not self.killed:
                raise subprocess.TimeoutExpired("git", timeout)
            return 0

        def kill(self):
            self.killed = True

    process = Process()
    with pytest.raises(MovementError, match="diff read timed out"):
        compute_name_status_diff(
            "a" * 40,
            "b" * 40,
            popen_factory=lambda *_args, **_kwargs: process,
        )
    assert process.killed


def test_numeric_cross_bindings_reject_boolean_aliases():
    event, candidate, candidate_bytes, snapshot = snapshot_proof()
    scope = derive_scope({}, candidate)
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    current = json.loads(json.dumps(snapshot["pull_request"]))
    current["number"] = True
    with pytest.raises(MovementError):
        _fetch_current_snapshot(
            lambda _key: current,
            repository=REPOSITORY,
            number=1,
            base=BASE,
            head=HEAD,
        )
    attestation_body = snapshot["pull_request"]["body"].replace(
        '"pull_request":849', '"pull_request":true'
    )
    with pytest.raises(MovementError):
        _validate_attestation(
            attestation_body,
            repository=REPOSITORY,
            number=1,
            base=BASE,
            head=HEAD,
            digest=digest,
            scope=scope,
        )
    receipt_envelope = json.loads(json.dumps(snapshot["comment:1"]))
    receipt_envelope["body"] = receipt_envelope["body"].replace(
        '"pull_request":849', '"pull_request":true'
    )
    comment = dict(
        json.loads(json.dumps(snapshot["pull_request"]))["body"]
        and {"comment_id": 1, "updated_at": "2026-08-07T00:00:00Z"}
    )
    comment["comment_body_sha256"] = hashlib.sha256(receipt_envelope["body"].encode()).hexdigest()
    with pytest.raises(MovementError):
        _validate_receipt(
            receipt_envelope,
            role="program",
            issue=757,
            comment=comment,
            repository=REPOSITORY,
            number=1,
            base=BASE,
            head=HEAD,
            digest=digest,
            scope=scope,
        )


def test_blocked_reader_reports_timeout_even_if_kill_unblocks_eof():
    released = __import__("threading").Event()

    class BlockingStream:
        def read(self, _size):
            released.wait()
            return b""

    class Process:
        def __init__(self):
            self.stdout = BlockingStream()
            self.killed = False
            self.waits = 0

        def kill(self):
            self.killed = True
            released.set()

        def wait(self, timeout):
            del timeout
            self.waits += 1
            return 0

    process = Process()
    with pytest.raises(MovementError, match="diff read timed out"):
        compute_name_status_diff(
            "a" * 40,
            "b" * 40,
            popen_factory=lambda *_args, **_kwargs: process,
            timeout_seconds=0.01,
        )
    assert process.killed and process.waits == 1


@pytest.mark.parametrize(
    "field,value", [("issue", True), ("issue", 0), ("pull_request", True), ("pull_request", 0)]
)
@pytest.mark.parametrize("kind", ["completion", "accepted"])
def test_new_evidence_requires_positive_real_issue_and_pull_request(field, value, kind):
    record = {"issue": 900, "pull_request": 849}
    record[field] = value
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = (
        {"completion_evidence": [record], "delivery_prerequisites": []}
        if kind == "completion"
        else {
            "completion_evidence": [],
            "delivery_prerequisites": [{"source": "E0", "accepted_evidence": [record]}],
        }
    )
    with pytest.raises(MovementError):
        validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_new_evidence_accepts_legitimate_positive_issue_reference():
    baseline = {"completion_evidence": [], "delivery_prerequisites": []}
    candidate = {
        "completion_evidence": [{"issue": 900, "pull_request": 849}],
        "delivery_prerequisites": [
            {"source": "E0", "accepted_evidence": [{"issue": 900, "pull_request": 849}]}
        ],
    }
    validate_stream_evidence_bindings(baseline, candidate, pull_request=849)


def test_git_resolution_is_absolute_and_subprocess_environment_drops_secrets(tmp_path):
    git = _resolve_git_executable(tmp_path)
    assert Path(git).is_absolute()
    environment = _git_environment(
        git,
        {
            "PATH": os.environ.get("PATH", ""),
            "Path": "C:\\untrusted-path",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GITHUB_TOKEN": "github-secret",
            "GH_TOKEN": "gh-secret",
            "HTTP_PROXY": "http://proxy.invalid",
            "https_proxy": "http://proxy.invalid",
            "NO_PROXY": "github.com",
            "GIT_CONFIG_GLOBAL": "hostile-config",
        },
    )
    upper_keys = {key.upper() for key in environment}
    assert "GITHUB_TOKEN" not in upper_keys
    assert "GH_TOKEN" not in upper_keys
    assert "HTTP_PROXY" not in upper_keys
    assert "HTTPS_PROXY" not in upper_keys
    assert "NO_PROXY" not in upper_keys
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_CONFIG_GLOBAL"] == os.devnull
    assert sum(key.upper() == "PATH" for key in environment) == 1
    assert Path(environment["PATH"]).resolve() == Path(git).parent.resolve()


def test_repository_proof_binds_exact_commits_manifest_bytes_and_diff(tmp_path):
    _git, base, head, event = binding_repository(tmp_path)
    observed = {}

    def proof_runner(**kwargs):
        observed.update(kwargs)
        return PureProof("proved", {"kind": "program_control", "implementation_issue": 846})

    validated = []
    result = run_repository_proof(
        root=tmp_path,
        event=event,
        base=base,
        head=head,
        transport=None,
        proof_runner=proof_runner,
        manifest_validator=lambda root, candidate: validated.append((root, candidate)),
    )
    assert result.status == "proved"
    assert observed["candidate_manifest_bytes"] == b'{"version":2}\n'
    assert observed["candidate_manifest"] == {"version": 2}
    assert observed["baseline_manifest"] == {"version": 1}
    assert observed["baseline_manifest_bytes"] == b'{"version":1}\n'
    assert observed["baseline_manifest_view_bytes"] == b"# version 1\n"
    assert observed["diff"] == (
        b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json\0"
        b"M\0docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md\0"
    )
    assert validated == [(tmp_path.resolve(), head)]


def test_repository_proof_bootstraps_real_accepted_e596_legacy_bytes(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    repository = tmp_path / "repo"
    subprocess.run(
        [git, "clone", "--quiet", "--shared", "--no-checkout", str(REPO), str(repository)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [git, "checkout", "--quiet", ACCEPTED_BOOTSTRAP_BASE],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [git, "config", "user.email", "test@example.invalid"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [git, "config", "user.name", "Test"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    for relative in (
        Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"),
        Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"),
    ):
        shutil.copy2(REPO / relative, repository / relative)
    subprocess.run(
        [git, "commit", "-am", "candidate"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        [git, "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    pull_request = {
        "number": PR_NUMBER,
        "base": {
            "sha": ACCEPTED_BOOTSTRAP_BASE,
            "ref": "main",
            "repo": {"full_name": REPOSITORY},
        },
        "head": {"sha": head, "ref": "nerva2/bootstrap"},
        "body": "",
        "draft": True,
        "state": "open",
        "user": {"login": "andrei649"},
    }
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": copy.deepcopy(pull_request),
    }

    result = run_repository_proof(
        root=repository,
        event=event,
        base=ACCEPTED_BOOTSTRAP_BASE,
        head=head,
        transport=lambda key: pull_request if key == "pull_request" else None,
        manifest_validator=lambda _root, _head: None,
    )

    assert result.status == "draft_hold"

    subprocess.run(
        [git, "checkout", "--quiet", "-B", "later-base", ACCEPTED_BOOTSTRAP_BASE],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [git, "commit", "--allow-empty", "-m", "unchanged later base"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    later_base = subprocess.run(
        [git, "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    for relative in (
        Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"),
        Path("docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"),
    ):
        shutil.copy2(REPO / relative, repository / relative)
    subprocess.run(
        [git, "commit", "-am", "later candidate"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    later_head = subprocess.run(
        [git, "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    later_pull_request = copy.deepcopy(pull_request)
    later_pull_request["base"]["sha"] = later_base
    later_pull_request["head"]["sha"] = later_head
    later_event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": copy.deepcopy(later_pull_request),
    }
    with pytest.raises(MovementError, match="accepted bootstrap base"):
        run_repository_proof(
            root=repository,
            event=later_event,
            base=later_base,
            head=later_head,
            transport=(lambda key: later_pull_request if key == "pull_request" else None),
            manifest_validator=lambda _root, _head: None,
        )


def test_repository_proof_rejects_non_ancestor_base(tmp_path):
    git, _base, head, event = binding_repository(tmp_path)
    subprocess.run(
        [git, "checkout", "--orphan", "unrelated"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run([git, "rm", "-rf", "."], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    subprocess.run([git, "add", "unrelated.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [git, "commit", "-m", "unrelated"], cwd=tmp_path, check=True, capture_output=True
    )
    unrelated = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run([git, "checkout", head], cwd=tmp_path, check=True, capture_output=True)
    event["pull_request"]["base"]["sha"] = unrelated
    with pytest.raises(MovementError, match="base is not an ancestor"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=unrelated,
            head=head,
            transport=None,
            proof_runner=lambda **_kwargs: pytest.fail("proof must not run"),
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_proof_rejects_legacy_graft_before_non_nerva_skip(tmp_path):
    root, base, head = grafted_unrelated_repository(tmp_path, linked_worktree=False)
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": base, "ref": "main"},
            "head": {"sha": head, "ref": "feature/ordinary"},
            "body": "",
            "draft": False,
            "state": "open",
        },
    }
    current = json.loads(json.dumps(event["pull_request"]))
    current["base"]["repo"] = event["repository"]
    with pytest.raises(MovementError, match="legacy Git grafts"):
        run_repository_proof(
            root=root,
            event=event,
            base=base,
            head=head,
            transport={"pull_request": current}.__getitem__,
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_proof_rejects_common_dir_graft_before_unattested_draft_hold(tmp_path):
    root, base, head = grafted_unrelated_repository(tmp_path, linked_worktree=True)
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": base, "ref": "main"},
            "head": {"sha": head, "ref": "nerva2/draft"},
            "body": "",
            "draft": True,
            "state": "open",
        },
    }
    current = json.loads(json.dumps(event["pull_request"]))
    current["base"]["repo"] = event["repository"]
    with pytest.raises(MovementError, match="legacy Git grafts"):
        run_repository_proof(
            root=root,
            event=event,
            base=base,
            head=head,
            transport={"pull_request": current}.__getitem__,
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_proof_rejects_event_head_that_is_not_checkout(tmp_path):
    git, base, head, event = binding_repository(tmp_path)
    subprocess.run(
        [git, "commit", "--allow-empty", "-m", "different checkout"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    with pytest.raises(MovementError, match="event head does not equal checked-out HEAD"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=base,
            head=head,
            transport=None,
            proof_runner=lambda **_kwargs: pytest.fail("proof must not run"),
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_proof_requires_both_canonical_manifest_files_in_exact_diff(tmp_path):
    git, base, _head, event = binding_repository(tmp_path)
    document = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
    document.write_bytes(b"# version 1\n")
    subprocess.run(
        [git, "commit", "-am", "omit generated view"], cwd=tmp_path, check=True, capture_output=True
    )
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    event["pull_request"]["head"]["sha"] = head
    with pytest.raises(MovementError, match="omits canonical manifest or generated view"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=base,
            head=head,
            transport=None,
            proof_runner=lambda **_kwargs: PureProof(
                "proved", {"kind": "program_control", "implementation_issue": 846}
            ),
            manifest_validator=lambda *_args: pytest.fail("validator must not run"),
        )


def test_repository_binding_preserves_non_nerva_skip_without_manifest_churn(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable unavailable")
    for args in (
        ["init"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run([git, *args], cwd=tmp_path, check=True, capture_output=True)
    manifest = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json"
    document = tmp_path / "docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.md"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(candidate_manifest()), encoding="utf-8")
    document.write_text("unchanged\n", encoding="utf-8")
    subprocess.run([git, "add", "docs"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    base = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    source = tmp_path / "src/app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run([git, "add", "src/app.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "ordinary"], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(
        [git, "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {
            "number": PR_NUMBER,
            "base": {"sha": base, "ref": "main"},
            "head": {"sha": head, "ref": "feature/ordinary"},
            "body": "",
            "draft": False,
            "state": "open",
        },
    }
    current = json.loads(json.dumps(event["pull_request"]))
    current["base"]["repo"] = event["repository"]
    result = run_repository_proof(
        root=tmp_path,
        event=event,
        base=base,
        head=head,
        transport={"pull_request": current}.__getitem__,
        manifest_validator=lambda *_args: pytest.fail("non-Nerva must not invoke validator"),
    )
    assert result.status == "non_nerva"


def test_repository_proof_rechecks_head_immediately_before_success(tmp_path):
    git, base, head, event = binding_repository(tmp_path)

    def move_head(**_kwargs):
        subprocess.run(
            [git, "commit", "--allow-empty", "-m", "move head"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        return PureProof("proved", {"kind": "program_control", "implementation_issue": 846})

    with pytest.raises(MovementError, match="checked-out HEAD moved"):
        run_repository_proof(
            root=tmp_path,
            event=event,
            base=base,
            head=head,
            transport=None,
            proof_runner=move_head,
            manifest_validator=lambda *_args: None,
        )


def test_ci_nerva_movement_is_pr_only_exact_head_and_uses_live_checker() -> None:
    workflow_path = Path(__file__).parents[1] / ".github/workflows/ci.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    assert "pull_request_target" not in workflow_text
    assert "paths:" not in workflow_text
    pull_request = workflow["on"]["pull_request"]
    assert isinstance(pull_request, dict)
    assert set(pull_request["types"]) == {
        "opened",
        "synchronize",
        "reopened",
        "edited",
        "ready_for_review",
        "converted_to_draft",
    }

    movement_job = workflow["jobs"]["nerva-movement"]
    assert movement_job["if"] == "github.event_name == 'pull_request'"
    assert movement_job["timeout-minutes"] == "10"
    assert movement_job["permissions"] == {
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }

    checkout = next(
        step for step in movement_job["steps"] if "actions/checkout@" in step.get("uses", "")
    )
    assert checkout["with"] == {
        "fetch-depth": "0",
        "persist-credentials": "false",
        "ref": "${{ github.event.pull_request.head.sha }}",
    }

    checker = next(
        step for step in movement_job["steps"] if step.get("name") == "Validate live Nerva movement"
    )
    assert checker["timeout-minutes"] == "5"
    assert checker["env"] == {
        "GITHUB_TOKEN": "${{ github.token }}",
        "NERVA_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "NERVA_HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
    }
    assert checker["run"].split() == [
        "python",
        "scripts/check_nerva_issue_movement.py",
        "--live",
        "--event",
        '"$GITHUB_EVENT_PATH"',
        "--base",
        '"$NERVA_BASE_SHA"',
        "--head",
        '"$NERVA_HEAD_SHA"',
        "--root",
        '"$GITHUB_WORKSPACE"',
    ]
    assert "${{" not in checker["run"]
    assert [step for step in movement_job["steps"] if "GITHUB_TOKEN" in step.get("env", {})] == [
        checker
    ]


def test_ci_test_matrix_fails_before_setup_when_pr_movement_fails() -> None:
    workflow_path = Path(__file__).parents[1] / ".github/workflows/ci.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    test_job = workflow["jobs"]["test"]

    assert test_job["needs"] == ["nerva-movement"]
    assert test_job["if"] == "always()"
    assert test_job["strategy"]["matrix"]["os"] == ["ubuntu-latest", "windows-latest"]
    assert test_job["steps"][0] == {
        "name": "Require successful Nerva movement on pull requests",
        "if": "github.event_name == 'pull_request' && needs.nerva-movement.result != 'success'",
        "run": "exit 1",
    }
    assert "uses" not in test_job["steps"][0]


def test_ci_movement_permissions_are_read_only_and_runs_are_static() -> None:
    workflow_path = Path(__file__).parents[1] / ".github/workflows/ci.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)

    permission_sets = [workflow["permissions"]]
    permission_sets.extend(
        job["permissions"] for job in workflow["jobs"].values() if "permissions" in job
    )
    assert all(value == "read" for permissions in permission_sets for value in permissions.values())

    movement_runs = [
        step["run"] for step in workflow["jobs"]["nerva-movement"]["steps"] if "run" in step
    ]
    assert all("${{" not in command for command in movement_runs)
