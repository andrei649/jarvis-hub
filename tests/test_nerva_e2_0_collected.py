"""Directly collected Nerva E2.0 Atlas assertions."""

from tests._nerva_e2_0_checks import run_e2_0_checks
from tests.nerva_check_cases import case, collected_test

NERVA_E2_0_CASES = (
    case("e2.0", run_e2_0_checks, fixtures=("tmp_path",), name="atlas-contract"),
)

test_nerva_e2_0 = collected_test(NERVA_E2_0_CASES)
