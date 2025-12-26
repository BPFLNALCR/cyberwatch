"""Settings storage and retrieval using PostgreSQL."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from asyncpg import Pool

from cyberWatch.logging_config import get_logger

logger = get_logger("db")


# SQL for settings table
SQL_CREATE_SETTINGS = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def ensure_settings_table(pool: Pool) -> None:
    """Create the settings table if it doesn't exist."""
    async with pool.acquire() as conn:
        await conn.execute(SQL_CREATE_SETTINGS)
    logger.info("Settings table ensured", extra={"action": "settings_init"})


async def get_setting(pool: Pool, key: str) -> Optional[Dict[str, Any]]:
    """Retrieve a setting by key. Returns None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM settings WHERE key = $1",
            key,
        )
        if row is None:
            return None
        return json.loads(row["value"])


async def set_setting(pool: Pool, key: str, value: Dict[str, Any]) -> None:
    """Upsert a setting."""
    json_value = json.dumps(value)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            """,
            key,
            json_value,
        )
    logger.info(
        "Setting saved",
        extra={"key": key, "action": "setting_save", "outcome": "success"}
    )


async def delete_setting(pool: Pool, key: str) -> bool:
    """Delete a setting. Returns True if deleted, False if not found."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM settings WHERE key = $1",
            key,
        )
        deleted = result == "DELETE 1"
    if deleted:
        logger.info(
            "Setting deleted",
            extra={"key": key, "action": "setting_delete", "outcome": "success"}
        )
    return deleted


# Convenience functions for Pi-hole settings
PIHOLE_SETTINGS_KEY = "pihole"


async def get_pihole_settings(pool: Pool) -> Optional[Dict[str, Any]]:
    """Get Pi-hole connection settings."""
    return await get_setting(pool, PIHOLE_SETTINGS_KEY)


async def save_pihole_settings(
    pool: Pool,
    *,
    base_url: str,
    api_token: str,
    enabled: bool = True,
    poll_interval_seconds: int = 30,
    verify_ssl: bool = True,
) -> None:
    """Save Pi-hole connection settings."""
    await set_setting(pool, PIHOLE_SETTINGS_KEY, {
        "base_url": base_url,
        "api_token": api_token,
        "enabled": enabled,
        "poll_interval_seconds": poll_interval_seconds,
        "verify_ssl": verify_ssl,
    })
