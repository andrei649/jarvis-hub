"""Seed the knowledge graph with known facts about the user.

Called once on startup if the graph is empty.
"""

import logging

logger = logging.getLogger("jarvis.memory.seed_graph")

SEED_FACTS = [
    # People
    ("add_entity", "Andrei", "Person", {"works_at": "Raiffeisen", "role": "Software Engineer", "city": "Bucharest"}),
    ("add_entity", "Alexandra", "Person", {"relation": "wife"}),
    ("add_entity", "Max", "Person", {"relation": "son"}),
    # Organizations
    ("add_entity", "Raiffeisen", "Organization", {"industry": "Banking"}),
    ("add_entity", "Digitaholic", "Organization", {"industry": "Software Development"}),
    # Places
    ("add_entity", "Bucharest", "City", {"country": "Romania"}),
    ("add_entity", "Cosmina de Sus", "Village", {"country": "Romania", "note": "house build"}),
    # Projects / Objects
    ("add_entity", "BMW E93", "Project", {"type": "car restoration"}),
    # Relations
    ("add_relation", "Andrei", "WORKS_AT", "Raiffeisen", {}),
    ("add_relation", "Andrei", "RUNS", "Digitaholic", {}),
    ("add_relation", "Andrei", "MARRIED_TO", "Alexandra", {}),
    ("add_relation", "Andrei", "PARENT_OF", "Max", {}),
    ("add_relation", "Alexandra", "PARENT_OF", "Max", {}),
    ("add_relation", "Andrei", "LIVES_IN", "Bucharest", {}),
    ("add_relation", "Andrei", "BUILDING_HOUSE_AT", "Cosmina de Sus", {}),
    ("add_relation", "Andrei", "OWNS", "BMW E93", {}),
    ("add_relation", "Raiffeisen", "LOCATED_IN", "Bucharest", {}),
    ("add_relation", "Digitaholic", "LOCATED_IN", "Bucharest", {}),
]


def seed_graph(graph) -> int:
    """Populate graph with known facts. Returns count of items seeded."""
    existing = graph.get_entity("Andrei")
    if existing:
        logger.info("Graph already seeded — skipping")
        return 0

    count = 0
    for fact in SEED_FACTS:
        action = fact[0]
        try:
            if action == "add_entity":
                _, name, entity_type, props = fact
                graph.add_entity(name, entity_type, props)
            elif action == "add_relation":
                _, source, relation, target, props = fact
                graph.add_relation(source, relation, target, props)
            count += 1
        except Exception as e:
            logger.warning(f"Failed to seed {fact}: {e}")

    logger.info(f"Knowledge graph seeded with {count} facts")
    return count
