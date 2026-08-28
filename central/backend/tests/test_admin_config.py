"""The runtime-config endpoints: whitelist only, admin only, applied live, never secrets."""

import json
import logging

from app.config import get_settings
from app.core.logging_setup import get_runtime_logging

from conftest import ADMIN, auth


def _login(client):
    return client.post("/api/auth/login", json=ADMIN).json()["access_token"]


def test_config_is_admin_only(client, investigator):
    assert client.get("/api/admin/config", headers=auth(investigator["token"])).status_code == 403
    res = client.put(
        "/api/admin/config",
        json={"values": {"slow_query_ms": 500}},
        headers=auth(investigator["token"]),
    )
    assert res.status_code == 403


def test_the_whitelist_never_contains_secrets(client):
    res = client.get("/api/admin/config", headers=auth(_login(client)))
    assert res.status_code == 200, res.text
    dump = json.dumps(res.json()).lower()
    for forbidden in ("jwt", "secret", "password", "database_url", "private_key", "bootstrap"):
        assert forbidden not in dump, f"a {forbidden!r} setting must never reach a browser"
    keys = {f["key"] for f in res.json()["fields"]}
    assert "voice_match_threshold" in keys
    assert "log_level" in keys


def test_changes_apply_to_the_running_process_immediately(client):
    token = auth(_login(client))
    original = get_settings().voice_match_threshold
    try:
        res = client.put(
            "/api/admin/config",
            json={"values": {"voice_match_threshold": 0.72, "slow_query_ms": 5000}},
            headers=token,
        )
        assert res.status_code == 200, res.text
        # The very next get_settings() call - i.e. the next request - sees the new value.
        assert get_settings().voice_match_threshold == 0.72
        assert get_runtime_logging()["slow_query_ms"] == 5000
        by_key = {f["key"]: f["value"] for f in res.json()["fields"]}
        assert by_key["voice_match_threshold"] == 0.72
    finally:
        client.put(
            "/api/admin/config",
            json={"values": {"voice_match_threshold": original, "slow_query_ms": 200}},
            headers=token,
        )
    assert get_settings().voice_match_threshold == original


def test_log_level_change_takes_effect_and_reverts(client):
    token = auth(_login(client))
    try:
        res = client.put(
            "/api/admin/config", json={"values": {"log_level": "DEBUG"}}, headers=token
        )
        assert res.status_code == 200, res.text
        assert logging.getLogger().level == logging.DEBUG
    finally:
        client.put("/api/admin/config", json={"values": {"log_level": "INFO"}}, headers=token)
    assert logging.getLogger().level == logging.INFO


def test_invalid_values_are_refused_and_nothing_half_applies(client):
    token = auth(_login(client))
    before = get_settings().voice_match_threshold

    res = client.put(
        "/api/admin/config", json={"values": {"not_a_setting": 1}}, headers=token
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "unknown_config_key"

    # Out-of-bounds threshold: 0.2 would suggest near-strangers.
    res = client.put(
        "/api/admin/config", json={"values": {"voice_match_threshold": 0.2}}, headers=token
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "config_value_out_of_bounds"

    # One good + one bad key: the good one must NOT be applied.
    res = client.put(
        "/api/admin/config",
        json={"values": {"voice_match_threshold": 0.80, "log_level": "NONSENSE"}},
        headers=token,
    )
    assert res.status_code == 422
    assert get_settings().voice_match_threshold == before, "validation must precede application"


def test_logger_override_applies_and_clears(client):
    token = auth(_login(client))
    probe = logging.getLogger("app.services.voice_matching")
    try:
        client.put(
            "/api/admin/config",
            json={"values": {"log_levels": "app.services.voice_matching=DEBUG"}},
            headers=token,
        )
        assert probe.level == logging.DEBUG
        # Removing it from the spec returns the logger to inheritance, not to a stale level.
        client.put("/api/admin/config", json={"values": {"log_levels": ""}}, headers=token)
        assert probe.level == logging.NOTSET
    finally:
        client.put("/api/admin/config", json={"values": {"log_levels": ""}}, headers=token)


def test_scaled_units_display_friendly_and_store_canonical(client):
    """MB and minutes on the page; bytes and seconds in the process and in .env."""
    token = auth(_login(client))
    res = client.get("/api/admin/config", headers=token)
    by_key = {f["key"]: f for f in res.json()["fields"]}
    assert by_key["max_upload_bytes"]["value"] == 2048, "2 GiB shown as 2048 MB"
    assert "ميغابايت" in by_key["max_upload_bytes"]["label"]
    assert by_key["processing_token_submit_ttl_seconds"]["value"] == 1440, "86400s shown as 1440 min"
    assert "دقائق" in by_key["processing_token_submit_ttl_seconds"]["label"]

    try:
        res = client.put(
            "/api/admin/config",
            json={"values": {"max_upload_bytes": 100, "processing_token_submit_ttl_seconds": 120}},
            headers=token,
        )
        assert res.status_code == 200, res.text
        # Canonical values changed underneath...
        assert get_settings().max_upload_bytes == 100 * 1024 * 1024
        assert get_settings().processing_token_submit_ttl_seconds == 120 * 60
        # ...while the page keeps speaking MB / minutes.
        by_key = {f["key"]: f["value"] for f in res.json()["fields"]}
        assert by_key["max_upload_bytes"] == 100
        assert by_key["processing_token_submit_ttl_seconds"] == 120
        # Bounds are enforced in the DISPLAYED unit: 9000 MB is over the 8192 cap.
        res = client.put(
            "/api/admin/config", json={"values": {"max_upload_bytes": 9000}}, headers=token
        )
        assert res.status_code == 422
    finally:
        client.put(
            "/api/admin/config",
            json={"values": {"max_upload_bytes": 2048, "processing_token_submit_ttl_seconds": 1440}},
            headers=token,
        )
    assert get_settings().max_upload_bytes == 2 * 1024 * 1024 * 1024
