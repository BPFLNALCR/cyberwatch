# cyberWatch DNS Integration (Phase 4)

This collector turns local DNS queries into measurement targets for cyberWatch.

## Setup
- Apply schemas: `psql $DSN -f cyberWatch/db/schema.sql` then `psql $DSN -f cyberWatch/db/dns_schema.sql`.
- Copy the sample config: `sudo mkdir -p /etc/cyberwatch && sudo cp config/cyberwatch_dns.example.yaml /etc/cyberwatch/dns.yaml`.
- Adjust `/etc/cyberwatch/dns.yaml` for your resolver (Pi-hole API or log file tail).

## Running manually
- Activate the virtualenv: `source .venv/bin/activate`.
- Start the collector: `python -m cyberWatch.collector.dns_collector --config /etc/cyberwatch/dns.yaml`.
- Logs report processed queries and enqueued targets.

## Systemd service
- Unit: `systemd/cyberWatch-dns-collector.service`.
- Installed automatically by `install-cyberWatch.sh`; disable with `sudo systemctl disable --now cyberWatch-dns-collector.service` if not needed.

## Notes
- Filters can ignore suffixes (e.g., `.local`, `.lan`) and qtypes (e.g., PTR).
- DNS resolution can be disabled or limited via `dns_resolution` settings.
- Targets are enqueued with `source="dns"`; deduplication happens per cycle.
