"""H23.30 — `NERVA_PUBLIC_PROFILE` gates the personal knowledge-graph seed.

`seed_graph()` plants `SEED_FACTS` — real people (Andrei/Alexandra/Max), a real
employer, a real village and a real car — into any empty graph on first boot.
That is correct for the owner's private install and wrong for the public
digitaholic.ro demo box, where a stranger would be talking to a Nerva that
already "knows" the owner's family.

The gate lives inside `seed_graph()` itself, not at the single
`MemoryManager.__init__` call site: the seed is the thing that must never fire
on a public box, so no present or future caller can bypass it.

Spec: docs/decisions/2026-08-24-public-web-demo-digitaholic.md
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.memory.graph import InMemoryGraph
from agents.core.memory.manager import MemoryManager
from agents.core.memory.seed_graph import SEED_FACTS, seed_graph

# The names a public visitor must never find pre-loaded in the graph.
PERSONAL_ENTITIES = ["Andrei", "Alexandra", "Max", "Raiffeisen", "Cosmina de Sus", "BMW E93"]


def _seeded_entity_names(graph) -> list[str]:
    return [name for name in PERSONAL_ENTITIES if graph.get_entity(name) is not None]


class TestPublicProfileGate:
    def test_default_still_seeds(self, monkeypatch):
        """Unset flag = owner's private install: behavior is unchanged."""
        monkeypatch.delenv("NERVA_PUBLIC_PROFILE", raising=False)
        graph = InMemoryGraph()

        assert seed_graph(graph) > 0
        assert _seeded_entity_names(graph) == PERSONAL_ENTITIES

    def test_public_profile_skips_seeding(self, monkeypatch):
        """NERVA_PUBLIC_PROFILE=1 = public box: no personal fact is planted."""
        monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "1")
        graph = InMemoryGraph()

        assert seed_graph(graph) == 0
        assert _seeded_entity_names(graph) == []

    def test_public_profile_accepts_every_truthy_spelling(self, monkeypatch):
        """The flag reads through the shared env_config parse, not a local one."""
        for spelling in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("NERVA_PUBLIC_PROFILE", spelling)
            graph = InMemoryGraph()

            assert seed_graph(graph) == 0, f"{spelling!r} should read as public"
            assert _seeded_entity_names(graph) == []

    def test_explicit_falsy_still_seeds(self, monkeypatch):
        """An operator who explicitly turns the flag off keeps the private seed."""
        for spelling in ("0", "false", "off"):
            monkeypatch.setenv("NERVA_PUBLIC_PROFILE", spelling)
            graph = InMemoryGraph()

            assert seed_graph(graph) > 0, f"{spelling!r} should read as private"

    def test_malformed_value_falls_back_to_seeding(self, monkeypatch):
        """RESIDUAL, pinned deliberately: a typo means *private*, so it seeds.

        `env_config.truthy` resolves unrecognized spellings to the flag's
        declared default in both directions, and this flag is a default-off
        opt-in. So `NERVA_PUBLIC_PROFILE=pubic` deploys a public box that seeds
        the owner's family into a stranger's graph.

        This is the repo-wide AUD-14 convention (one parse home, no local
        boolean dialects) and this test does not change it — it makes the
        parse-level behaviour visible instead of silent.

        The typo can no longer reach a *running* box: `boot_guards.
        assert_parseable_posture_flags` (DRA-07/DRA-14, see
        tests/test_public_profile_boot_guard.py) refuses to start when the flag
        is set-but-unparseable, from both documented entry points. `seed_graph`
        itself is deliberately unchanged, which is exactly what this test pins.
        """
        monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "pubic")
        graph = InMemoryGraph()

        assert seed_graph(graph) > 0
        assert _seeded_entity_names(graph) == PERSONAL_ENTITIES

    def test_seed_facts_are_not_reachable_without_the_seed_call(self, monkeypatch):
        """The gate is on the seed, so the fact table alone plants nothing."""
        monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "1")
        graph = InMemoryGraph()
        seed_graph(graph)

        assert SEED_FACTS, "the fact table still exists for the private install"
        assert graph.get_entity("Andrei") is None


class TestMemoryManagerIntegration:
    def test_manager_boot_is_clean_on_a_public_box(self, monkeypatch):
        """The real call site: constructing MemoryManager plants nothing."""
        monkeypatch.setenv("NERVA_PUBLIC_PROFILE", "1")

        manager = MemoryManager(graph_backend="memory", vector_backend="memory")

        assert _seeded_entity_names(manager.graph) == []

    def test_manager_boot_still_seeds_the_private_install(self, monkeypatch):
        monkeypatch.delenv("NERVA_PUBLIC_PROFILE", raising=False)

        manager = MemoryManager(graph_backend="memory", vector_backend="memory")

        assert _seeded_entity_names(manager.graph) == PERSONAL_ENTITIES
