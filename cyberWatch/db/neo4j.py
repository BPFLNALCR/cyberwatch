"""Neo4j helper for async driver creation."""
from __future__ import annotations

import os
from typing import Optional

from neo4j import AsyncDriver, AsyncGraphDatabase


def get_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> AsyncDriver:
    """Create an AsyncDriver using environment defaults."""
    neo4j_uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = user or os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = password or os.getenv("NEO4J_PASSWORD", "neo4j")
    return AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
