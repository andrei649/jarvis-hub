"""A real inbound circuit gate suppresses calls and owns one recovery probe."""

from agents.core.channels.reconnect import PollingCircuit


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_fifth_failure_opens_and_only_one_recovery_probe_enters():
    clock = Clock()
    circuit = PollingCircuit(clock=clock)
    for _ in range(4):
        lease, wait = circuit.admit()
        assert lease is not None and wait == 0
        assert circuit.admit() == (None, 1.0)
        assert circuit.failure(lease) == 0
        assert circuit.snapshot()["state"] == "closed"
    lease, _ = circuit.admit()
    assert circuit.failure(lease) == 120
    assert circuit.snapshot()["state"] == "open"
    assert circuit.admit() == (None, 120)
    clock.advance(119)
    assert circuit.admit() == (None, 1)
    clock.advance(1)
    probe, wait = circuit.admit()
    assert probe is not None and wait == 0
    assert circuit.snapshot()["state"] == "half_open"
    assert circuit.admit() == (None, 1.0)
    assert circuit.failure(probe) == 120
    assert circuit.snapshot()["state"] == "open"


def test_success_closes_and_old_lease_cannot_change_a_new_probe():
    clock = Clock()
    circuit = PollingCircuit(clock=clock, failure_threshold=1)
    first, _ = circuit.admit()
    assert circuit.failure(first) == 120
    clock.advance(120)
    second, _ = circuit.admit()
    assert circuit.success(first) is False
    assert circuit.release(first) is False
    assert circuit.failure(first) == 0
    assert circuit.snapshot()["state"] == "half_open"
    assert circuit.success(second) is True
    assert circuit.snapshot() == {
        "state": "closed", "failures": 0, "retry_in_s": 0, "probe_active": False,
    }
    third, _ = circuit.admit()
    assert third is not None and third is not second
    assert circuit.failure(second) == 0
    assert circuit.release(third) is True


def test_server_retry_after_never_admits_early_even_before_threshold():
    clock = Clock()
    circuit = PollingCircuit(clock=clock)
    lease, _ = circuit.admit()
    assert circuit.failure(lease, retry_after=300) == 300
    assert circuit.snapshot()["state"] == "closed"
    clock.advance(299)
    assert circuit.admit() == (None, 1)
    clock.advance(1)
    assert circuit.admit()[0] is not None


def test_stable_stream_closes_circuit_but_remains_the_only_active_lease():
    clock = Clock()
    circuit = PollingCircuit(clock=clock, failure_threshold=2)
    failed, _ = circuit.admit()
    circuit.failure(failed)
    failed, _ = circuit.admit()
    circuit.failure(failed)
    clock.advance(120)
    stream, _ = circuit.admit()
    assert circuit.mark_healthy(stream) is True
    assert circuit.snapshot() == {
        "state": "closed", "failures": 0, "retry_in_s": 0, "probe_active": True,
    }
    assert circuit.admit() == (None, 1.0)
    assert circuit.failure(stream) == 0
    assert circuit.snapshot()["failures"] == 1
    assert circuit.snapshot()["state"] == "closed"
    next_stream, _ = circuit.admit()
    assert next_stream is not None
    assert circuit.release(next_stream) is True


def test_reset_refuses_active_transport_and_stale_other_gate_lease():
    clock = Clock()
    circuit = PollingCircuit(clock=clock, failure_threshold=1)
    other = PollingCircuit(clock=clock)
    lease, _ = circuit.admit()
    assert circuit.reset() is False
    assert other.success(lease) is False
    assert other.failure(lease) == 0
    assert other.release(lease) is False
    assert circuit.release(lease) is True
    assert circuit.reset() is True
    assert circuit.snapshot()["state"] == "closed"


def test_aborted_half_open_probe_reopens_without_counting_transient_failure():
    clock = Clock()
    circuit = PollingCircuit(clock=clock, failure_threshold=1)
    lease, _ = circuit.admit()
    circuit.failure(lease)
    clock.advance(120)
    probe, _ = circuit.admit()
    assert circuit.release(probe) is True
    assert circuit.snapshot()["failures"] == 1
    assert circuit.snapshot()["state"] == "open"
    assert circuit.admit() == (None, 120)
