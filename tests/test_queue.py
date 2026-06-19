from cyberWatch.scheduler.queue import TargetQueue


def test_default_queue_key_is_lowercase():
    assert TargetQueue().queue_key == "cyberwatch:targets"
    assert TargetQueue("redis://example.invalid/0").queue_key == "cyberwatch:targets"


def test_queue_key_override_is_preserved():
    assert TargetQueue(queue_key="custom").queue_key == "custom"
