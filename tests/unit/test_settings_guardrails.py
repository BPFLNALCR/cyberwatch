from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from cyberWatch.api.routes import settings
from cyberWatch.api.routes.settings import (
    DESTRUCTIVE_SETTINGS_OPT_IN_ENV,
    DESTRUCTIVE_SETTINGS_POLICY_KEY,
    destructive_settings_enabled,
    require_destructive_settings_enabled,
)


def test_destructive_settings_default_to_disabled() -> None:
    assert destructive_settings_enabled(environ={}) is False


def test_destructive_settings_env_opt_in_is_explicit() -> None:
    assert destructive_settings_enabled(environ={DESTRUCTIVE_SETTINGS_OPT_IN_ENV: "1"}) is True
    assert destructive_settings_enabled(environ={DESTRUCTIVE_SETTINGS_OPT_IN_ENV: "true"}) is True
    assert destructive_settings_enabled(environ={DESTRUCTIVE_SETTINGS_OPT_IN_ENV: "0"}) is False


def test_destructive_settings_table_policy_is_explicit() -> None:
    assert destructive_settings_enabled(environ={}, policy={DESTRUCTIVE_SETTINGS_POLICY_KEY: True}) is True
    assert destructive_settings_enabled(environ={}, policy={"enabled": True}) is True
    assert destructive_settings_enabled(environ={}, policy={DESTRUCTIVE_SETTINGS_POLICY_KEY: False}) is False


@pytest.mark.parametrize(
    "action",
    ["clear_measurements", "clear_dns", "clear_graph", "clear_all"],
)
def test_destructive_actions_raise_403_by_default(action: str) -> None:
    with pytest.raises(HTTPException) as exc:
        require_destructive_settings_enabled(action, environ={})

    assert exc.value.status_code == 403
    assert action in str(exc.value.detail)
    assert DESTRUCTIVE_SETTINGS_OPT_IN_ENV in str(exc.value.detail)


def test_destructive_actions_are_allowed_after_explicit_opt_in() -> None:
    require_destructive_settings_enabled(
        "clear_dns",
        environ={DESTRUCTIVE_SETTINGS_OPT_IN_ENV: "yes"},
    )


@pytest.mark.parametrize(
    ("action", "call"),
    [
        ("clear_measurements", lambda: settings.clear_measurements(pool=object(), request=None)),
        ("clear_dns", lambda: settings.clear_dns(pool=object(), request=None)),
        ("clear_graph", lambda: settings.clear_graph(pool=object(), driver=object(), request=None)),
        ("clear_all", lambda: settings.clear_all(pool=object(), driver=object(), request=None)),
    ],
)
def test_destructive_endpoint_handlers_raise_403_by_default(action: str, call) -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(call())

    assert exc.value.status_code == 403
    assert action in str(exc.value.detail)
    assert DESTRUCTIVE_SETTINGS_OPT_IN_ENV in str(exc.value.detail)
