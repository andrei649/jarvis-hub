"""Everyone write rights are per access bit, not one boolean for the whole DACL."""

from agents.core.platform_files import (
    _INHERIT_ONLY,
    _INHERITED,
    _OBJECT_INHERIT,
    DELETE,
    FILE_APPEND_DATA,
    FILE_WRITE_DATA,
    FILE_WRITE_EA,
    GENERIC_WRITE,
    everyone_write_effective,
)

_ALLOW = 0
_DENY = 1


def test_deny_delete_does_not_cancel_file_write_data():
    """Codex review 4466592318: DENY DELETE + ALLOW FILE_WRITE_DATA is writable."""
    aces = [
        (_DENY, 0, DELETE),
        (_ALLOW, 0, FILE_WRITE_DATA),
    ]
    assert everyone_write_effective(aces, directory=False) is True
    assert everyone_write_effective(aces, directory=True) is True


def test_explicit_deny_of_a_write_bit_beats_an_explicit_allow_of_that_bit():
    aces = [
        (_ALLOW, 0, FILE_WRITE_DATA),
        (_DENY, 0, FILE_WRITE_DATA),
    ]
    assert everyone_write_effective(aces, directory=False) is False


def test_explicit_allow_beats_an_inherited_deny_of_the_same_bit():
    aces = [
        (_DENY, _INHERITED, FILE_WRITE_DATA),
        (_ALLOW, 0, FILE_WRITE_DATA),
    ]
    assert everyone_write_effective(aces, directory=False) is True


def test_inherited_deny_beats_an_inherited_allow():
    aces = [
        (_ALLOW, _INHERITED, FILE_WRITE_DATA),
        (_DENY, _INHERITED, FILE_WRITE_DATA),
    ]
    assert everyone_write_effective(aces, directory=False) is False


def test_inherit_only_and_the_other_object_kind_do_not_grant_write():
    inherit_only = [(_ALLOW, _INHERIT_ONLY | _OBJECT_INHERIT, FILE_WRITE_DATA)]
    assert everyone_write_effective(inherit_only, directory=False) is False
    # Inherited file-only ACE does not make the directory writable.
    file_only = [(_ALLOW, _INHERITED | _OBJECT_INHERIT, FILE_APPEND_DATA)]
    assert everyone_write_effective(file_only, directory=True) is False
    assert everyone_write_effective(file_only, directory=False) is True


def test_generic_write_and_write_ea_count_as_writable():
    assert everyone_write_effective([(_ALLOW, 0, GENERIC_WRITE)], directory=False) is True
    assert everyone_write_effective([(_ALLOW, 0, FILE_WRITE_EA)], directory=False) is True
    assert everyone_write_effective([(_ALLOW, 0, 0)], directory=False) is False
