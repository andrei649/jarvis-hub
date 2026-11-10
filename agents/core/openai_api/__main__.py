"""``python -m agents.core.openai_api keys issue|list|revoke`` (see ``cli``)."""
import sys

from agents.core.openai_api.cli import main

sys.exit(main())
