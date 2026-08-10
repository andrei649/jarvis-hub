"""Directly collected Nerva E3.0 Episodes assertions."""

from tests._nerva_e3_0_checks import run_e3_0_checks
from tests.nerva_check_cases import case, collected_test

NERVA_E3_0_CASES = (
    case("e3.0", run_e3_0_checks, fixtures=("tmp_path",), name="episodes-contract"),
)

test_nerva_e3_0 = collected_test(NERVA_E3_0_CASES)
