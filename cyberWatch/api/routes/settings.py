"""Settings management API endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import aiohttp
import asyncpg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cyberWatch.api.models import ok, err
from cyberWatch.api.utils.db import pg_dep, neo4j_dep
from cyberWatch.db.settings import (
    get_pihole_settings,
    save_pihole_settings,
    request_collector_restart,
    get_collector_status,
)
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/settings", tags=["settings"])


class PiholeSettingsRequest(BaseModel):
    """Request body for Pi-hole settings."""
    base_url: str = Field(..., description="Pi-hole base URL (e.g., http://192.168.1.10)")
    api_token: Optional[str] = Field(default=None, description="Pi-hole API password/token (optional if already saved)")
    enabled: bool = Field(default=True, description="Enable DNS collection from Pi-hole")
    poll_interval_seconds: int = Field(default=30, ge=5, le=300, description="Poll interval in seconds")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates (disable for self-signed certs)")


class PiholeSettingsResponse(BaseModel):
    """Response body for Pi-hole settings (token masked)."""
    base_url: str
    enabled: bool
    poll_interval_seconds: int
    has_token: bool


@router.get("/pihole")
async def get_pihole(
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Get current Pi-hole settings (token is masked)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Fetching Pi-hole settings",
        extra={"request_id": request_id, "action": "pihole_get"}
    )
    
    settings = await get_pihole_settings(pool)
    
    if settings is None:
        return ok({
            "configured": False,
            "base_url": "",
            "enabled": False,
            "poll_interval_seconds": 30,
            "has_token": False,
            "verify_ssl": True,
        })
    
    return ok({
        "configured": True,
        "base_url": settings.get("base_url", ""),
        "enabled": settings.get("enabled", False),
        "poll_interval_seconds": settings.get("poll_interval_seconds", 30),
        "has_token": bool(settings.get("api_token")),
        "verify_ssl": settings.get("verify_ssl", True),
    })


@router.get("/pihole/status")
async def get_collector_status_endpoint(
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Get DNS collector status including last restart time."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    status = await get_collector_status(pool)
    settings = await get_pihole_settings(pool)
    
    return ok({
        "configured": settings is not None and bool(settings.get("base_url")),
        "enabled": settings.get("enabled", False) if settings else False,
        "last_restart_requested": status.get("restart_requested_at") if status else None,
        "last_collector_heartbeat": status.get("last_heartbeat") if status else None,
        "collector_running": status.get("running", False) if status else False,
    })


@router.post("/pihole")
async def save_pihole(
    body: PiholeSettingsRequest,
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Save Pi-hole connection settings."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    # Get existing settings to preserve password if not provided
    existing = await get_pihole_settings(pool)
    
    # Determine the API token to use
    api_token = body.api_token
    if not api_token or api_token.strip() == "":
        # Use existing token if available
        if existing and existing.get("api_token"):
            api_token = existing["api_token"]
            logger.info(
                "Using existing API token",
                extra={"request_id": request_id, "action": "pihole_save"}
            )
        else:
            return ok({
                "success": False,
                "message": "API token is required for initial configuration.",
            })
    
    logger.info(
        "Saving Pi-hole settings",
        extra={
            "request_id": request_id,
            "base_url": body.base_url,
            "enabled": body.enabled,
            "poll_interval_seconds": body.poll_interval_seconds,
            "action": "pihole_save",
        }
    )
    
    await save_pihole_settings(
        pool,
        base_url=body.base_url,
        api_token=api_token,
        enabled=body.enabled,
        poll_interval_seconds=body.poll_interval_seconds,
        verify_ssl=body.verify_ssl,
    )
    
    logger.info(
        "Pi-hole settings saved",
        extra={"request_id": request_id, "outcome": "success"}
    )
    
    return ok({"success": True, "message": "Pi-hole settings saved successfully"})


@router.post("/pihole/restart")
async def restart_collector(
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Request the DNS collector to restart and reload settings."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Requesting DNS collector restart",
        extra={"request_id": request_id, "action": "collector_restart"}
    )
    
    await request_collector_restart(pool)
    
    return ok({
        "success": True,
        "message": "Restart requested. The collector will reload settings on its next cycle.",
    })


@router.post("/pihole/test")
async def test_pihole_connection(
    body: PiholeSettingsRequest,
    request: Request = None,
):
    """Test Pi-hole connection without saving settings."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Testing Pi-hole connection",
        extra={"request_id": request_id, "base_url": body.base_url, "action": "pihole_test"}
    )
    
    # Normalize base URL
    base_url = body.base_url.rstrip("/")
    
    # Pi-hole v6 uses session-based authentication
    # First, authenticate to get a session
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        
        # Create SSL context for self-signed certs if verify_ssl is False
        import ssl
        ssl_context = None if body.verify_ssl else ssl.create_default_context()
        if not body.verify_ssl:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            # Try v6 authentication first
            auth_url = f"{base_url}/api/auth"
            auth_payload = {"password": body.api_token}
            
            async with session.post(auth_url, json=auth_payload) as auth_resp:
                if auth_resp.status == 200:
                    auth_data = await auth_resp.json()
                    sid = auth_data.get("session", {}).get("sid")
                    
                    if sid:
                        # v6 authentication successful, test query endpoint
                        queries_url = f"{base_url}/api/queries"
                        headers = {"sid": sid}
                        
                        async with session.get(queries_url, headers=headers) as queries_resp:
                            if queries_resp.status == 200:
                                data = await queries_resp.json()
                                query_count = len(data.get("queries", []))
                                
                                # Logout
                                await session.delete(f"{base_url}/api/auth", headers=headers)
                                
                                logger.info(
                                    "Pi-hole v6 connection test successful",
                                    extra={
                                        "request_id": request_id,
                                        "api_version": "v6",
                                        "query_count": query_count,
                                        "outcome": "success",
                                    }
                                )
                                
                                return ok({
                                    "success": True,
                                    "api_version": "v6",
                                    "message": f"Connected to Pi-hole v6. Found {query_count} recent queries.",
                                })
                            else:
                                return ok({
                                    "success": False,
                                    "api_version": "v6",
                                    "message": f"Authenticated but failed to fetch queries: HTTP {queries_resp.status}",
                                })
                    else:
                        return ok({
                            "success": False,
                            "api_version": "v6",
                            "message": "Authentication failed: no session ID returned. Check your password.",
                        })
                
                elif auth_resp.status == 401:
                    return ok({
                        "success": False,
                        "api_version": "v6",
                        "message": "Authentication failed: invalid password.",
                    })
                
                elif auth_resp.status == 404:
                    # Not v6, try v5 API
                    logger.debug("v6 auth endpoint not found, trying v5 API")
                    pass
                else:
                    return ok({
                        "success": False,
                        "api_version": "v6",
                        "message": f"Authentication failed: HTTP {auth_resp.status}",
                    })
            
            # Try v5 API fallback
            v5_url = f"{base_url}/admin/api.php"
            params = {"getAllQueries": "1", "auth": body.api_token}
            
            async with session.get(v5_url, params=params) as v5_resp:
                if v5_resp.status == 200:
                    try:
                        data = await v5_resp.json(content_type=None)
                        queries = data.get("data") or data.get("queries") or []
                        
                        if isinstance(queries, list):
                            logger.info(
                                "Pi-hole v5 connection test successful",
                                extra={
                                    "request_id": request_id,
                                    "api_version": "v5",
                                    "query_count": len(queries),
                                    "outcome": "success",
                                }
                            )
                            
                            return ok({
                                "success": True,
                                "api_version": "v5",
                                "message": f"Connected to Pi-hole v5. Found {len(queries)} recent queries.",
                            })
                        else:
                            return ok({
                                "success": False,
                                "api_version": "v5",
                                "message": "Connected but received unexpected response format. Check API token.",
                            })
                    except Exception as e:
                        return ok({
                            "success": False,
                            "api_version": "v5",
                            "message": f"Failed to parse response: {str(e)}",
                        })
                else:
                    return ok({
                        "success": False,
                        "api_version": "unknown",
                        "message": f"Could not connect to Pi-hole API. HTTP {v5_resp.status}",
                    })
    
    except aiohttp.ClientConnectorError as e:
        logger.warning(
            "Pi-hole connection failed",
            extra={"request_id": request_id, "error": str(e), "outcome": "error"}
        )
        return ok({
            "success": False,
            "api_version": "unknown",
            "message": f"Connection failed: {str(e)}. Check URL and ensure Pi-hole is accessible.",
        })
    
    except Exception as e:
        logger.error(
            f"Pi-hole test error: {str(e)}",
            exc_info=True,
            extra={"request_id": request_id, "outcome": "error"}
        )
        return ok({
            "success": False,
            "api_version": "unknown",
            "message": f"Error: {str(e)}",
        })


