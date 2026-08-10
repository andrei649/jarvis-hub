"""Directly collected Nerva E3.0 revision assertions."""

from tests._nerva_e3_0_revision_checks import run_e3_0_revision_checks
from tests.nerva_check_cases import case, collected_test

NERVA_E3_0_REVISION_CASES = (
    case("e3.0", run_e3_0_revision_checks, name="revision-integrity"),
)

test_nerva_e3_0_revision = collected_test(NERVA_E3_0_REVISION_CASES)
