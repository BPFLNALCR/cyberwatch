"""DNS data sources (Pi-hole API, log tail)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import aiohttp

from cyberWatch.collector.config import LogFileConfig, PiholeConfig
from cyberWatch.collector.models import DNSQuery
from cyberWatch.logging_config import get_logger

logger = get_logger("collector")

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
    """Fetch DNS queries via Pi-hole HTTP API (supports v5 and v6)."""

    def __init__(self, cfg: PiholeConfig) -> None:
        self.cfg = cfg
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_seen_ts: float = 0.0
        self.poll_interval = cfg.poll_interval_seconds
        self._api_version: Optional[str] = None
        self._session_id: Optional[str] = None

    async def _client(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def _detect_api_version(self) -> str:
        """Detect Pi-hole API version (v5 or v6)."""
        if self._api_version:
            return self._api_version
        
        client = await self._client()
        base_url = self.cfg.base_url.rstrip("/")
        
        # Try v6 auth endpoint first
        try:
            auth_url = f"{base_url}/api/auth"
            async with client.post(auth_url, json={"password": self.cfg.api_token}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sid = data.get("session", {}).get("sid")
                    if sid:
                        self._api_version = "v6"
                        self._session_id = sid
                        logger.info(
                            "Pi-hole v6 API detected and authenticated",
                            extra={"api_version": "v6"}
                        )
                        return "v6"
                elif resp.status == 401:
                    logger.warning("Pi-hole v6 authentication failed: invalid password")
                    self._api_version = "v6"
                    return "v6"
        except Exception as e:
            logger.debug(f"v6 auth check failed: {e}")
        
        # Fallback to v5
        self._api_version = "v5"
        logger.info("Using Pi-hole v5 API", extra={"api_version": "v5"})
        return "v5"

    async def _authenticate_v6(self) -> Optional[str]:
        """Authenticate with Pi-hole v6 and get session ID."""
        if self._session_id:
            return self._session_id
        
        client = await self._client()
        base_url = self.cfg.base_url.rstrip("/")
        
        try:
            auth_url = f"{base_url}/api/auth"
            async with client.post(auth_url, json={"password": self.cfg.api_token}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._session_id = data.get("session", {}).get("sid")
                    if self._session_id:
                        logger.debug("Pi-hole v6 session acquired")
                    return self._session_id
                else:
                    logger.warning(f"Pi-hole v6 auth failed: HTTP {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Pi-hole v6 authentication error: {e}")
            return None

    async def _fetch_v6(self) -> List[DNSQuery]:
        """Fetch queries using Pi-hole v6 API."""
        sid = await self._authenticate_v6()
        if not sid:
            logger.warning("Cannot fetch queries: no valid v6 session")
            return []
        
        client = await self._client()
        base_url = self.cfg.base_url.rstrip("/")
        queries_url = f"{base_url}/api/queries"
        headers = {"sid": sid}
        
        try:
            async with client.get(queries_url, headers=headers) as resp:
                if resp.status == 401:
                    # Session expired, clear and retry
                    self._session_id = None
                    sid = await self._authenticate_v6()
                    if not sid:
                        return []
                    headers = {"sid": sid}
                    async with client.get(queries_url, headers=headers) as retry_resp:
                        if retry_resp.status != 200:
                            return []
                        payload = await retry_resp.json()
                elif resp.status != 200:
                    logger.warning(f"Pi-hole v6 queries fetch failed: HTTP {resp.status}")
                    return []
                else:
                    payload = await resp.json()
        except Exception as e:
            logger.error(f"Pi-hole v6 fetch error: {e}")
            return []
        
        # v6 response format: {"queries": [...]}
        rows = payload.get("queries", [])
        queries: List[DNSQuery] = []
        
        for row in rows:
            try:
                # v6 format: each row is a dict with keys like:
                # {time, domain, client, type, status, ...}
                if isinstance(row, dict):
                    ts_raw = float(row.get("time", 0))
                    domain = row.get("domain", "")
                    client_ip = row.get("client")
                    qtype = row.get("type")
                else:
                    # Fallback for array format
                    ts_raw = float(row[0])
                    domain = row[2] if len(row) > 2 else ""
                    client_ip = row[3] if len(row) > 3 else None
                    qtype = str(row[1]) if len(row) > 1 else None
                
                if not domain or ts_raw <= self.last_seen_ts:
                    continue
                
                ts = datetime.utcfromtimestamp(ts_raw)
                queries.append(DNSQuery(
                    domain=domain,
                    client_ip=client_ip,
                    qtype=qtype,
                    timestamp=ts,
                ))
            except (ValueError, TypeError, IndexError, KeyError) as e:
                logger.debug(f"Failed to parse v6 query row: {e}")
                continue
        
        if queries:
            self.last_seen_ts = max(q.timestamp.timestamp() for q in queries)
        
        return queries

    async def _fetch_v5(self) -> List[DNSQuery]:
        """Fetch queries using Pi-hole v5 API."""
        client = await self._client()
        base_url = self.cfg.base_url.rstrip("/")
        
        # Ensure we use the correct v5 endpoint
        if "/admin/api.php" not in base_url:
            api_url = f"{base_url}/admin/api.php"
        else:
            api_url = base_url
        
        params = {"getAllQueries": "1", "auth": self.cfg.api_token}
        
        try:
            async with client.get(api_url, params=params) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except Exception as e:
            logger.error(f"Pi-hole v5 fetch error: {e}")
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
            queries.append(DNSQuery(
                domain=domain,
                client_ip=client_ip,
                qtype=qtype,
                timestamp=ts,
            ))
        
        if queries:
            self.last_seen_ts = max(q.timestamp.timestamp() for q in queries)
        
        return queries

    async def fetch_new(self) -> List[DNSQuery]:
        """Fetch new DNS queries from Pi-hole."""
        api_version = await self._detect_api_version()
        
        if api_version == "v6":
            return await self._fetch_v6()
        else:
            return await self._fetch_v5()

    async def close(self) -> None:
        """Close the HTTP session and logout from v6 if needed."""
        if self._session_id and self.session and not self.session.closed:
            try:
                base_url = self.cfg.base_url.rstrip("/")
                headers = {"sid": self._session_id}
                await self.session.delete(f"{base_url}/api/auth", headers=headers)
                logger.debug("Logged out from Pi-hole v6")
            except Exception:
                pass
        
        if self.session:
            await self.session.close()
            self.session = None
        
        self._session_id = None


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
