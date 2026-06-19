import pytest
from fastapi import HTTPException, status

from cyberWatch.api.routes.settings import (
    DESTRUCTIVE_SETTINGS_ENV,
    destructive_settings_enabled,
    require_destructive_settings_enabled,
)


def test_destructive_settings_disabled_by_default(monkeypatch):
    monkeypatch.delenv(DESTRUCTIVE_SETTINGS_ENV, raising=False)

    assert destructive_settings_enabled() is False


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", ""])
def test_destructive_settings_false_like_values_are_disabled(monkeypatch, value):
    monkeypatch.setenv(DESTRUCTIVE_SETTINGS_ENV, value)

    assert destructive_settings_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_destructive_settings_true_like_values_are_enabled(monkeypatch, value):
    monkeypatch.setenv(DESTRUCTIVE_SETTINGS_ENV, value)

    assert destructive_settings_enabled() is True
    require_destructive_settings_enabled("test-request")


def test_destructive_settings_guard_raises_clear_403(monkeypatch):
    monkeypatch.delenv(DESTRUCTIVE_SETTINGS_ENV, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        require_destructive_settings_enabled("test-request")

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert DESTRUCTIVE_SETTINGS_ENV in exc_info.value.detail
