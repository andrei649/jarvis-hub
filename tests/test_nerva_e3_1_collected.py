"""Directly collected Nerva E3.1 comparison assertions."""

from tests._nerva_e3_1_checks import run_e3_1_checks
from tests.nerva_check_cases import case, collected_test

NERVA_E3_1_CASES = (
    case("e3.1", run_e3_1_checks, name="episode-comparison-contract"),
)

test_nerva_e3_1 = collected_test(NERVA_E3_1_CASES)
