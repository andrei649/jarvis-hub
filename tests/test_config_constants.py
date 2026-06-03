"""Q4: centralized config constants are wired to the modules that use them."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.core import config


def test_limits_defined():
    assert config.NOTES_MAX_LEN == 20_000
    assert config.ROOM_HISTORY_CAP == 200
    assert config.RUN_HISTORY_MAX_PER_AGENT == 100


def test_modules_use_central_limits():
    from agents.core.notes import MAX_LEN
    from agents.core.rooms import _HISTORY_CAP
    from agents.core.run_history import MAX_PER_AGENT
    assert MAX_LEN == config.NOTES_MAX_LEN
    assert _HISTORY_CAP == config.ROOM_HISTORY_CAP
    assert MAX_PER_AGENT == config.RUN_HISTORY_MAX_PER_AGENT


def test_data_path_under_memory_dir():
    p = config.data_path("widgets.json")
    assert p.name == "widgets.json" and p.parent == config.MEMORY_DIR