@router.post("/clear-measurements")
async def clear_measurements(
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Clear all measurement data (targets, measurements, hops)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Clearing measurement data",
        extra={"request_id": request_id, "action": "clear_measurements"}
    )
    
    try:
        async with pool.acquire() as conn:
            # Count rows before clearing
            targets_count = await conn.fetchval("SELECT COUNT(*) FROM targets")
            measurements_count = await conn.fetchval("SELECT COUNT(*) FROM measurements")
            hops_count = await conn.fetchval("SELECT COUNT(*) FROM hops")
            
            # Clear tables with CASCADE to handle foreign keys
            await conn.execute("TRUNCATE TABLE targets CASCADE")
            
            logger.info(
                "Measurement data cleared successfully",
                extra={
                    "request_id": request_id,
                    "targets_cleared": targets_count,
                    "measurements_cleared": measurements_count,
                    "hops_cleared": hops_count,
                    "outcome": "success"
                }
            )
            
            return ok({
                "success": True,
                "message": f"Cleared {targets_count} targets, {measurements_count} measurements, {hops_count} hops",
                "stats": {
                    "targets": targets_count,
                    "measurements": measurements_count,
                    "hops": hops_count,
                }
            })
    
    except Exception as exc:
        logger.error(
            f"Failed to clear measurement data: {str(exc)}",
            exc_info=True,
            extra={"request_id": request_id, "outcome": "error"}
        )
        return err(str(exc))


