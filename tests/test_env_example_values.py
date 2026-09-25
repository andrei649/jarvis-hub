"""Every value in .env.example is what an owner who copies it gets.

The packaged install copies .env.example to the owner's .env (ensure_user_home), and
python-dotenv reads `KEY=   # comment` as the value "# comment": the comment became
the setting. JARVIS_DRIVE_AI_REMOTE turned the Drive sync's remote into a sentence,
the backup caps stopped being numbers, and JARVIS_FORGET_ARCHIVE_DIR wrote every
pre-forget archive into a directory named "# default: a sibling of the data root" in
the working directory. A comment for an empty value belongs on its own line.
"""
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[1]


def test_no_value_in_the_example_is_a_comment():
    values = dotenv_values(REPO / ".env.example")
    assert values, "the example declares settings"
    commented = sorted(key for key, value in values.items() if (value or "").lstrip().startswith("#"))
    assert commented == []


def test_an_empty_example_value_stays_empty():
    values = dotenv_values(REPO / ".env.example")
    for key in ("JARVIS_FORGET_ARCHIVE_DIR", "JARVIS_DRIVE_AI_REMOTE", "JARVIS_BACKUP_MAX_BYTES"):
        assert values[key] == ""
