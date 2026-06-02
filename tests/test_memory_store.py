"""Tests for MemoryStore and profile extractor."""
import pytest
import asyncio
from pathlib import Path
from agents.core.memory.store import MemoryStore
from agents.core.memory.profile_extractor import extract_facts, process_conversation
from agents.core.memory.digest import generate_digest


@pytest.fixture
def store(tmp_path):
    return MemoryStore(db_path=tmp_path / "test_memory.db")


@pytest.mark.asyncio
async def test_upsert_and_get(store):
    await store.upsert("fact", "name", "Andrei")
    result = await store.get("fact", "name")
    assert result is not None
    assert result["value"] == "Andrei"


@pytest.mark.asyncio
async def test_upsert_overwrites(store):
    await store.upsert("fact", "name", "Andrei")
    await store.upsert("fact", "name", "Alex")
    result = await store.get("fact", "name")
    assert result["value"] == "Alex"


@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    assert await store.get("fact", "nonexistent") is None


@pytest.mark.asyncio
async def test_get_category(store):
    await store.upsert("preference", "language", "Romanian")
    await store.upsert("preference", "theme", "dark")
    prefs = await store.get_category("preference")
    assert len(prefs) == 2


@pytest.mark.asyncio
async def test_delete(store):
    await store.upsert("fact", "to_delete", "value")
    deleted = await store.delete("fact", "to_delete")
    assert deleted is True
    assert await store.get("fact", "to_delete") is None


@pytest.mark.asyncio
async def test_search(store):
    await store.upsert("fact", "city", "Bucharest")
    results = await store.search("Bucharest")
    assert any(r["value"] == "Bucharest" for r in results)


def test_extract_facts_name():
    facts = extract_facts("My name is Andrei")
    assert any(f.key == "name" and "andrei" in f.value.lower() for f in facts)


def test_extract_facts_no_match():
    facts = extract_facts("the weather is nice today")
    assert facts == []


@pytest.mark.asyncio
async def test_process_conversation(store):
    messages = [
        {"role": "user", "content": "My name is Andrei"},
        {"role": "assistant", "content": "Hello Andrei!"},
    ]
    count = await process_conversation(messages, store)
    assert count >= 1


@pytest.mark.asyncio
async def test_digest_empty_store(store):
    digest = await generate_digest(store)
    assert "generated_at" in digest
    assert isinstance(digest["highlights"], list)


@pytest.mark.asyncio
async def test_digest_with_facts(store):
    await store.upsert("fact", "name", "Andrei")
    await store.upsert("preference", "language", "ro")
    digest = await generate_digest(store)
    assert "fact" in digest["profile_summary"] or "preference" in digest["profile_summary"]
