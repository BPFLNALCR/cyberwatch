"""DNS data sources (Pi-hole API, log tail)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import aiohttp

from cyberWatch.collector.config import LogFileConfig, PiholeConfig
from cyberWatch.collector.models import DNSQuery
from cyberWatch.logging_config import get_logger

logger = get_logger("collector")


class PiholeApiError(RuntimeError):
    pass


class PiholeAuthError(PiholeApiError):
    pass

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
            
            # Handle SSL verification for self-signed certificates
            import ssl
            ssl_context = None
            if not self.cfg.verify_ssl:
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                logger.debug("SSL verification disabled for Pi-hole connection")
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self.session

    async def _detect_api_version(self) -> str:
        """Detect Pi-hole API version (v5 or v6)."""
        if self._api_version:
            return self._api_version
        
        client = await self._client()
        base_url = self._base_url_for_v6()
        
        # Try v6 auth endpoint first
        auth_url = f"{base_url}/api/auth"
        try:
            async with client.post(auth_url, json={"password": self.cfg.api_token}) as resp:
                content_type = resp.headers.get("Content-Type")
                content_length = resp.headers.get("Content-Length")
                if resp.status == 200:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception as exc:
                        body_preview = (await resp.text())[:200]
                        raise PiholeApiError(
                            f"Pi-hole v6 auth returned non-JSON body (content-type={content_type}, len={content_length}): {body_preview!r}"
                        ) from exc

                    sid = data.get("session", {}).get("sid")
                    if sid:
                        self._api_version = "v6"
                        self._session_id = sid
                        logger.info(
                            "Pi-hole v6 API detected and authenticated",
                            extra={"api_version": "v6"},
                        )
                        return "v6"

                    raise PiholeApiError("Pi-hole v6 auth succeeded but no session.sid returned")

                if resp.status in {401, 403}:
                    body_preview = (await resp.text())[:200]
                    self._api_version = "v6"
                    raise PiholeAuthError(
                        f"Pi-hole v6 authentication failed (HTTP {resp.status}). Check the configured password. Body={body_preview!r}"
                    )

                # If the endpoint doesn't exist (older Pi-hole), treat as not v6.
                if resp.status in {404, 405}:
                    raise aiohttp.ClientResponseError(
                        request_info=resp.request_info,
                        history=resp.history,
                        status=resp.status,
                        message=f"v6 auth endpoint not supported (HTTP {resp.status})",
                        headers=resp.headers,
                    )

                body_preview = (await resp.text())[:200]
                raise PiholeApiError(
                    f"Pi-hole v6 auth check unexpected HTTP {resp.status} (content-type={content_type}, len={content_length}) body={body_preview!r}"
                )
        except PiholeAuthError:
            raise
        except PiholeApiError:
            raise
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
        base_url = self._base_url_for_v6()
        
        auth_url = f"{base_url}/api/auth"
        async with client.post(auth_url, json={"password": self.cfg.api_token}) as resp:
            content_type = resp.headers.get("Content-Type")
            content_length = resp.headers.get("Content-Length")
            if resp.status == 200:
                try:
                    data = await resp.json(content_type=None)
                except Exception as exc:
                    body_preview = (await resp.text())[:200]
                    raise PiholeApiError(
                        f"Pi-hole v6 auth returned non-JSON body (content-type={content_type}, len={content_length}): {body_preview!r}"
                    ) from exc

                self._session_id = data.get("session", {}).get("sid")
                if self._session_id:
                    logger.debug("Pi-hole v6 session acquired")
                    return self._session_id
                raise PiholeApiError("Pi-hole v6 auth succeeded but no session.sid returned")

            if resp.status in {401, 403}:
                body_preview = (await resp.text())[:200]
                raise PiholeAuthError(
                    f"Pi-hole v6 authentication failed (HTTP {resp.status}). Check the configured password. Body={body_preview!r}"
                )

            body_preview = (await resp.text())[:200]
            raise PiholeApiError(
                f"Pi-hole v6 auth failed: HTTP {resp.status} (content-type={content_type}, len={content_length}) body={body_preview!r}"
            )

    def _coerce_epoch_seconds(self, value: Any) -> Optional[float]:
        if value is None:
            return None

        ts: Optional[float] = None
        if isinstance(value, (int, float)):
            ts = float(value)
        elif isinstance(value, str):
            s = value.strip()
            # numeric string
            if re.fullmatch(r"\d+(?:\.\d+)?", s):
                ts = float(s)
            else:
                try:
                    # Handle trailing Z
                    if s.endswith("Z"):
                        s = s[:-1] + "+00:00"
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    ts = dt.timestamp()
                except Exception:
                    return None
        else:
            return None

        # Detect ms timestamps (e.g., 1700000000000)
        if ts > 1e11:
            ts = ts / 1000.0
        return ts

    def _extract_v6_fields(self, row: Dict[str, Any]) -> tuple[Optional[float], str, Optional[str], Optional[str]]:
        domain = row.get("domain") or row.get("query") or row.get("name") or ""
        if not isinstance(domain, str):
            domain = str(domain)
        domain = domain.strip()

        ts_raw = (
            row.get("time")
            or row.get("timestamp")
            or row.get("ts")
            or row.get("date")
            or row.get("queried_at")
        )
        ts = self._coerce_epoch_seconds(ts_raw)

        client = row.get("client") or row.get("client_ip") or row.get("clientIP")
        client_ip: Optional[str]
        if isinstance(client, dict):
            client_ip = client.get("ip") or client.get("address") or client.get("name")
        elif client is None:
            client_ip = None
        else:
            client_ip = str(client)

        qtype_val = row.get("type") or row.get("qtype") or row.get("query_type")
        qtype = str(qtype_val) if qtype_val is not None else None
        return ts, domain, client_ip, qtype

    async def _fetch_v6(self) -> List[DNSQuery]:
        """Fetch queries using Pi-hole v6 API."""
        sid = await self._authenticate_v6()
        if not sid:
            logger.warning("Cannot fetch queries: no valid v6 session")
            return []
        
        client = await self._client()
        base_url = self._base_url_for_v6()
        queries_url = f"{base_url}/api/queries"
        headers = {"sid": sid}
        
        async def _read_payload(r: aiohttp.ClientResponse) -> Dict[str, Any]:
            try:
                return await r.json(content_type=None)
            except Exception as exc:
                body_preview = (await r.text())[:200]
                raise PiholeApiError(
                    f"Pi-hole v6 queries returned non-JSON body (HTTP {r.status}, content-type={r.headers.get('Content-Type')}) preview={body_preview!r}"
                ) from exc

        async with client.get(queries_url, headers=headers) as resp:
            content_type = resp.headers.get("Content-Type")
            content_length = resp.headers.get("Content-Length")

            if resp.status == 401:
                # Session expired, clear and retry
                self._session_id = None
                sid = await self._authenticate_v6()
                if not sid:
                    return []
                headers = {"sid": sid}
                async with client.get(queries_url, headers=headers) as retry_resp:
                    if retry_resp.status != 200:
                        body_preview = (await retry_resp.text())[:200]
                        raise PiholeApiError(
                            f"Pi-hole v6 queries retry failed: HTTP {retry_resp.status} (content-type={retry_resp.headers.get('Content-Type')}) body={body_preview!r}"
                        )
                    payload = await _read_payload(retry_resp)
            elif resp.status != 200:
                body_preview = (await resp.text())[:200]
                raise PiholeApiError(
                    f"Pi-hole v6 queries fetch failed: HTTP {resp.status} (content-type={content_type}, len={content_length}) body={body_preview!r}"
                )
            else:
                payload = await _read_payload(resp)
        
        # v6 response format: {"queries": [...]}
        rows = payload.get("queries", [])
        queries: List[DNSQuery] = []

        received = len(rows) if isinstance(rows, list) else 0
        parsed = 0
        skipped_cursor = 0
        skipped_missing = 0
        parse_errors = 0
        
        for row in rows:
            try:
                # v6 format: each row is a dict with keys like:
                # {time, domain, client, type, status, ...}
                if isinstance(row, dict):
                    ts_raw, domain, client_ip, qtype = self._extract_v6_fields(row)
                else:
                    # Fallback for array format
                    ts_raw = self._coerce_epoch_seconds(row[0] if len(row) > 0 else None)
                    domain = row[2] if len(row) > 2 else ""
                    client_ip = row[3] if len(row) > 3 else None
                    qtype = str(row[1]) if len(row) > 1 else None

                if not domain or ts_raw is None:
                    skipped_missing += 1
                    continue
                if ts_raw <= self.last_seen_ts:
                    skipped_cursor += 1
                    continue

                ts = datetime.utcfromtimestamp(ts_raw)
                queries.append(DNSQuery(
                    domain=domain,
                    client_ip=client_ip,
                    qtype=qtype,
                    timestamp=ts,
                ))
                parsed += 1
            except (ValueError, TypeError, IndexError, KeyError) as e:
                logger.debug(f"Failed to parse v6 query row: {e}")
                parse_errors += 1
                continue
        
        if queries:
            self.last_seen_ts = max(q.timestamp.timestamp() for q in queries)

        # Make "0 queries" diagnosable.
        if received and not parsed:
            logger.warning(
                "Pi-hole v6 returned queries but none were parsed",
                extra={
                    "received": received,
                    "parsed": parsed,
                    "skipped_cursor": skipped_cursor,
                    "skipped_missing": skipped_missing,
                    "parse_errors": parse_errors,
                    "last_seen_ts": self.last_seen_ts,
                },
            )
        else:
            logger.debug(
                "Pi-hole v6 queries fetched",
                extra={
                    "received": received,
                    "parsed": parsed,
                    "skipped_cursor": skipped_cursor,
                    "skipped_missing": skipped_missing,
                    "parse_errors": parse_errors,
                },
            )
        
        return queries

    async def _fetch_v5(self) -> List[DNSQuery]:
        """Fetch queries using Pi-hole v5 API."""
        client = await self._client()
        api_url = self._v5_api_url()
        
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
        return await self._fetch_v5()

    async def close(self) -> None:
        """Close the HTTP session and logout from v6 if needed."""
        if self._session_id and self.session and not self.session.closed:
            try:
                base_url = self._base_url_for_v6()
                headers = {"sid": self._session_id}
                await self.session.delete(f"{base_url}/api/auth", headers=headers)
                logger.debug("Logged out from Pi-hole v6")
            except Exception:
                pass
        
        if self.session:
            await self.session.close()
            self.session = None
        
        self._session_id = None

    def _strip_known_suffixes(self, url: str) -> str:
        url = url.rstrip("/")
        for suffix in ("/admin/api.php", "/api.php", "/admin"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
                url = url.rstrip("/")
        return url

    def _base_url_for_v6(self) -> str:
        # v6 endpoints are rooted at /api/* (no /admin prefix)
        return self._strip_known_suffixes(self.cfg.base_url)

    def _v5_api_url(self) -> str:
        # v5 endpoint is /admin/api.php
        base = self._strip_known_suffixes(self.cfg.base_url)
        return f"{base}/admin/api.php"


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
