"""Directly collected Nerva E1.1 contract assertions."""

from tests._nerva_e1_1_checks import run_e1_1_checks
from tests.nerva_check_cases import case, collected_test

NERVA_E1_1_CASES = (
    case("e1.1", run_e1_1_checks, name="contract-privacy-failure-ledger"),
)

test_nerva_e1_1 = collected_test(NERVA_E1_1_CASES)
