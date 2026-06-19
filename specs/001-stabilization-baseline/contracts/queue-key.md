# Contract: Redis Target Queue Key

## Canonical Key

`cyberwatch:targets`

## Required Behavior

- `TargetQueue()` uses `cyberwatch:targets` by default.
- `TargetQueue(redis_url)` uses `cyberwatch:targets` by default.
- `TargetQueue(queue_key="custom")` continues to use the caller-provided key.
- Documentation and operator commands use `redis-cli LLEN cyberwatch:targets`.

## Validation

- Unit test: `TargetQueue().queue_key == "cyberwatch:targets"`.
- Unit test: explicit override remains supported.
- Documentation check: no remaining default examples point to `cyberWatch:targets`.

