"""Shared Pydantic models for the API layer."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, IPvAnyAddress


class APIStatus(BaseModel):
    status: str = Field(default="ok")


class ErrorResponse(APIStatus):
    detail: str
    status: str = Field(default="error")


class Hop(BaseModel):
    hop: int
    ip: Optional[str]
    rtt_ms: Optional[float]
    asn: Optional[int] = None
    org: Optional[str] = None


class MeasurementSummary(BaseModel):
    id: int
    target: str
    tool: str
    started_at: datetime
    completed_at: Optional[datetime]
    success: bool


class MeasurementDetail(MeasurementSummary):
    raw_output: Optional[str]


class TracerouteRequest(BaseModel):
    target: str


class TracerouteResponse(APIStatus):
    data: dict


class MtrResponse(APIStatus):
    data: dict


class TargetEnqueueRequest(BaseModel):
    target: IPvAnyAddress
    source: str = Field(default="api")


class TargetListItem(BaseModel):
    id: int
    target_ip: str
    source: Optional[str]
    last_seen: Optional[datetime]
    created_at: datetime


class ASNInfo(BaseModel):
    asn: int
    org_name: Optional[str]
    country: Optional[str]
    prefixes: List[str] = Field(default_factory=list)
    neighbors: List[int] = Field(default_factory=list)


class GraphPath(BaseModel):
    asns: List[int]
    length: int


class GraphNeighbors(BaseModel):
    asn: int
    neighbors: List[dict]


def ok(data: object) -> dict:
    return {"status": "ok", "data": data}


def err(detail: str) -> dict:
    return {"status": "error", "detail": detail}
