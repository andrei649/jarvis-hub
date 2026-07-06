"""H20.5 live wave — skill usage telemetry, lifecycle + nightly curator. Offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from datetime import datetime, timedelta, timezone

from agents.core.skills.curator import SkillCurator
from agents.core.skills.proposals import (
    SkillProposalStore,
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_STALE,
)
from agents.core.skills.usage import (
    ORIGIN_AGENT,
    ORIGIN_BUNDLED,
    STATE_ACTIVE,
    STATE_ARCHIVED,
    STATE_STALE,
    SkillUsageStore,
)


class _FakeLoader:
    def __init__(self, tmp_path):
        self.skills = {}
        self._tmp = tmp_path

    def add(self, name, content="# skill\nbody"):
        d = self._tmp / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(content, encoding="utf-8")

        class S:
            path = d
        self.skills[name] = S()
        return d

    def _load_skill(self, path):        # curator calls this after a patch apply
        pass


def _store(tmp_path):
    return SkillUsageStore(path=tmp_path / "usage.json")


# ── usage store ──────────────────────────────────────────────────────────────

def test_bump_counts_and_reactivates_stale(tmp_path):
    u = _store(tmp_path)
    u.note_created("s1", ORIGIN_AGENT)
    u.set_state("s1", STATE_STALE)
    u.bump("s1", "use")
    rec = u.get("s1")
    assert rec["use_count"] == 1 and rec["last_used_at"]
    assert rec["state"] == STATE_ACTIVE          # activity reactivates


def test_curatable_requires_agent_origin_and_unpinned(tmp_path):
    u = _store(tmp_path)
    u.note_created("agent_skill", ORIGIN_AGENT)
    u.note_created("bundled_skill", ORIGIN_BUNDLED)
    assert u.curatable("agent_skill") is True
    assert u.curatable("bundled_skill") is False
    assert u.curatable("never_seen") is False
    u.pin("agent_skill")
    assert u.curatable("agent_skill") is False


# ── curator lifecycle ────────────────────────────────────────────────────────

def _curator(loader, usage, tmp_path, now, proposals=None, approvals=None):
    return SkillCurator(loader, usage, proposals=proposals, approvals=approvals,
                        archive_dir=tmp_path / "archive", now=lambda: now,
                        get_setting=lambda k, d=None: d)


async def test_idle_agent_skill_goes_stale_then_archived(tmp_path):
    loader = _FakeLoader(tmp_path)
    loader.add("old_skill")
    usage = _store(tmp_path)
    usage.note_created("old_skill", ORIGIN_AGENT)

    base = datetime.now(timezone.utc)
    # 40 days idle → stale
    cur = _curator(loader, usage, tmp_path, base + timedelta(days=40))
    out = await cur.run()
    assert out["lifecycle"]["stale"] == ["old_skill"]
    assert usage.get("old_skill")["state"] == STATE_STALE
    # 100 days idle → archived: dir moves, skill unloads
    cur2 = _curator(loader, usage, tmp_path, base + timedelta(days=100))
    out2 = await cur2.run()
    assert out2["lifecycle"]["archived"] == ["old_skill"]
    assert "old_skill" not in loader.skills
    assert (tmp_path / "archive" / "old_skill" / "SKILL.md").exists()
    assert usage.get("old_skill")["state"] == STATE_ARCHIVED


async def test_bundled_and_pinned_skills_never_touched(tmp_path):
    loader = _FakeLoader(tmp_path)
    loader.add("bundled")
    loader.add("pinned_agent")
    usage = _store(tmp_path)
    usage.note_created("bundled", ORIGIN_BUNDLED)
    usage.note_created("pinned_agent", ORIGIN_AGENT)
    usage.pin("pinned_agent")

    cur = _curator(loader, usage, tmp_path,
                   datetime.now(timezone.utc) + timedelta(days=365))
    out = await cur.run()
    assert out["lifecycle"]["archived"] == [] and out["lifecycle"]["stale"] == []
    assert "bundled" in loader.skills and "pinned_agent" in loader.skills


async def test_recent_activity_keeps_skill_active(tmp_path):
    loader = _FakeLoader(tmp_path)
    loader.add("fresh")
    usage = _store(tmp_path)
    usage.note_created("fresh", ORIGIN_AGENT)
    usage.bump("fresh", "use")
    cur = _curator(loader, usage, tmp_path,
                   datetime.now(timezone.utc) + timedelta(days=10))
    out = await cur.run()
    assert out["lifecycle"]["stale"] == [] and out["lifecycle"]["archived"] == []


async def test_curator_idempotent_per_day(tmp_path):
    loader = _FakeLoader(tmp_path)
    usage = _store(tmp_path)
    now = datetime.now(timezone.utc)
    cur = _curator(loader, usage, tmp_path, now)
    first = await cur.run()
    assert "lifecycle" in first
    second = await cur.run()
    assert second == {"skipped": True, "reason": "already_ran_today"}


# ── proposals: approve → curator applies (hash-checked, reversible) ──────────

async def test_approved_proposal_applied_with_backup(tmp_path):
    loader = _FakeLoader(tmp_path)
    loader.add("weather", "# Weather\nv1")
    usage = _store(tmp_path)
    usage.note_created("weather", ORIGIN_AGENT)
    props = SkillProposalStore(path=tmp_path / "p.json")
    rec = props.propose("weather", "# Weather\nv1", "# Weather\nv2 improved")
    props.mark(rec["id"], STATUS_APPROVED)

    cur = _curator(loader, usage, tmp_path, datetime.now(timezone.utc),
                   proposals=props)
    out = await cur.run()
    assert out["proposals"]["applied"] == ["weather"]
    md = (loader.skills["weather"].path / "SKILL.md").read_text(encoding="utf-8")
    assert md == "# Weather\nv2 improved"
    assert props.get(rec["id"])["status"] == STATUS_APPLIED
    backups = list((tmp_path / "archive").glob("weather-*.SKILL.md"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "# Weather\nv1"


async def test_drifted_proposal_marked_stale_not_applied(tmp_path):
    loader = _FakeLoader(tmp_path)
    loader.add("weather", "# Weather\nv1")
    props = SkillProposalStore(path=tmp_path / "p.json")
    rec = props.propose("weather", "# Weather\nv1", "# Weather\nv2")
    props.mark(rec["id"], STATUS_APPROVED)
    # skill drifts after the proposal was computed
    (loader.skills["weather"].path / "SKILL.md").write_text(
        "# Weather\nsomeone edited this", encoding="utf-8")

    cur = _curator(loader, _store(tmp_path), tmp_path,
                   datetime.now(timezone.utc), proposals=props)
    out = await cur.run()
    assert out["proposals"]["applied"] == []
    assert props.get(rec["id"])["status"] == STATUS_STALE
    md = (loader.skills["weather"].path / "SKILL.md").read_text(encoding="utf-8")
    assert "someone edited this" in md            # newer content preserved


async def test_approval_queue_decisions_sync_to_ledger(tmp_path):
    loader = _FakeLoader(tmp_path)
    loader.add("s", "# S\nv1")
    props = SkillProposalStore(path=tmp_path / "p.json")
    rec = props.propose("s", "# S\nv1", "# S\nv2")

    class _Approvals:
        def list(self, status=None):
            if status == "approved":
                return [{"tool": "skill.patch_proposal",
                         "args": {"skill": "s", "proposal_id": rec["id"]}}]
            return []

    cur = _curator(loader, _store(tmp_path), tmp_path,
                   datetime.now(timezone.utc), proposals=props,
                   approvals=_Approvals())
    out = await cur.run()
    assert out["proposals"]["applied"] == ["s"]
    assert props.get(rec["id"])["status"] == STATUS_APPLIED


def test_proposal_dedupe_and_noop_rejection(tmp_path):
    props = SkillProposalStore(path=tmp_path / "p.json")
    assert props.propose("s", "same", "same") is None            # no-op change
    a = props.propose("s", "v1", "v2")
    b = props.propose("s", "v1", "v2")                           # identical pending
    assert a["id"] == b["id"]
    assert len(props.list(STATUS_PENDING)) == 1
