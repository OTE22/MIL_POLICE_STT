"""Token validation, localhost-only binding and CORS/PNA behaviour."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import Settings
from app.jobs.store import JobStore
from app.main import assert_loopback_binding
from app.security.token_validation import ProcessingTokenValidator, PublicKeyProvider, TokenValidationError
from tests.conftest import make_token


@pytest.fixture
def validator(settings: Settings, keypair):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(settings.db_path)
    yield ProcessingTokenValidator(settings, store, PublicKeyProvider(settings)), keypair
    store.close()


def test_valid_token_accepted(validator):
    v, kp = validator
    token, claims = make_token(kp["private"])
    out = v.validate(token)
    assert out.job_id == claims["job_id"]
    assert out.nonce == claims["jti"]


def test_replay_rejected(validator):
    v, kp = validator
    token, _ = make_token(kp["private"])
    v.validate(token)
    with pytest.raises(TokenValidationError) as exc:
        v.validate(token)
    assert exc.value.code == "token_replay"


def test_expired_token_rejected(validator):
    v, kp = validator
    token, _ = make_token(kp["private"], exp_seconds=-400)
    with pytest.raises(TokenValidationError) as exc:
        v.validate(token)
    assert exc.value.code == "token_expired"


def test_acceptance_window_passed_rejected(validator):
    v, kp = validator
    token, _ = make_token(kp["private"], accept_seconds=-400, exp_seconds=3600)
    with pytest.raises(TokenValidationError) as exc:
        v.validate(token)
    assert exc.value.code == "token_expired"


def test_wrong_key_rejected(validator):
    v, _ = validator
    other = ec.generate_private_key(ec.SECP256R1())
    pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    token, _ = make_token(pem)
    with pytest.raises(TokenValidationError) as exc:
        v.validate(token)
    assert exc.value.code == "token_invalid"


@pytest.mark.parametrize("kw", [{"action": "something_else"}, {"issuer": "evil"}, {"audience": "other"}])
def test_wrong_claims_rejected(validator, kw):
    v, kp = validator
    token, _ = make_token(kp["private"], **kw)
    with pytest.raises(TokenValidationError):
        v.validate(token)


def test_garbage_rejected(validator):
    v, _ = validator
    with pytest.raises(TokenValidationError):
        v.validate("not-a-token")


def test_missing_public_key_reported(settings: Settings, tmp_path):
    settings.central_public_key_path = tmp_path / "missing.pem"
    store = JobStore(settings.db_path)
    v = ProcessingTokenValidator(settings, store, PublicKeyProvider(settings))
    with pytest.raises(TokenValidationError) as exc:
        v.validate("x.y.z")
    assert exc.value.code == "public_key_missing"
    store.close()


def test_non_loopback_bind_refused(settings: Settings):
    settings.bind_host = "0.0.0.0"
    settings.allow_non_loopback_bind = False
    with pytest.raises(SystemExit):
        assert_loopback_binding(settings)


def test_loopback_bind_ok(settings: Settings):
    settings.bind_host = "127.0.0.1"
    assert_loopback_binding(settings)
    settings.bind_host = "0.0.0.0"
    settings.allow_non_loopback_bind = True
    assert_loopback_binding(settings)  # administrator override


def test_cors_and_private_network_headers(agent_app):
    client = agent_app["client"]
    res = client.options(
        "/jobs",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:8080"
    assert res.headers.get("access-control-allow-private-network") == "true"
    # Unknown origins are not allowed.
    res = client.options("/jobs", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert res.headers.get("access-control-allow-origin") is None
