"""Configuration loader for the DNS collector."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, List

import yaml
from pydantic import BaseModel, Field, ValidationError


class PiholeConfig(BaseModel):
    base_url: str = Field(default="http://pihole.local/admin/api.php")
    api_token: str = Field(default="REPLACE_ME")
    poll_interval_seconds: int = Field(default=30, ge=5)


class LogFileConfig(BaseModel):
    log_path: str = Field(default="/var/log/pihole.log")
    format: str = Field(default="pihole_ftl")
    poll_interval_seconds: int = Field(default=10, ge=1)


class FilterConfig(BaseModel):
    ignore_domains_suffix: List[str] = Field(default_factory=list)
    ignore_qtypes: List[str] = Field(default_factory=list)
    ignore_clients: List[str] = Field(default_factory=list)
    max_domain_length: int = Field(default=255, ge=1)


class DNSResolutionConfig(BaseModel):
    enabled: bool = Field(default=True)
    timeout_seconds: float = Field(default=2.0, gt=0)
    max_ips_per_domain: int = Field(default=4, ge=1)


class DNSCollectorConfig(BaseModel):
    enabled: bool = Field(default=True)
    source: Literal["pihole", "logfile"] = Field(default="pihole")
    pihole: PiholeConfig = Field(default_factory=PiholeConfig)
    logfile: LogFileConfig = Field(default_factory=LogFileConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    dns_resolution: DNSResolutionConfig = Field(default_factory=DNSResolutionConfig)

    @classmethod
    def load(cls, path: str) -> "DNSCollectorConfig":
        cfg_path = Path(path)
        if not cfg_path.exists():
            raise FileNotFoundError(f"DNS config not found: {cfg_path}")
        try:
            raw = yaml.safe_load(cfg_path.read_text()) or {}
            return cls(**raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid DNS config: {exc}") from exc

    @property
    def poll_interval(self) -> int:
        if self.source == "pihole":
            return self.pihole.poll_interval_seconds
        return self.logfile.poll_interval_seconds
