"""FastAPI application entrypoint for cyberWatch API."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cyberWatch.api.routes import measurements, traceroute, targets, asn, graph, dns
from cyberWatch.api.utils import db

app = FastAPI(title="cyberWatch-api", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(measurements.router)
app.include_router(traceroute.router)
app.include_router(targets.router)
app.include_router(asn.router)
app.include_router(graph.router)
app.include_router(dns.router)


@app.on_event("startup")
async def startup_event() -> None:
    await db.init_resources()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await db.close_resources()


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
