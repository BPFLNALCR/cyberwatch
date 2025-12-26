"""Settings management API endpoints."""
from __future__ import annotations

from typing import Optional

import aiohttp
import asyncpg
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from cyberWatch.api.models import ok, err
from cyberWatch.api.utils.db import pg_dep
from cyberWatch.db.settings import get_pihole_settings, save_pihole_settings
from cyberWatch.logging_config import get_logger

logger = get_logger("api")
router = APIRouter(prefix="/settings", tags=["settings"])


class PiholeSettingsRequest(BaseModel):
    """Request body for Pi-hole settings."""
    base_url: str = Field(..., description="Pi-hole base URL (e.g., http://192.168.1.10)")
    api_token: str = Field(..., description="Pi-hole API password/token")
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


@router.post("/pihole")
async def save_pihole(
    body: PiholeSettingsRequest,
    pool: asyncpg.Pool = Depends(pg_dep),
    request: Request = None,
):
    """Save Pi-hole connection settings."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"
    
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
        api_token=body.api_token,
        enabled=body.enabled,
        poll_interval_seconds=body.poll_interval_seconds,
        verify_ssl=body.verify_ssl,
    )
    
    logger.info(
        "Pi-hole settings saved",
        extra={"request_id": request_id, "outcome": "success"}
    )
    
    return ok({"message": "Pi-hole settings saved successfully"})


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
