# cyberWatch DNS Integration (Phase 4)

This collector turns local DNS queries into measurement targets for cyberWatch.

## Quick Start (Web UI)

The easiest way to configure Pi-hole integration:

1. Navigate to the CyberWatch UI at `http://your-server:8080/settings`
2. Enter your Pi-hole URL (e.g., `http://192.168.1.10` or `http://pi.hole`)
3. Enter your Pi-hole password (v6) or API token (v5)
4. Click "Test Connection" to verify connectivity
5. Click "Save Settings"
6. Restart the DNS collector: `sudo systemctl restart cyberWatch-dns-collector`

## Pi-hole Version Compatibility

### Pi-hole v6
- Uses session-based authentication
- Enter your Pi-hole web interface **password** as the API token
- CyberWatch automatically detects v6 and authenticates via `/api/auth`

### Pi-hole v5
- Uses token-based authentication
- Find your API token in Pi-hole: Settings → API → Show API token
- CyberWatch appends `/admin/api.php` automatically

## Setup (Manual Configuration)
- Apply schemas: `psql $DSN -f cyberWatch/db/schema.sql` then `psql $DSN -f cyberWatch/db/dns_schema.sql`.
- Copy the sample config: `sudo mkdir -p /etc/cyberwatch && sudo cp config/cyberwatch_dns.example.yaml /etc/cyberwatch/dns.yaml`.
- Adjust `/etc/cyberwatch/dns.yaml` for your resolver (Pi-hole API or log file tail).

**Note:** Settings configured via the Web UI take precedence over the config file.

## Running manually
- Activate the virtualenv: `source .venv/bin/activate`.
- Start the collector: `python -m cyberWatch.collector.dns_collector --config /etc/cyberwatch/dns.yaml`.
- Logs report processed queries and enqueued targets.

## Systemd service
- Unit: `systemd/cyberWatch-dns-collector.service`.
- Installed automatically by `install-cyberWatch.sh`; disable with `sudo systemctl disable --now cyberWatch-dns-collector.service` if not needed.

## Viewing DNS Data

- **DNS Activity page** (`/dns`): View top domains and ASN distribution
- **Grafana dashboards**: Time-series visualization of DNS query patterns
- **API endpoints**:
  - `GET /dns/top-domains`: Most queried domains
  - `GET /dns/top-asns`: ASN distribution by DNS queries

## Notes
- Filters can ignore suffixes (e.g., `.local`, `.lan`) and qtypes (e.g., PTR).
- DNS resolution can be disabled or limited via `dns_resolution` settings.
- Targets are enqueued with `source="dns"`; deduplication happens per cycle.
- The collector re-checks database settings each cycle, allowing dynamic enable/disable.
