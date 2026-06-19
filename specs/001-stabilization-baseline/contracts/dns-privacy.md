# Contract: DNS Client-IP Privacy

## Goal

New DNS ingestion omits client-identifying fields by default while preserving DNS-derived target creation and pre-storage filtering.

## Configuration

YAML config:

```yaml
privacy:
  store_client_ips: false
```

Environment override:

```text
CYBERWATCH_DNS_STORE_CLIENT_IPS=false
```

Env values are interpreted case-insensitively after trimming whitespace.

True-like values:

- `1`
- `true`
- `yes`
- `on`

False-like values:

- unset
- `0`
- `false`
- `no`
- `off`

## Required Behavior

- Default new ingestion stores `NULL` for `dns_queries.client_ip`.
- Default new ingestion stores `NULL` for `dns_targets.last_client_ip`.
- If client-IP storage is enabled, current client field persistence behavior is preserved.
- `filters.ignore_clients` still works before storage suppression.
- Existing historical rows are not modified.
- Schema columns remain nullable for compatibility and lab opt-in.

## Validation

- Unit tests cover default privacy behavior.
- Unit tests cover env/config opt-in.
- Unit tests cover that records prepared for persistence contain `None` for client fields when privacy mode suppresses storage.

