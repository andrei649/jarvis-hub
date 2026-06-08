"""WorldView OSINT ingestion workers.

Each worker fetches a source, normalizes it to the canonical telemetry envelope, and
publishes to its per-domain Kafka topic. See worldview/docs/01-architecture-and-schema.md.
"""

__version__ = "0.1.0"
