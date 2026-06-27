"""Data models for DNS ingestion."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, IPvAnyAddress, ConfigDict


class DNSQuery(BaseModel):
    """Raw DNS query observed from a resolver."""
    domain: str
    client_ip: Optional[str] = None
    qtype: Optional[str] = None
    timestamp: datetime

    model_config = ConfigDict(extra="ignore")


class ResolvedTarget(BaseModel):
    """Domain resolved to an IP, ready for storage/enqueue."""
    domain: str
    ip: IPvAnyAddress
    queried_at: datetime
    client_ip: Optional[str] = None
    qtype: Optional[str] = None

    model_config = ConfigDict(extra="ignore")