@router.post("/clear-dns")
async def clear_dns(
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Clear all DNS data (dns_queries, dns_targets)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Clearing DNS data",
        extra={"request_id": request_id, "action": "clear_dns"}
    )
    
    try:
        async with pool.acquire() as conn:
            # Count rows before clearing
            queries_count = await conn.fetchval("SELECT COUNT(*) FROM dns_queries")
            targets_count = await conn.fetchval("SELECT COUNT(*) FROM dns_targets")
            
            # Clear DNS tables
            await conn.execute("TRUNCATE TABLE dns_queries")
            await conn.execute("TRUNCATE TABLE dns_targets")
            
            logger.info(
                "DNS data cleared successfully",
                extra={
                    "request_id": request_id,
                    "queries_cleared": queries_count,
                    "targets_cleared": targets_count,
                    "outcome": "success"
                }
            )
            
            return ok({
                "success": True,
                "message": f"Cleared {queries_count} DNS queries, {targets_count} DNS targets",
                "stats": {
                    "dns_queries": queries_count,
                    "dns_targets": targets_count,
                }
            })
    
    except Exception as exc:
        logger.error(
            f"Failed to clear DNS data: {str(exc)}",
            exc_info=True,
            extra={"request_id": request_id, "outcome": "error"}
        )
        return err(str(exc))


