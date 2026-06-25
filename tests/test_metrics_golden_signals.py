"""AUD-17 — HTTP golden-signals (/metrics) + a real-path concurrency/p95 check.

Two layers:
  * unit — the collector counts, renders valid Prometheus exposition, collapses
    cardinality by route template, and tracks 5xx + in-flight;
  * integration — GET /metrics serves the Prometheus payload, the middleware
    records real requests under their route *template* (not the raw path), and a
    burst of concurrent real requests keeps p95 latency under a budget with no
    in-flight leak.
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.observability.http_metrics import (
    HTTP_METRICS,
    PROM_CONTENT_TYPE,
    HTTPMetrics,
)

# Generous ceiling: a no-op in-process route should be milliseconds; 2s leaves
# huge headroom for a loaded CI runner while still failing on a real regression
# (e.g. a blocking call sneaking onto the request path). Override per-env.
_P95_BUDGET_S = float(os.environ.get("JARVIS_METRICS_P95_BUDGET_S", "2.0"))


# ── unit: the collector in isolation ─────────────────────────────────────────

def test_collector_counts_and_renders_exposition():
    m = HTTPMetrics()
    m.record("GET", "/healthz", 200, 0.001)
    m.record("get", "/healthz", 200, 0.003)          # method normalized to upper
    m.record("POST", "/api/x", 500, 0.010)
    text = m.render()

    # counter series
    assert 'jarvis_http_requests_total{method="GET",route="/healthz",status="200"} 2' in text
    assert 'jarvis_http_requests_total{method="POST",route="/api/x",status="500"} 1' in text
    # summary type + quantiles + _sum/_count
    assert "# TYPE jarvis_http_request_duration_seconds summary" in text
    assert 'jarvis_http_request_duration_seconds{method="GET",route="/healthz",quantile="0.95"}' in text
    assert 'jarvis_http_request_duration_seconds_count{method="GET",route="/healthz"} 2' in text
    # 5xx error counter
    assert 'jarvis_http_errors_total{method="POST",route="/api/x"} 1' in text
    # gauge present and HELP/TYPE for every metric family
    assert "# TYPE jarvis_http_requests_in_flight gauge" in text
    assert text.count("# HELP ") == 4


def test_collector_collapses_by_template_not_raw_path():
    """The collector keys on whatever route string it's handed — the middleware
    feeds it the template, so per-id traffic must collapse to ONE series."""
    m = HTTPMetrics()
    for _ in range(5):
        m.record("GET", "/api/agents/{agent_id}/soul", 200, 0.002)
    assert m.count("GET", "/api/agents/{agent_id}/soul") == 5
    # exactly one duration series for that template
    assert m.render().count(
        'jarvis_http_request_duration_seconds_count{method="GET",route="/api/agents/{agent_id}/soul"}'
    ) == 1


def test_collector_in_flight_and_quantile():
    m = HTTPMetrics()
    m.inc_in_flight()
    m.inc_in_flight()
    assert m.in_flight == 2
    m.dec_in_flight()
    assert m.in_flight == 1
    assert m.quantile("GET", "/nope", 0.95) is None      # no samples
    for v in (0.01, 0.02, 0.03, 0.04):
        m.record("GET", "/r", 200, v)
    p95 = m.quantile("GET", "/r", 0.95)
    assert p95 is not None and 0.03 <= p95 <= 0.04


def test_label_values_are_escaped():
    m = HTTPMetrics()
    m.record("GET", '/weird"\\path', 200, 0.001)
    assert r'route="/weird\"\\path"' in m.render()


# ── integration: live app ────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    import agents.web as web
    with TestClient(web.app) as c:
        yield c


def test_metrics_endpoint_serves_prometheus(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"] == PROM_CONTENT_TYPE
    body = r.text
    for family in (
        "jarvis_http_requests_total",
        "jarvis_http_request_duration_seconds",
        "jarvis_http_errors_total",
        "jarvis_http_requests_in_flight",
    ):
        assert family in body


def test_middleware_records_requests_under_route_template(client):
    """Hitting a param route with two distinct ids records ONE template series,
    never the concrete ids — proof the middleware uses scope['route'].path."""
    before = HTTP_METRICS.count("GET", "/api/agents/{agent_id}/soul")
    for agent_id in ("jarvis", "friday"):
        client.get(f"/api/agents/{agent_id}/soul")        # status irrelevant; route matched
    after = HTTP_METRICS.count("GET", "/api/agents/{agent_id}/soul")
    assert after - before == 2
    body = client.get("/metrics").text
    assert 'route="/api/agents/{agent_id}/soul"' in body
    assert "/api/agents/jarvis/soul" not in body          # no per-id cardinality blow-up


def test_unmatched_paths_fold_into_one_series(client):
    before = HTTP_METRICS.count("GET", "<unmatched>")
    assert client.get("/no-such-route-xyz").status_code == 404
    assert client.get("/another-missing-abc").status_code == 404
    assert HTTP_METRICS.count("GET", "<unmatched>") - before == 2


def test_concurrent_real_requests_meet_p95_budget_without_leak(client):
    """Drive a burst of concurrent real requests through the full middleware
    stack; assert p95 latency is measured and within budget, with no in-flight
    leak once the burst drains (RED 'duration' under concurrency)."""
    HTTP_METRICS.reset()
    N, WORKERS = 60, 10

    def hit():
        return client.get("/healthz").status_code

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda _: hit(), range(N)))

    assert results == [200] * N
    assert HTTP_METRICS.count("GET", "/healthz") == N
    p95 = HTTP_METRICS.quantile("GET", "/healthz", 0.95)
    assert p95 is not None, "no latency samples recorded"
    assert p95 < _P95_BUDGET_S, f"p95 {p95:.3f}s exceeded budget {_P95_BUDGET_S}s"

    # in-flight must settle back to 0 (give the gauge a beat to drain).
    deadline = time.monotonic() + 2.0
    while HTTP_METRICS.in_flight > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert HTTP_METRICS.in_flight == 0
