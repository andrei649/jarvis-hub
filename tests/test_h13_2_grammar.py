"""Tests for H13.2 — Constrained decoding (GBNF grammar generation)."""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from agents.core.llm.grammar import json_schema_to_gbnf, tool_to_gbnf, validate_args

WEATHER = {
    "type": "object",
    "properties": {
        "city": {"type": "string"},
        "days": {"type": "integer"},
        "units": {"type": "string", "enum": ["metric", "imperial"]},
    },
    "required": ["city", "days"],
}


def _rules(gbnf: str) -> dict:
    out = {}
    for line in gbnf.splitlines():
        if "::=" in line:
            name, body = line.split("::=", 1)
            out[name.strip()] = body.strip()
    return out


# ── grammar generation ───────────────────────────────────────────────────────

def test_root_object_has_required_keys_in_order():
    g = json_schema_to_gbnf(WEATHER)
    rules = _rules(g)
    assert "root" in rules
    obj = rules[rules["root"]]                       # root references the object rule
    # required keys appear as literals, in order
    assert obj.index('\\"city\\"') < obj.index('\\"days\\"')


def test_primitive_rules_emitted():
    rules = _rules(json_schema_to_gbnf(WEATHER))
    assert "string" in rules and "integer" in rules and "ws" in rules


def test_boolean_rule_when_used():
    rules = _rules(json_schema_to_gbnf(
        {"type": "object", "properties": {"flag": {"type": "boolean"}}, "required": ["flag"]}))
    assert rules["boolean"] == '"true" | "false"'


def test_enum_becomes_alternation():
    g = json_schema_to_gbnf(WEATHER)
    # the enum values appear as quoted literals joined by |
    assert '"\\"metric\\""' in g and '"\\"imperial\\""' in g


def test_array_rule():
    schema = {"type": "object", "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
              "required": ["tags"]}
    rules = _rules(json_schema_to_gbnf(schema))
    arr = [b for n, b in rules.items() if n.startswith("array")]
    assert arr and '"["' in arr[0] and '"]"' in arr[0]


def test_nested_object():
    schema = {"type": "object", "properties": {
        "user": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        "required": ["user"]}
    g = json_schema_to_gbnf(schema)
    assert '\\"user\\"' in g and '\\"name\\"' in g


def test_tool_wrapper_shapes():
    openai = {"name": "f", "parameters": WEATHER}
    anthropic = {"name": "f", "input_schema": WEATHER}
    assert '\\"city\\"' in tool_to_gbnf(openai)
    assert '\\"city\\"' in tool_to_gbnf(anthropic)


# ── fallback validator ───────────────────────────────────────────────────────

def test_validate_args_ok_and_errors():
    assert validate_args({"city": "Cluj", "days": 3, "units": "metric"}, WEATHER)["ok"]
    bad = validate_args({"city": "Cluj"}, WEATHER)           # missing required 'days'
    assert bad["ok"] is False and any("days" in e for e in bad["errors"])
    wrong = validate_args({"city": 5, "days": 3}, WEATHER)   # city wrong type
    assert wrong["ok"] is False
    enum = validate_args({"city": "x", "days": 1, "units": "kelvin"}, WEATHER)
    assert enum["ok"] is False and any("enum" in e for e in enum["errors"])


def test_validate_nested_and_array():
    schema = {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "integer"}}}, "required": ["items"]}
    assert validate_args({"items": [1, 2, 3]}, schema)["ok"]
    assert validate_args({"items": [1, "two"]}, schema)["ok"] is False


# ── endpoint ─────────────────────────────────────────────────────────────────

def test_grammar_endpoint():
    from agents import web
    with TestClient(web.app) as c:
        assert c.post("/api/llm/grammar", json={}).status_code == 400
        r = c.post("/api/llm/grammar", json={"schema": WEATHER})
        assert r.status_code == 200 and "root ::=" in r.json()["gbnf"]
        t = c.post("/api/llm/grammar", json={"tool": {"name": "f", "parameters": WEATHER}})
        assert t.status_code == 200 and '\\"city\\"' in t.json()["gbnf"]
