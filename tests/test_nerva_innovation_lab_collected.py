"""Directly collected Innovation Lab hostile matrix."""

from tests._nerva_innovation_lab_checks import run_checks
from tests.nerva_check_cases import case, collected_test

NERVA_INNOVATION_LAB_CASES = (
    case("innovation-lab", run_checks, name="fail-closed-hostile-matrix"),
)

test_nerva_innovation_lab = collected_test(NERVA_INNOVATION_LAB_CASES)
