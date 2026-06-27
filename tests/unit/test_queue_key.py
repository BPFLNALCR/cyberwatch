from __future__ import annotations

from cyberWatch.scheduler.queue import (
    CANONICAL_TARGET_QUEUE_KEY,
    LEGACY_TARGET_QUEUE_KEY,
    TargetQueue,
    queue_key_migration_message,
    queue_key_status,
)


def test_target_queue_uses_lowercase_canonical_key_by_default() -> None:
    assert CANONICAL_TARGET_QUEUE_KEY == "cyberwatch:targets"
    assert TargetQueue().queue_key == CANONICAL_TARGET_QUEUE_KEY


def test_legacy_mixed_case_key_is_detectable() -> None:
    assert LEGACY_TARGET_QUEUE_KEY == "cyberWatch:targets"
    status = queue_key_status(canonical_depth=0, legacy_depth=3)
    assert status["status"] == "WARN"
    assert status["legacy_key"] == LEGACY_TARGET_QUEUE_KEY
    assert status["canonical_key"] == CANONICAL_TARGET_QUEUE_KEY


def test_redis_queue_migration_message_names_both_keys() -> None:
    message = queue_key_migration_message(canonical_depth=0, legacy_depth=3)

    assert CANONICAL_TARGET_QUEUE_KEY in message
    assert LEGACY_TARGET_QUEUE_KEY in message
    assert "RPOPLPUSH" in message
    assert "3" in message
