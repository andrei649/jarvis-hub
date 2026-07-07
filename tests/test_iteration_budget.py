"""H20.x — IterationBudget consume/refund counter. All offline."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.iteration_budget import IterationBudget


def test_consume_until_cap():
    b = IterationBudget(2)
    assert b.consume() is True
    assert b.consume() is True
    assert b.consume() is False          # cap reached
    assert b.used == 2 and b.remaining == 0


def test_refund_gives_back_an_iteration():
    b = IterationBudget(1)
    assert b.consume() is True
    assert b.consume() is False
    b.refund()
    assert b.consume() is True           # refunded slot is usable again


def test_refund_never_goes_negative():
    b = IterationBudget(3)
    b.refund()
    assert b.used == 0 and b.remaining == 3


def test_zero_budget_denies_everything():
    b = IterationBudget(0)
    assert b.consume() is False
    assert b.remaining == 0


def test_status_shape():
    b = IterationBudget(5)
    b.consume()
    st = b.status()
    assert st == {"max_total": 5, "used": 1, "remaining": 4}
