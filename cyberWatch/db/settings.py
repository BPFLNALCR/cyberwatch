"""Settings storage and retrieval using PostgreSQL."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
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
        value = row["value"]
        # asyncpg typically decodes JSONB into Python objects already.
        # Older rows or alternate codecs may yield a JSON string.
        if isinstance(value, (dict, list)):
            return value  # type: ignore[return-value]
        if isinstance(value, (str, bytes, bytearray)):
            return json.loads(value)
        return None


async def set_setting(pool: Pool, key: str, value: Dict[str, Any]) -> None:
    """Upsert a setting."""
    json_value = json.dumps(value)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES ($1, $2::jsonb, NOW())
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


# Collector status and restart control
COLLECTOR_STATUS_KEY = "collector_status"


async def request_collector_restart(pool: Pool) -> None:
    """Signal the collector to restart by updating the restart timestamp."""
    await set_setting(pool, COLLECTOR_STATUS_KEY, {
        "restart_requested_at": datetime.utcnow().isoformat(),
    })
    logger.info("Collector restart requested", extra={"action": "restart_request"})


async def get_collector_status(pool: Pool) -> Optional[Dict[str, Any]]:
    """Get collector status including restart requests and heartbeat."""
    return await get_setting(pool, COLLECTOR_STATUS_KEY)


async def update_collector_heartbeat(pool: Pool) -> None:
    """Update the collector's heartbeat timestamp."""
    status = await get_setting(pool, COLLECTOR_STATUS_KEY) or {}
    status["last_heartbeat"] = datetime.utcnow().isoformat()
    status["running"] = True
    await set_setting(pool, COLLECTOR_STATUS_KEY, status)


async def check_restart_requested(pool: Pool, last_check: Optional[datetime] = None) -> bool:
    """Check if a restart has been requested since the last check.
    
    Args:
        last_check: The datetime of the last restart check. If None, always returns False.
    
    Returns:
        True if a restart was requested after last_check.
    """
    status = await get_setting(pool, COLLECTOR_STATUS_KEY)
    if not status or "restart_requested_at" not in status:
        return False
    
    if last_check is None:
        return False
    
    try:
        restart_time = datetime.fromisoformat(status["restart_requested_at"])
        return restart_time > last_check
    except (ValueError, TypeError):
        return False


async def clear_restart_request(pool: Pool) -> None:
    """Clear the restart request after handling it."""
    status = await get_setting(pool, COLLECTOR_STATUS_KEY) or {}
    status.pop("restart_requested_at", None)
    status["last_restarted_at"] = datetime.utcnow().isoformat()
    await set_setting(pool, COLLECTOR_STATUS_KEY, status)


# Worker settings
WORKER_SETTINGS_KEY = "worker_settings"


async def get_worker_settings(pool: Pool) -> Optional[Dict[str, Any]]:
    """Get worker configuration settings."""
    return await get_setting(pool, WORKER_SETTINGS_KEY)


async def save_worker_settings(
    pool: Pool,
    *,
    rate_limit_per_minute: int = 30,
    max_concurrent_traceroutes: int = 5,
    worker_count: int = 2,
) -> None:
    """Save worker configuration settings."""
    await set_setting(pool, WORKER_SETTINGS_KEY, {
        "rate_limit_per_minute": rate_limit_per_minute,
        "max_concurrent_traceroutes": max_concurrent_traceroutes,
        "worker_count": worker_count,
    })


# Enrichment settings
ENRICHMENT_SETTINGS_KEY = "enrichment_settings"


async def get_enrichment_settings(pool: Pool) -> Optional[Dict[str, Any]]:
    """Get enrichment configuration settings."""
    return await get_setting(pool, ENRICHMENT_SETTINGS_KEY)


async def save_enrichment_settings(
    pool: Pool,
    *,
    poll_interval_seconds: int = 10,
    batch_size: int = 200,
    asn_expansion_enabled: bool = True,
    asn_expansion_interval_minutes: int = 60,
    asn_min_neighbor_count: int = 5,
    asn_max_ips_per_asn: int = 10,
) -> None:
    """Save enrichment configuration settings."""
    await set_setting(pool, ENRICHMENT_SETTINGS_KEY, {
        "poll_interval_seconds": poll_interval_seconds,
        "batch_size": batch_size,
        "asn_expansion_enabled": asn_expansion_enabled,
        "asn_expansion_interval_minutes": asn_expansion_interval_minutes,
        "asn_min_neighbor_count": asn_min_neighbor_count,
        "asn_max_ips_per_asn": asn_max_ips_per_asn,
    })


# Remeasurement settings
REMEASUREMENT_SETTINGS_KEY = "remeasurement_settings"


async def get_remeasurement_settings(pool: Pool) -> Optional[Dict[str, Any]]:
    """Get remeasurement configuration settings."""
    return await get_setting(pool, REMEASUREMENT_SETTINGS_KEY)


async def save_remeasurement_settings(
    pool: Pool,
    *,
    enabled: bool = True,
    interval_hours: int = 24,
    batch_size: int = 100,
    targets_per_run: int = 500,
) -> None:
    """Save remeasurement configuration settings."""
    await set_setting(pool, REMEASUREMENT_SETTINGS_KEY, {
        "enabled": enabled,
        "interval_hours": interval_hours,
        "batch_size": batch_size,
        "targets_per_run": targets_per_run,
    })
