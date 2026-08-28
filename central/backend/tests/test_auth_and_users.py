from __future__ import annotations

from tests.conftest import ADMIN, auth, create_user, login


def test_successful_login_returns_token_and_me(client, admin_token):
    res = client.get("/api/auth/me", headers=auth(admin_token))
    assert res.status_code == 200
    body = res.json()
    assert body["username"] == "admin" and "ADMIN" in body["roles"] and "users.manage" in body["permissions"]


def test_invalid_login(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert res.status_code == 401 and res.json()["detail"] == "invalid_credentials"
    res = client.post("/api/auth/login", json={"username": "ghost", "password": "nope"})
    assert res.status_code == 401


def test_disabled_account_cannot_login(client, admin_token):
    user = create_user(client, admin_token, "temp", ["USER"])
    res = client.patch(f"/api/users/{user['id']}/status", json={"is_active": False}, headers=auth(admin_token))
    assert res.status_code == 200 and res.json()["is_active"] is False
    res = client.post("/api/auth/login", json={"username": "temp", "password": "Password!1234"})
    assert res.status_code == 403 and res.json()["detail"] == "account_disabled"
    # Re-activate
    client.patch(f"/api/users/{user['id']}/status", json={"is_active": True}, headers=auth(admin_token))
    assert client.post("/api/auth/login", json={"username": "temp", "password": "Password!1234"}).status_code == 200


def test_unauthenticated_and_bad_tokens(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_admin_authorization_required_for_user_management(client, investigator, viewer):
    for tok in (investigator["token"], viewer["token"]):
        assert client.get("/api/users", headers=auth(tok)).status_code == 403
        res = client.post("/api/users", json={"username": "x1", "password": "Password!1234", "roles": ["USER"], "profile": {"full_name": "x"}}, headers=auth(tok))
        assert res.status_code == 403


def test_user_creation_validation_and_profile(client, admin_token):
    user = create_user(client, admin_token, "Inv9", ["INVESTIGATOR"], full_name="م. خالد", rank="نقيب", military_id="M-9")
    assert user["username"] == "inv9" and user["profile"]["rank"] == "نقيب"
    # duplicate username / military id
    res = client.post("/api/users", json={"username": "inv9", "password": "Password!1234", "roles": ["USER"], "profile": {"full_name": "x", "military_id": "M-dup", "security_branch": "ARMY"}}, headers=auth(admin_token))
    assert res.status_code == 409 and res.json()["detail"] == "username_taken"
    res = client.post("/api/users", json={"username": "inv10", "password": "Password!1234", "roles": ["USER"], "profile": {"full_name": "x", "military_id": "M-9", "security_branch": "ARMY"}}, headers=auth(admin_token))
    assert res.status_code == 409 and res.json()["detail"] == "military_id_taken"
    # weak password / bad role
    res = client.post("/api/users", json={"username": "inv11", "password": "short", "roles": ["USER"], "profile": {"full_name": "x", "military_id": "M-11", "security_branch": "ARMY"}}, headers=auth(admin_token))
    assert res.status_code == 422
    res = client.post("/api/users", json={"username": "inv11", "password": "Password!1234", "roles": ["ROOT"], "profile": {"full_name": "x", "military_id": "M-12", "security_branch": "ARMY"}}, headers=auth(admin_token))
    assert res.status_code == 422


def test_role_change_password_reset_and_audit(client, admin_token):
    user = create_user(client, admin_token, "roleuser", ["USER"])
    res = client.put(f"/api/users/{user['id']}", json={"roles": ["INVESTIGATOR"], "profile": {"full_name": "الاسم الجديد", "unit": "الكتيبة 3", "military_id": "M-role", "security_branch": "ARMY"}}, headers=auth(admin_token))
    assert res.status_code == 200 and res.json()["roles"] == ["INVESTIGATOR"] and res.json()["profile"]["unit"] == "الكتيبة 3"
    res = client.post(f"/api/users/{user['id']}/reset-password", json={"new_password": "NewPassword!99", "must_change_password": True}, headers=auth(admin_token))
    assert res.status_code == 204
    assert client.post("/api/auth/login", json={"username": "roleuser", "password": "Password!1234"}).status_code == 401
    tok = login(client, "roleuser", "NewPassword!99")
    assert client.get("/api/auth/me", headers=auth(tok)).json()["must_change_password"] is True
    res = client.post("/api/auth/change-password", json={"current_password": "NewPassword!99", "new_password": "FinalPassword!7"}, headers=auth(tok))
    assert res.status_code == 204

    logs = client.get("/api/audit-logs", headers=auth(admin_token)).json()
    actions = [e["action"] for e in logs["items"]]
    for expected in ("USER_CREATED", "ROLE_CHANGED", "USER_UPDATED", "PASSWORD_RESET", "LOGIN", "LOGIN_FAILED"):
        assert expected in actions
    # No secrets in the audit log
    assert "password" not in str(logs).lower().replace("password_reset", "")


def test_admin_cannot_disable_self(client, admin_token):
    me = client.get("/api/auth/me", headers=auth(admin_token)).json()
    res = client.patch(f"/api/users/{me['id']}/status", json={"is_active": False}, headers=auth(admin_token))
    assert res.status_code == 400 and res.json()["detail"] == "cannot_disable_self"


def test_investigator_directory(client, admin_token, investigator, viewer):
    res = client.get("/api/investigators", headers=auth(investigator["token"]))
    assert res.status_code == 200
    names = [p["full_name"] for p in res.json()]
    assert "الرائد علي حسن" in names and "مشاهد" not in names  # USER role is not an investigator
    assert client.get("/api/investigators", headers=auth(viewer["token"])).status_code == 403


def test_bootstrap_admin_must_change_password(client):
    tok = login(client, ADMIN["username"], ADMIN["password"])
    assert client.get("/api/auth/me", headers=auth(tok)).json()["must_change_password"] is True