@router.post("/clear-graph")
async def clear_graph(
    driver = Depends(neo4j_dep),
    request: Request = None,
):
    """Clear all Neo4j graph data (nodes and relationships)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Clearing graph data",
        extra={"request_id": request_id, "action": "clear_graph"}
    )
    
    try:
        async with driver.session() as session:
            # Count nodes and relationships before clearing
            count_result = await session.run(
                "MATCH (n) OPTIONAL MATCH (n)-[r]-() RETURN count(DISTINCT n) as nodes, count(DISTINCT r) as rels"
            )
            count_record = await count_result.single()
            nodes_count = count_record["nodes"] if count_record else 0
            rels_count = count_record["rels"] if count_record else 0
            
            # Clear all nodes and relationships
            await session.run("MATCH (n) DETACH DELETE n")
            
            logger.info(
                "Graph data cleared successfully",
                extra={
                    "request_id": request_id,
                    "nodes_cleared": nodes_count,
                    "relationships_cleared": rels_count,
                    "outcome": "success"
                }
            )
            
            return ok({
                "success": True,
                "message": f"Cleared {nodes_count} nodes, {rels_count} relationships",
                "stats": {
                    "nodes": nodes_count,
                    "relationships": rels_count,
                }
            })
    
    except Exception as exc:
        logger.error(
            f"Failed to clear graph data: {str(exc)}",
            exc_info=True,
            extra={"request_id": request_id, "outcome": "error"}
        )
        return err(str(exc))


@router.post("/clear-all")
async def clear_all(
    pool: asyncpg.Pool = Depends(pg_dep),
    driver = Depends(neo4j_dep),
    request: Request = None,
):
    """Clear all data: measurements, DNS data, and graph data."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
    logger.info(
        "Clearing all data",
        extra={"request_id": request_id, "action": "clear_all"}
    )
    
    total_stats = {}
    
    try:
        # Clear PostgreSQL data
        async with pool.acquire() as conn:
            # Count rows before clearing
            targets_count = await conn.fetchval("SELECT COUNT(*) FROM targets")
            measurements_count = await conn.fetchval("SELECT COUNT(*) FROM measurements")
            hops_count = await conn.fetchval("SELECT COUNT(*) FROM hops")
            queries_count = await conn.fetchval("SELECT COUNT(*) FROM dns_queries")
            dns_targets_count = await conn.fetchval("SELECT COUNT(*) FROM dns_targets")
            
            # Clear all tables
            await conn.execute("TRUNCATE TABLE targets CASCADE")
            await conn.execute("TRUNCATE TABLE dns_queries")
            await conn.execute("TRUNCATE TABLE dns_targets")
            
            total_stats.update({
                "targets": targets_count,
                "measurements": measurements_count,
                "hops": hops_count,
                "dns_queries": queries_count,
                "dns_targets": dns_targets_count,
            })
        
        # Clear Neo4j data
        async with driver.session() as session:
            # Count nodes and relationships before clearing
            count_result = await session.run(
                "MATCH (n) OPTIONAL MATCH (n)-[r]-() RETURN count(DISTINCT n) as nodes, count(DISTINCT r) as rels"
            )
            count_record = await count_result.single()
            nodes_count = count_record["nodes"] if count_record else 0
            rels_count = count_record["rels"] if count_record else 0
            
            # Clear all nodes and relationships
            await session.run("MATCH (n) DETACH DELETE n")
            
            total_stats.update({
                "graph_nodes": nodes_count,
                "graph_relationships": rels_count,
            })
        
        logger.info(
            "All data cleared successfully",
            extra={
                "request_id": request_id,
                "stats": total_stats,
                "outcome": "success"
            }
        )
        
        return ok({
            "success": True,
            "message": f"Cleared all data: {total_stats['targets']} targets, {total_stats['measurements']} measurements, {total_stats['hops']} hops, {total_stats['dns_queries']} DNS queries, {total_stats['dns_targets']} DNS targets, {total_stats['graph_nodes']} graph nodes, {total_stats['graph_relationships']} graph relationships",
            "stats": total_stats
        })
    
    except Exception as exc:
        logger.error(
            f"Failed to clear all data: {str(exc)}",
            exc_info=True,
            extra={"request_id": request_id, "outcome": "error"}
        )
        return err(str(exc))
