# Test suite

**1,520+ tests, fully offline** (mocked LLMs, channels, hardware). Run:

```bash
python -m pytest                       # whole suite (~65s)
python -m pytest tests/test_h10_3_transform_nodes.py   # one file
python -m pytest -k "arena or quality" # by keyword
python -m pytest -q -p no:cacheprovider
```

> **Optional dep:** `tests/test_heartbeat.py` (4 tests) needs **`apscheduler`**
> (`pip install apscheduler`); without it those 4 fail locally. CI has it.

## Naming conventions

- **`test_hXX_Y_*.py`** — maps to a backlog item (`BACKLOG.md`). E.g.
  `test_h10_19_model_arena.py` = item **H10.19**. This is the fastest way to find
  the tests for a feature: look up the item in `BACKLOG.md`, grep the code.
- **`test_<area>.py`** — area suites (`test_autonomy*`, `test_admin*`,
  `test_workflows*`, `test_memory*`, `test_security*`, …).

## What's covered (by area)

| Area | Example test files | Covers |
|------|--------------------|--------|
| Workflows | `test_h10_3/4/6/9/11/14`, `test_workflows`, `test_h10_15_critic_node` | engine, step kinds (transform/guardrail/loop/subflow/router/critic), hierarchical, flow-decorator |
| Observability / eval | `test_h10_23_quality_monitor`, `test_h10_25_review_queue`, `test_h10_2_workflow_trace` | quality monitor + alert, review queue, tracer, datasets |
| Autonomy | `test_h12_5_autonomy_dryrun`, `test_h10_18_action_approvals`, `test_h12_11_escalation`, `test_h7_11_learning_loop_schedule` | dry-run, action approvals, escalation, learning-loop proposals |
| Memory | `test_h14_*`, `test_memory*`, `test_json_store_base` | bi-temporal KG, decay/forgetting, consolidation, eval harness, JsonStore base |
| Security | `test_h17_*`, `test_h15_4_secret_broker`, `test_h16_1_mcp_oauth` | quarantine, capability/kill-switch, audit anchor, secret broker, MCP OAuth |
| Collaboration / UI | `test_h10_1_chat_widget`, `test_h10_20_chat_rooms`, `test_h10_21_conversation_notes` | widget, rooms, notes |
| Channels / inbound | `test_h16_4_signed_triggers`, channel adapters | signed webhooks, channel round-trips (mocked) |
| LLM | `test_h13_2_grammar`, tokenizer/cost tests | GBNF grammar gen, cost, tiering |

## Conventions

- Tests are **offline + deterministic**: network is guarded, LLMs are mocked or
  injected (`handle_input` stubs), randomness is seeded.
- Endpoint tests use `fastapi.testclient.TestClient`, which triggers real app
  startup (lifespan) — so they exercise the wired orchestrator.
- Stores under test take a `tmp_path` (or `path=None` in-memory) for isolation.

See **`docs/MANUAL_TESTING.md`** for everything the offline suite *cannot* cover
(real models, live channels, external services, HUD rendering).
