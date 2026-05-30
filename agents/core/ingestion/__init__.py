"""
ingestion — Data ingestion pipeline for Howard (Digital Twin).
Parses Facebook Messenger JSON exports and WhatsApp .txt exports,
normalizes into a common format, and feeds into the learning system.
"""

from .pipeline import IngestionPipeline
from .normalizer import NormalizedMessage
from .stylometry import VoiceProfile, StylometryAnalyzer
from .knowledge import KnowledgeExtractor
from .embedder import Embedder
