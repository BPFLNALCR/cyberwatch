"""DNS data sources (Pi-hole API, log tail)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Protocol

import aiohttp

from cyberWatch.collector.config import LogFileConfig, PiholeConfig
from cyberWatch.collector.models import DNSQuery

MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


class DNSSource(Protocol):
    poll_interval: int

    async def fetch_new(self) -> List[DNSQuery]:
        ...


class PiholeApiSource:
    """Fetch DNS queries via Pi-hole HTTP API."""

    def __init__(self, cfg: PiholeConfig) -> None:
        self.cfg = cfg
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_seen_ts: float = 0.0
        self.poll_interval = cfg.poll_interval_seconds

    async def _client(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def fetch_new(self) -> List[DNSQuery]:
        client = await self._client()
        params = {"getAllQueries": 1, "auth": self.cfg.api_token}
        try:
            async with client.get(self.cfg.base_url, params=params) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except Exception:
            return []

        rows = payload.get("data") or payload.get("queries") or []
        queries: List[DNSQuery] = []
        for row in rows:
            # Expected: [timestamp, type, domain, client, status, reply_type]
            try:
                ts_raw = float(row[0])
                domain = row[2]
                client_ip = row[3] if len(row) >= 4 else None
                qtype = str(row[1]) if len(row) >= 2 else None
            except (ValueError, TypeError, IndexError):
                continue
            if ts_raw <= self.last_seen_ts:
                continue
            ts = datetime.utcfromtimestamp(ts_raw)
            queries.append(DNSQuery(domain=domain, client_ip=client_ip, qtype=qtype, timestamp=ts))

        if queries:
            self.last_seen_ts = max(q.timestamp.timestamp() for q in queries)
        return queries

    async def close(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None


FTL_PATTERN = re.compile(
    r"^(?P<mon>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2}).*?query\[(?P<qtype>[A-Z]+)\]\s+(?P<domain>\S+)\s+from\s+(?P<client>\S+)",
)


class LogFileTailSource:
    """Tail a DNS resolver log file."""

    def __init__(self, cfg: LogFileConfig) -> None:
        self.cfg = cfg
        self.poll_interval = cfg.poll_interval_seconds
        self.path = Path(cfg.log_path)
        self._offset = 0
        self._inode: Optional[int] = None

    def _reset_if_rotated(self) -> None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._offset = 0
            self._inode = None
            return
        inode = getattr(stat, "st_ino", None)
        if self._inode is None:
            self._inode = inode
            self._offset = 0
        elif inode is not None and self._inode != inode:
            # File rotated
            self._inode = inode
            self._offset = 0
        elif stat.st_size < self._offset:
            # Truncated
            self._offset = 0

    def _parse_line(self, line: str) -> Optional[DNSQuery]:
        match = FTL_PATTERN.match(line)
        if not match:
            return None
        mon = match.group("mon")
        day = int(match.group("day"))
        time_str = match.group("time")
        year = datetime.utcnow().year
        month = MONTHS.get(mon)
        if not month:
            return None
        ts = datetime.strptime(f"{year}-{month:02d}-{day:02d} {time_str}", "%Y-%m-%d %H:%M:%S")
        return DNSQuery(
            domain=match.group("domain"),
            client_ip=match.group("client"),
            qtype=match.group("qtype"),
            timestamp=ts,
        )

    async def fetch_new(self) -> List[DNSQuery]:
        self._reset_if_rotated()
        if not self.path.exists():
            return []

        try:
            with self.path.open("r", encoding="utf-8", errors="ignore") as fh:
                fh.seek(self._offset)
                lines = fh.readlines()
                self._offset = fh.tell()
        except FileNotFoundError:
            return []

        queries: List[DNSQuery] = []
        for line in lines:
            q = self._parse_line(line.strip())
            if q:
                queries.append(q)
        return queries


async def build_source(kind: str, pihole: PiholeConfig, logfile: LogFileConfig) -> DNSSource:
    if kind == "pihole":
        return PiholeApiSource(pihole)
    if kind == "logfile":
        return LogFileTailSource(logfile)
    raise ValueError(f"Unsupported DNS source: {kind}")
