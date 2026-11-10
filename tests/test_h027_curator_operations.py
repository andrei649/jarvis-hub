"""H027 owner curator operations: exact approval, local bytes, and recovery."""

import io
import tarfile
from datetime import UTC, datetime, timedelta

from agents.core.autonomy.action_approvals import ActionApprovalQueue
from agents.core.skills.curator import SkillCurator
from agents.core.skills.curator_operations import CuratorOperations
from agents.core.skills.references import Holders
from agents.core.skills.signing import source_snapshot
from agents.core.skills.usage import ORIGIN_AGENT, ORIGIN_IMPORT, SkillUsageStore


class Loader:
    def __init__(self):
        self.skills = {}
        self.roots = set()

    def add(self, name, path):
        path.mkdir()
        (path / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        skill = type("Skill", (), {"path": path, "external": True, "name": name})()
        self.skills[name] = skill
        self.roots.add(path)
        return skill

    def discover(self):
        for path in self.roots:
            if path.is_dir():
                self.skills[path.name] = type("Skill", (), {"path": path, "external": True, "name": path.name})()

    def owner_standing(self, skill):
        return {"bundled": False, "unreadable": False, "snapshot": source_snapshot(skill.path)}


def setup(tmp_path):
    loader = Loader()
    usage = SkillUsageStore(tmp_path / "usage.json")
    approvals = ActionApprovalQueue(tmp_path / "approvals.json")
    curator = SkillCurator(loader, usage, archive_dir=tmp_path / "archive")
    ops = CuratorOperations(loader, usage, curator, approvals,
                            state_dir=tmp_path / "operations", archive_dir=tmp_path / "archive",
                            get_setting=lambda _key, default=None: default,
                            holders=lambda: Holders(switches=lambda: {"disabled": [], "channel_disabled": {}},
                                                    load_set=lambda: {"disabled": [], "only": []},
                                                    bundles=lambda: []))
    return loader, usage, approvals, ops


def gate(verdict="queue"):
    calls = []

    def authorize(payload):
        calls.append(dict(payload))
        return verdict

    return authorize, calls


def decide_and_apply(ops, approvals, operation, args, authorize):
    preview = ops.preview(operation, args)
    assert preview["ok"] is True
    pending = ops.request(operation, args, preview_fingerprint=preview["preview_fingerprint"],
                          actor="owner", authorize=authorize)
    assert pending["status"] == "pending"
    approvals.decide(pending["card_id"], True, by="user")
    return ops.apply_decision(pending["card_id"], authorize=authorize)


def test_read_and_preview_do_not_write_or_infer_agent_origin(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("unknown", tmp_path / "unknown")
    loader.add("imported", tmp_path / "imported")
    usage.note_created("imported", ORIGIN_IMPORT)
    usage.bump("unknown", "view")  # telemetry's default bundled label is not provenance
    before = usage.path.read_bytes()

    assert "unknown" in [row["name"] for row in ops.read("list-unmanaged")["items"]]
    assert next(row for row in ops.read("usage")["items"] if row["name"] == "unknown")["origin"] == "unknown"
    assert "imported" not in [row["name"] for row in ops.read("list-unmanaged")["items"]]
    assert ops.preview("adopt", {"name": "unknown"})["ok"] is True
    assert usage.path.read_bytes() == before
    assert not (tmp_path / "operations").exists()
    assert approvals.list() == []


def test_exact_approved_card_and_live_kernel_required_for_archive(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, calls = gate("queue")
    preview = ops.preview("archive", {"name": "agent"})
    pending = ops.request("archive", {"name": "agent"},
                          preview_fingerprint=preview["preview_fingerprint"],
                          actor="owner", authorize=authorize)
    assert pending["status"] == "pending"
    assert skill.path.exists() and usage.get("agent")["state"] == "active"
    assert ops.apply_decision(pending["card_id"], authorize=authorize)["status"] == "refused"
    approvals.decide(pending["card_id"], True, by="user")
    applied = ops.apply_decision(pending["card_id"], authorize=authorize)
    assert applied["status"] == "applied" and applied["ledger_id"]
    assert not skill.path.exists() and usage.get("agent")["state"] == "archived"
    assert len(ops.read("list-archived")["items"]) == 1
    assert ops.apply_decision(pending["card_id"], authorize=authorize)["status"] == "refused"
    assert [call["phase"] for call in calls] == ["request", "apply"]


def test_stale_bytes_and_protected_import_refuse_before_write(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    loader.add("imported", tmp_path / "imported")
    usage.note_created("imported", ORIGIN_IMPORT)
    assert ops.preview("archive", {"name": "imported"})["status"] == "refused"
    authorize, _ = gate("queue")
    preview = ops.preview("archive", {"name": "agent"})
    (skill.path / "SKILL.md").write_text("# changed\n", encoding="utf-8")
    refused = ops.request("archive", {"name": "agent"},
                          preview_fingerprint=preview["preview_fingerprint"],
                          actor="owner", authorize=authorize)
    assert refused["status"] == "refused"
    assert skill.path.exists() and not ops.read("list-archived")["items"]


def test_restore_and_single_mutation_rollback_keep_bytes(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    original = (skill.path / "SKILL.md").read_bytes()
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    decide_and_apply(ops, approvals, "archive", {"name": "agent"}, authorize)
    archive_id = ops.read("list-archived")["items"][0]["id"]
    restored = decide_and_apply(ops, approvals, "restore", {"archive_id": archive_id}, authorize)
    assert restored["status"] == "applied"
    assert (skill.path / "SKILL.md").read_bytes() == original
    assert usage.get("agent")["state"] == "active"
    rolled = decide_and_apply(ops, approvals, "rollback", {"ledger_id": restored["ledger_id"]}, authorize)
    assert rolled["status"] == "applied"
    assert not skill.path.exists()
    assert ops.read("list-archived")["items"]


def test_purge_requires_verified_backup_and_never_runs_automatically(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    decide_and_apply(ops, approvals, "archive", {"name": "agent"}, authorize)
    assert ops.preview("purge", {"days": 0})["status"] == "refused"
    assert ops.read("list-archived")["items"]
    assert (tmp_path / "archive").exists()


def test_archive_rollback_restores_original_bytes(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    original = (skill.path / "SKILL.md").read_bytes()
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    archived = decide_and_apply(ops, approvals, "archive", {"name": "agent"}, authorize)
    rolled = decide_and_apply(ops, approvals, "rollback", {"ledger_id": archived["ledger_id"]}, authorize)
    assert rolled["status"] == "applied"
    assert (skill.path / "SKILL.md").read_bytes() == original
    assert usage.get("agent")["state"] == "active"


def test_bulk_adopt_does_not_rewrite_origin(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("owner", tmp_path / "owner")
    authorize, _ = gate("queue")
    preview = ops.preview("adopt", {"all_unmanaged": True})
    assert preview["ok"] and [x["name"] for x in preview["targets"]] == ["owner"]
    out = decide_and_apply(ops, approvals, "adopt", {"all_unmanaged": True}, authorize)
    assert out["status"] == "applied"
    assert usage.get("owner") is None
    assert not ops.read("list-unmanaged")["items"]


def test_unmanaged_pin_records_owner_choice_without_adopting(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("owner", tmp_path / "owner")
    authorize, _ = gate("queue")
    assert decide_and_apply(ops, approvals, "pin", {"name": "owner"}, authorize)["status"] == "applied"
    assert usage.get("owner")["pinned"] is True
    assert usage.get("owner")["origin"] == "bundled"  # legacy telemetry default, not authorship
    assert ops.read("usage")["items"][0]["origin"] == "unknown"
    assert [item["name"] for item in ops.read("list-unmanaged")["items"]] == ["owner"]


def test_references_refuse_archive_before_card(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    ops.holders = lambda: Holders(jobs=lambda: [type("Job", (), {"id": "j1", "name": "j1", "action": {"prompt": "run agent"}})()],
                                  switches=lambda: {"disabled": [], "channel_disabled": {}},
                                  load_set=lambda: {"disabled": [], "only": []}, bundles=lambda: [])
    assert ops.preview("archive", {"name": "agent"})["reason"] == "source_referenced"
    assert approvals.list() == []


def test_backup_is_verified_and_rollback_requires_empty_or_managed_destination(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    saved = decide_and_apply(ops, approvals, "backup", {"reason": "manual"}, authorize)
    assert saved["status"] == "applied"
    assert ops.read("backups")["items"]
    assert ops.preview("rollback", {"backup_id": saved["backup_id"]})["ok"]
    (skill.path / "SKILL.md").write_text("# owner edit\n", encoding="utf-8")
    assert ops.preview("rollback", {"backup_id": saved["backup_id"]})["status"] == "refused"
    assert (skill.path / "SKILL.md").read_text() == "# owner edit\n"


def test_backup_rollback_restores_archived_managed_slice_and_keeps_safety_copy(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    original = (skill.path / "SKILL.md").read_bytes()
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    saved = decide_and_apply(ops, approvals, "backup", {}, authorize)
    decide_and_apply(ops, approvals, "archive", {"name": "agent"}, authorize)
    rolled = decide_and_apply(ops, approvals, "rollback", {"backup_id": saved["backup_id"]}, authorize)
    assert rolled["status"] == "applied"
    assert (skill.path / "SKILL.md").read_bytes() == original
    assert not ops.read("list-archived")["items"]
    assert len(ops.read("backups")["items"]) >= 2


def test_pause_persists_and_scheduled_run_requires_grant(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    ops.get_setting = lambda key, default=None: True if key == "cognition.review_enabled" else default
    authorize, calls = gate("queue")
    assert ops.run_scheduled(authorize=authorize)["status"] == "refused"
    assert calls[-1]["phase"] == "scheduled"
    decide_and_apply(ops, approvals, "pause", {}, authorize)
    again = CuratorOperations(loader, usage, ops.curator, approvals,
                              state_dir=ops.state_dir, archive_dir=ops.archive_dir,
                              get_setting=ops.get_setting, holders=ops.holders)
    assert again.read("status")["paused"] is True
    assert again.run_scheduled(authorize=lambda _payload: "grant")["reason"] == "paused"
    manual = decide_and_apply(again, approvals, "run", {}, authorize)
    assert manual["status"] == "applied" and again.read("status")["paused"] is True
    decide_and_apply(again, approvals, "resume", {}, authorize)
    assert again.run_scheduled(authorize=lambda _payload: "grant")["reason"] == "already_ran_today"


def test_corrupt_state_and_usage_refuse_without_mutation(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    ops.state_dir.mkdir()
    ops.state_file.write_text("{bad", encoding="utf-8")
    assert ops.preview("archive", {"name": "agent"})["reason"] == "state_unreadable"
    assert ops.read("ledger")["status"] == "refused"
    ops.state_file.unlink()
    usage.path.write_text("{bad", encoding="utf-8")
    fresh = CuratorOperations(loader, usage, ops.curator, approvals,
                              state_dir=tmp_path / "fresh-operations", archive_dir=ops.archive_dir,
                              get_setting=ops.get_setting, holders=ops.holders)
    assert fresh.preview("archive", {"name": "agent"})["reason"] == "usage_unreadable"
    assert approvals.list() == []


def test_approval_and_kernel_rechecked_before_effect(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    preview = ops.preview("archive", {"name": "agent"})
    pending = ops.request("archive", {"name": "agent"},
                          preview_fingerprint=preview["preview_fingerprint"], actor="owner", authorize=authorize)
    approvals.decide(pending["card_id"], True, by="user")
    assert ops.apply_decision(pending["card_id"], authorize=lambda _payload: ["grant"])["status"] == "refused"
    assert skill.path.is_dir()
    assert ops.apply_decision(pending["card_id"], authorize=authorize)["status"] == "applied"


def test_backup_with_unsafe_member_refuses_rollback_preview(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    saved = decide_and_apply(ops, approvals, "backup", {}, authorize)
    path = ops.backup_dir / f"{saved['backup_id']}.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        body = b"evil"
        member = tarfile.TarInfo("../../escape")
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))
    assert ops.preview("rollback", {"backup_id": saved["backup_id"]})["status"] == "refused"


def test_approved_proposal_pass_has_durable_before_after_receipt(tmp_path):
    loader, usage, _approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)

    class Proposals:
        def list(self, status):
            return [{"skill": "agent"}] if status == "approved" else []

    class Curator:
        _proposals = Proposals()

        def apply_decisions(self):
            (skill.path / "SKILL.md").write_text("# patched\n", encoding="utf-8")
            return {"applied": ["agent"], "outcomes": [{"skill": "agent", "proposal_id": "p1", "ok": True}]}

    ops.curator = Curator()
    result = ops.apply_proposals()
    assert result["status"] == "applied"
    entry = ops.read("ledger")["items"][0]
    assert entry["operation"] == "approved_proposals" and entry["targets"] == ["agent"]
    assert entry["before"]["agent"] != entry["after"]["agent"]


def test_archive_control_metadata_drift_refuses_restore_and_recoverable_listing(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    decide_and_apply(ops, approvals, "archive", {"name": "agent"}, authorize)
    archive_id = ops.read("list-archived")["items"][0]["id"]
    (ops.archive_dir / archive_id / "SKILL.sig").write_text("forged", encoding="utf-8")
    assert ops.preview("restore", {"archive_id": archive_id})["reason"] == "archive_drifted"
    assert ops.read("list-archived")["status"] == "refused"


def test_rollback_itself_is_recoverable_for_state_and_snapshot(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    pin = decide_and_apply(ops, approvals, "pin", {"name": "agent"}, authorize)
    undone_pin = decide_and_apply(ops, approvals, "rollback", {"ledger_id": pin["ledger_id"]}, authorize)
    assert usage.get("agent")["pinned"] is False
    assert decide_and_apply(ops, approvals, "rollback", {"ledger_id": undone_pin["ledger_id"]}, authorize)["status"] == "applied"
    assert usage.get("agent")["pinned"] is True
    decide_and_apply(ops, approvals, "unpin", {"name": "agent"}, authorize)
    backup = decide_and_apply(ops, approvals, "backup", {}, authorize)
    decide_and_apply(ops, approvals, "archive", {"name": "agent"}, authorize)
    restored = decide_and_apply(ops, approvals, "rollback", {"backup_id": backup["backup_id"]}, authorize)
    assert skill.path.exists()
    assert decide_and_apply(ops, approvals, "rollback", {"ledger_id": restored["ledger_id"]}, authorize)["status"] == "applied"
    assert not skill.path.exists()
    assert ops.read("list-archived")["items"]


def test_backup_refuses_an_incomplete_generated_dependency_snapshot(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    skill = loader.add("agent", tmp_path / "agent")
    (skill.path / "node_modules").mkdir()
    (skill.path / "node_modules" / "generated.js").write_text("generated", encoding="utf-8")
    usage.note_created("agent", ORIGIN_AGENT)
    result = ops.preview("backup", {})
    assert result["status"] == "refused" and result["reason"] == "backup_excluded_artifacts"
    assert approvals.list() == []
    assert not ops.read("backups")["items"]


def test_snapshot_rollback_refuses_new_managed_skill_without_losing_activity(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("a", tmp_path / "a")
    usage.note_created("a", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    saved = decide_and_apply(ops, approvals, "backup", {}, authorize)
    loader.add("b", tmp_path / "b")
    usage.note_created("b", ORIGIN_AGENT)
    usage.bump("a", "use")
    assert ops.preview("rollback", {"backup_id": saved["backup_id"]})["reason"] == "snapshot_scope_changed"
    assert (tmp_path / "b" / "SKILL.md").is_file()
    assert usage.get("a")["use_count"] == 1


def test_pin_rollback_preserves_later_telemetry_on_unmanaged_skill(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("owner", tmp_path / "owner")
    authorize, _ = gate("queue")
    pinned = decide_and_apply(ops, approvals, "pin", {"name": "owner"}, authorize)
    usage.bump("owner", "use")
    assert decide_and_apply(ops, approvals, "rollback", {"ledger_id": pinned["ledger_id"]}, authorize)["status"] == "applied"
    assert usage.get("owner")["pinned"] is False
    assert usage.get("owner")["use_count"] == 1


def test_old_pin_and_pause_rollback_refuse_after_later_same_value_control(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    first_pin = decide_and_apply(ops, approvals, "pin", {"name": "agent"}, authorize)
    decide_and_apply(ops, approvals, "unpin", {"name": "agent"}, authorize)
    decide_and_apply(ops, approvals, "pin", {"name": "agent"}, authorize)
    assert ops.preview("rollback", {"ledger_id": first_pin["ledger_id"]})["reason"] == "rollback_superseded"
    first_pause = decide_and_apply(ops, approvals, "pause", {}, authorize)
    decide_and_apply(ops, approvals, "resume", {}, authorize)
    decide_and_apply(ops, approvals, "pause", {}, authorize)
    assert ops.preview("rollback", {"ledger_id": first_pause["ledger_id"]})["reason"] == "rollback_superseded"


def test_snapshot_scope_detects_new_archive_and_restored_skill_keeps_new_activity(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("a", tmp_path / "a")
    usage.note_created("a", ORIGIN_AGENT)
    authorize, _ = gate("queue")
    saved = decide_and_apply(ops, approvals, "backup", {}, authorize)
    decide_and_apply(ops, approvals, "archive", {"name": "a"}, authorize)
    usage.bump("a", "use")
    assert decide_and_apply(ops, approvals, "rollback", {"backup_id": saved["backup_id"]}, authorize)["status"] == "applied"
    assert usage.get("a")["use_count"] == 1
    loader.add("b", tmp_path / "b")
    usage.note_created("b", ORIGIN_AGENT)
    decide_and_apply(ops, approvals, "archive", {"name": "b"}, authorize)
    assert ops.preview("rollback", {"backup_id": saved["backup_id"]})["reason"] == "snapshot_scope_changed"


def test_legacy_status_projects_committed_run_without_private_receipts(tmp_path):
    loader, usage, approvals, ops = setup(tmp_path)
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    ops.get_setting = lambda key, default=None: True if key == "cognition.review_enabled" else default
    assert ops.legacy_status() == {"available": True, "last_run": None, "last_result": None}
    authorize, _ = gate("queue")
    assert decide_and_apply(ops, approvals, "run", {}, authorize)["status"] == "applied"
    report = ops.legacy_status()
    assert report["last_run"] == datetime.now(UTC).date().isoformat()
    assert report["last_result"]["date"] == report["last_run"]
    assert set(report["last_result"]["lifecycle"]) == {"considered", "stale", "archived"}
    assert str(tmp_path) not in str(report)


def test_quarantined_skill_does_not_block_the_lifecycle_pass(tmp_path):
    loader, usage, _approvals, ops = setup(tmp_path)
    ops.get_setting = lambda key, default=None: True if key == "cognition.review_enabled" else default
    loader.add("waiting", tmp_path / "waiting")
    usage.note_created("waiting", ORIGIN_AGENT)
    (tmp_path / "waiting" / "PENDING_REVIEW").write_text("review", encoding="utf-8")
    loader.add("agent", tmp_path / "agent")
    usage.note_created("agent", ORIGIN_AGENT)
    # A skill awaiting review is skipped by the pass, not a reason to refuse the whole pass...
    assert ops.preview("run", {})["status"] != "refused"
    # ...while naming it directly still refuses.
    assert ops.preview("pin", {"name": "waiting"})["status"] == "refused"
