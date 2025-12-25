"""FastAPI application entrypoint for cyberWatch API."""
from __future__ import annotations

import os
import time
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cyberWatch.api.routes import measurements, traceroute, targets, asn, graph, dns, health
from cyberWatch.api.utils import db
from cyberWatch.logging_config import setup_logging

logger = setup_logging("api")

app = FastAPI(title="cyberWatch-api", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable) -> Response:
    """Log all HTTP requests with timing and outcome."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    start_time = time.time()
    
    # Log incoming request
    logger.info(
        "Incoming request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
    )
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Log response
        logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration": round(duration * 1000, 2),
                "outcome": "success" if response.status_code < 400 else "error",
            }
        )
        
        # Add request ID to response headers for tracing
        response.headers["X-Request-ID"] = request_id
        return response
        
    except Exception as exc:
        duration = time.time() - start_time
        logger.error(
            f"Request failed: {str(exc)}",
            exc_info=True,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration": round(duration * 1000, 2),
                "outcome": "exception",
                "error_type": type(exc).__name__,
            }
        )
        raise


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Ensure CORS headers are sent even on unhandled errors."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": str(exc)},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


app.include_router(measurements.router)
app.include_router(traceroute.router)
app.include_router(targets.router)
app.include_router(asn.router)
app.include_router(graph.router)
app.include_router(dns.router)
app.include_router(health.router)


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Starting cyberWatch API", extra={"component": "api", "state": "startup"})
    await db.init_resources()
    logger.info("API startup complete", extra={"component": "api", "state": "ready"})


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("Shutting down cyberWatch API", extra={"component": "api", "state": "shutdown"})
    await db.close_resources()
    logger.info("API shutdown complete", extra={"component": "api", "state": "stopped"})


@app.get("/")
async def root():
    return {"status": "ok", "service": "cyberWatch-api"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "cyberWatch.api.server:app",
        host=os.getenv("CYBERWATCH_API_HOST", "0.0.0.0"),
        port=int(os.getenv("CYBERWATCH_API_PORT", "8000")),
        reload=bool(os.getenv("CYBERWATCH_API_RELOAD", "")),
    )
