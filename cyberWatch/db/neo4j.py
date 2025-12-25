"""Neo4j helper for async driver creation."""
from __future__ import annotations

import os
from typing import Optional

from neo4j import AsyncDriver, AsyncGraphDatabase

from cyberWatch.logging_config import get_logger, sanitize_log_data

logger = get_logger("db")


def get_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> AsyncDriver:
    """Create an AsyncDriver using environment defaults."""
    neo4j_uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = user or os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = password or os.getenv("NEO4J_PASSWORD", "neo4j")
    
    logger.info(
        "Creating Neo4j driver",
        extra={
            "uri": neo4j_uri,
            "user": neo4j_user,
            "action": "neo4j_connect",
        }
    )
    
    try:
        driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        logger.info(
            "Neo4j driver created successfully",
            extra={"uri": neo4j_uri, "outcome": "success"}
        )
        return driver
    except Exception as exc:
        logger.error(
            f"Failed to create Neo4j driver: {str(exc)}",
            exc_info=True,
            extra={"uri": neo4j_uri, "outcome": "error"}
        )
        raise
