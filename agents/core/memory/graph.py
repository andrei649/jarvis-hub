import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from agents.core.validation import (
    coerce_kg_label,
    coerce_kg_rel_type,
    is_safe_kg_rel_type,
    is_safe_property_key,
)

logger = logging.getLogger("jarvis.memory.graph")

NEO4J_URL = os.getenv("NEO4J_URL", "http://localhost:7474")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j")


class KnowledgeGraph(ABC):
    """Abstract knowledge graph interface."""

    @abstractmethod
    def add_entity(self, name: str, entity_type: str, properties: dict = None) -> bool:
        ...

    @abstractmethod
    def add_relation(self, source: str, relation: str, target: str, properties: dict = None) -> bool:
        ...

    @abstractmethod
    def query(self, cypher: str, params: dict = None) -> list[dict]:
        ...

    @abstractmethod
    def get_entity(self, name: str) -> Optional[dict]:
        ...

    @abstractmethod
    def get_relations(self, name: str, direction: str = "both") -> list[dict]:
        ...

    @abstractmethod
    def search(self, keyword: str) -> list[dict]:
        ...

    # ── H12.3 editing surface (view / delete) ──────────────────────────────
    @abstractmethod
    def list_entities(self, limit: int = 100) -> list[dict]:
        ...

    @abstractmethod
    def delete_entity(self, name: str) -> bool:
        ...

    @abstractmethod
    def delete_relation(self, source: str, relation: str, target: str) -> bool:
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove every entity and relation. Backs ``POST /api/admin/forget`` (AUDIT-2).

        Abstract on purpose — see the matching note on ``VectorStore.clear``. No
        implementation defined it, and ``data_purge.clear_live_memory`` called it behind
        ``hasattr``, so under the documented neo4j backend every triple survived a forget
        permanently while the purge reported success.

        Implementations MUST raise on failure rather than degrade quietly. Everywhere
        else in this class a swallowed error means a stale read; here it means the owner
        was told their data was deleted when it was not.
        """
        ...


class InMemoryGraph(KnowledgeGraph):
    """Fallback — simple dict-based graph."""

    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.relations: list[dict] = []

    def clear(self) -> None:
        self.entities.clear()
        self.relations.clear()

    def add_entity(self, name: str, entity_type: str, properties: dict = None) -> bool:
        props = properties or {}
        self.entities[name] = {
            "name": name,
            "type": entity_type,
            "properties": props,
        }
        return True

    def add_relation(self, source: str, relation: str, target: str, properties: dict = None) -> bool:
        if source not in self.entities:
            self.entities[source] = {"name": source, "type": "unknown", "properties": {}}
        if target not in self.entities:
            self.entities[target] = {"name": target, "type": "unknown", "properties": {}}
        self.relations.append({
            "source": source,
            "relation": relation,
            "target": target,
            "properties": properties or {},
        })
        return True

    def query(self, cypher: str, params: dict = None) -> list[dict]:
        return []

    def get_entity(self, name: str) -> Optional[dict]:
        return self.entities.get(name)

    def get_relations(self, name: str, direction: str = "both") -> list[dict]:
        results = []
        for rel in self.relations:
            if direction == "outgoing" and rel["source"] == name:
                results.append(rel)
            elif direction == "incoming" and rel["target"] == name:
                results.append(rel)
            elif direction == "both" and (rel["source"] == name or rel["target"] == name):
                results.append(rel)
        return results

    def search(self, keyword: str) -> list[dict]:
        kw = keyword.lower()
        results = []
        for name, ent in self.entities.items():
            if kw in name.lower():
                results.append(ent)
            props = ent.get("properties", {})
            for val in props.values():
                if kw in str(val).lower():
                    results.append(ent)
                    break
        return results

    def list_entities(self, limit: int = 100) -> list[dict]:
        return list(self.entities.values())[:max(1, limit)]

    def delete_entity(self, name: str) -> bool:
        if name not in self.entities:
            return False
        del self.entities[name]
        # Drop any relations that touch the removed entity.
        self.relations = [
            r for r in self.relations if r["source"] != name and r["target"] != name
        ]
        return True

    def delete_relation(self, source: str, relation: str, target: str) -> bool:
        before = len(self.relations)
        self.relations = [
            r for r in self.relations
            if not (r["source"] == source and r["relation"] == relation and r["target"] == target)
        ]
        return len(self.relations) < before


class Neo4jGraph(KnowledgeGraph):
    """Neo4j via REST API (no driver needed)."""

    def __init__(self, url: str = None, user: str = None, password: str = None):
        self.url = (url or NEO4J_URL).rstrip("/")
        self.user = user or NEO4J_USER
        self.password = password or NEO4J_PASSWORD
        self._auth = httpx.BasicAuth(self.user, self.password)
        self._tx_url = f"{self.url}/db/neo4j/tx/commit"
        self._connected = None  # lazy check
        logger.info(f"Neo4jGraph configured at {self.url} (user={self.user})")

    def _check_connection(self) -> bool:
        if self._connected is not None:
            return self._connected
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0)) as client:
                resp = client.get(
                    f"{self.url}/db/neo4j/tx",
                    auth=self._auth,
                )
                self._connected = resp.status_code == 200
        except httpx.TransportError:
            self._connected = False
            logger.warning("Neo4j unreachable — falling back to in-memory graph")
        return self._connected

    def _call_neo4j(self, statements: list[dict]) -> list[dict]:
        if not self._check_connection():
            return []
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
                resp = client.post(
                    self._tx_url,
                    json={"statements": statements},
                    auth=self._auth,
                )
                resp.raise_for_status()
                return resp.json().get("results", [])
        except Exception as e:
            logger.warning(f"Neo4j query failed: {e}")
            return []

    def query(self, cypher: str, params: dict = None) -> list[dict]:
        results = self._call_neo4j([{"statement": cypher, "parameters": params or {}}])
        rows = []
        for result in results:
            columns = result.get("columns", [])
            for row_data in result.get("data", []):
                row = {}
                for col, val in zip(columns, row_data.get("row", [])):
                    row[col] = val
                rows.append(row)
        return rows

    def add_entity(self, name: str, entity_type: str, properties: dict = None) -> bool:
        # AUD-12 (F11): the label is interpolated into Cypher (Neo4j can't
        # parameterise it), so coerce it to a safe identifier — a legitimate
        # type passes through unchanged (mirrors the old ``capitalize()``); only
        # a non-identifier value collapses to ``Entity`` and can't break out of
        # the query. Property *keys* are interpolated as map keys too, so drop
        # any that aren't bare identifiers.
        label = coerce_kg_label(entity_type)
        props = properties or {}
        all_props = {
            k: v for k, v in {"name": name, **props}.items()
            if k == "name" or is_safe_property_key(k)
        }
        prop_pairs = ", ".join(f"{k}: ${k}" for k in all_props)
        cypher = f"MERGE (n:{label} {{name: $name}}) SET n += {{{prop_pairs}}} RETURN n"
        results = self._call_neo4j([{"statement": cypher, "parameters": all_props}])
        return len(results) > 0

    def add_relation(self, source: str, relation: str, target: str, properties: dict = None) -> bool:
        # AUD-12 (F11): the relationship type is interpolated into Cypher, so
        # coerce it to a safe identifier (a legitimate or free-form-but-safe type
        # like WORKS_AT or DAUGHTER is kept; only a non-identifier collapses to
        # RELATED_TO). Drop property keys that aren't bare identifiers.
        rel = coerce_kg_rel_type(relation)
        props = {k: v for k, v in (properties or {}).items() if is_safe_property_key(k)}
        prop_pairs = ", ".join(f"{k}: ${k}" for k in props)
        set_clause = f" SET r += {{{prop_pairs}}}" if props else ""
        cypher = (
            f"MERGE (a {{name: $source}}) "
            f"MERGE (b {{name: $target}}) "
            f"MERGE (a)-[r:{rel} {{}}]->(b){set_clause} "
            f"RETURN a, r, b"
        )
        params = {"source": source, "target": target, **props}
        results = self._call_neo4j([{"statement": cypher, "parameters": params}])
        return len(results) > 0

    def get_entity(self, name: str) -> Optional[dict]:
        rows = self.query(
            "MATCH (n {name: $name}) RETURN n, labels(n) AS labels",
            {"name": name},
        )
        if not rows:
            return None
        row = rows[0]
        node = row.get("n", {})
        return {
            "name": node.get("name", name),
            "type": (row.get("labels", []) + ["unknown"])[0].lower(),
            "properties": {k: v for k, v in node.items() if k != "name"},
        }

    def get_relations(self, name: str, direction: str = "both") -> list[dict]:
        if direction == "outgoing":
            pattern = "(n)-[r]->(m)"
        elif direction == "incoming":
            pattern = "(n)<-[r]-(m)"
        else:
            pattern = "(n)-[r]-(m)"
        cypher = (
            f"MATCH {pattern} "
            "WHERE n.name = $name OR (n.name IS NULL AND n.name = $name) "
            "RETURN n.name AS source, type(r) AS relation, m.name AS target, properties(r) AS properties"
        )
        rows = self.query(cypher, {"name": name})
        for row in rows:
            row["properties"] = row.get("properties", {})
        return rows

    def search(self, keyword: str) -> list[dict]:
        # Match on the node name OR any of its string-ish properties, mirroring
        # InMemoryGraph.search (name OR any property). Without the property scan a
        # geo-event whose AOI/source/details live only in properties (e.g. a
        # ReconWindow with no resolvable AOI in its name) is unfindable on Neo4j.
        # Injection-safe: the keyword is parameterised and property keys are read
        # from the node itself via keys(n) — no string interpolation of input.
        rows = self.query(
            "MATCH (n) WHERE toLower(toString(n.name)) CONTAINS toLower($keyword) "
            "OR any(k IN keys(n) WHERE toLower(toString(n[k])) CONTAINS toLower($keyword)) "
            "RETURN n, labels(n) AS labels LIMIT 50",
            {"keyword": keyword},
        )
        results = []
        for row in rows:
            node = row.get("n", {})
            results.append({
                "name": node.get("name", ""),
                "type": (row.get("labels", []) + ["unknown"])[0].lower(),
                "properties": {k: v for k, v in node.items() if k != "name"},
            })
        return results

    def list_entities(self, limit: int = 100) -> list[dict]:
        rows = self.query(
            "MATCH (n) RETURN n, labels(n) AS labels LIMIT $limit",
            {"limit": max(1, limit)},
        )
        results = []
        for row in rows:
            node = row.get("n", {})
            results.append({
                "name": node.get("name", ""),
                "type": (row.get("labels", []) + ["unknown"])[0].lower(),
                "properties": {k: v for k, v in node.items() if k != "name"},
            })
        return results

    def clear(self) -> None:
        """Delete every node and relationship, and RAISE if it did not happen.

        Deliberately different from every other method here. The rest of this class
        degrades quietly on a Neo4j problem because the cost is a stale read; a failed
        wipe during ``POST /api/admin/forget`` means the owner was told their knowledge
        graph was deleted when it was not. That is the AUDIT-2 finding, so this one
        reports.

        Scope note, stated because it matters: this clears the WHOLE configured Neo4j
        database, not only Nerva-written nodes. ``add_relation`` MERGEs bare
        ``(a {name: ...})`` nodes with no Nerva label, so there is no label that reliably
        identifies our data and a scoped delete would silently miss some of it — which is
        the exact failure mode being fixed. Point ``NEO4J_URL`` at a database Nerva owns.
        """
        if not self._check_connection():
            raise RuntimeError(
                f"knowledge-graph wipe failed: Neo4j at {self.url} is unreachable. The "
                "graph still holds your data — do not report this forget as complete."
            )
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0)) as client:
                resp = client.post(
                    self._tx_url,
                    json={"statements": [{"statement": "MATCH (n) DETACH DELETE n"}]},
                    auth=self._auth,
                )
                resp.raise_for_status()
                errors = resp.json().get("errors") or []
        except Exception as exc:
            raise RuntimeError(f"knowledge-graph wipe failed: {exc}") from exc
        if errors:
            raise RuntimeError(f"knowledge-graph wipe failed: {errors}")

    def delete_entity(self, name: str) -> bool:
        results = self._call_neo4j([{
            "statement": "MATCH (n {name: $name}) DETACH DELETE n RETURN count(n) AS deleted",
            "parameters": {"name": name},
        }])
        return len(results) > 0

    def delete_relation(self, source: str, relation: str, target: str) -> bool:
        # AUD-12 (F11): refuse a non-identifier relationship type rather than
        # coerce it — coercing a delete could remove the wrong (RELATED_TO) edge.
        # The direct API rejects these with 400 before reaching here.
        if not is_safe_kg_rel_type(relation):
            logger.warning("delete_relation refused: %r is not a safe Cypher identifier", relation)
            return False
        rel = coerce_kg_rel_type(relation)  # guaranteed to pass through unchanged
        cypher = (
            f"MATCH (a {{name: $source}})-[r:{rel}]->(b {{name: $target}}) "
            "DELETE r RETURN count(r) AS deleted"
        )
        results = self._call_neo4j([{
            "statement": cypher,
            "parameters": {"source": source, "target": target},
        }])
        return len(results) > 0


def create_graph(backend: str = None) -> KnowledgeGraph:
    """Factory: create a KnowledgeGraph from env or explicit backend."""
    backend = backend or os.getenv("KNOWLEDGE_GRAPH_BACKEND", "memory")
    if backend == "neo4j":
        graph = Neo4jGraph()
        if graph._check_connection():
            logger.info("Using Neo4j knowledge graph backend")
            return graph
        logger.warning("Neo4j requested but unreachable — using in-memory fallback")
    return InMemoryGraph()
