import ssl
from unittest.mock import Mock
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import User
from app.api import auth as auth_api
from app.services.ldap_auth import authenticate_directory, DirectoryUnavailable
from tests.conftest import ADMIN, auth, create_user


def directory_settings(**kwargs):
    return Settings(_env_file=None, auth_mode='ldap', ldap_host='dc.example.org',
                    ldap_domain='example.org', **kwargs)


def test_configuration_requires_directory_and_secure_transport():
    assert Settings(_env_file=None).auth_mode == 'local'
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_mode='ldap', ldap_host='', ldap_domain='')
    with pytest.raises(ValidationError):
        directory_settings(ldap_tls_mode='plain')
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auth_mode='unexpected')


@pytest.mark.parametrize('tls_mode', ['ldaps', 'starttls'])
def test_secure_direct_bind_and_cleanup(monkeypatch, tls_mode):
    import ldap3
    connection=Mock(closed=False, result={'result':0})
    connection.bind.return_value=True
    connection.start_tls.return_value=True
    factory=Mock(return_value=connection)
    server=Mock()
    monkeypatch.setattr(ldap3,'Connection',factory)
    monkeypatch.setattr(ldap3,'Server',server)
    assert authenticate_directory('alice','directory-secret',directory_settings(ldap_tls_mode=tls_mode))
    assert factory.call_args.kwargs['user'] == 'alice@example.org'
    assert factory.call_args.kwargs['auto_referrals'] is False
    assert factory.call_args.kwargs['read_only'] is True
    assert server.call_args.kwargs['tls'].validate == ssl.CERT_REQUIRED
    assert server.call_args.kwargs['use_ssl'] == (tls_mode == 'ldaps')
    assert connection.method_calls == ([('open',(),{}),('start_tls',(),{}),('bind',(),{}),('unbind',(),{})] if tls_mode == 'starttls' else [('open',(),{}),('bind',(),{}),('unbind',(),{})])


def test_tls_failure_never_sends_password_bind(monkeypatch):
    import ldap3
    connection=Mock(closed=False)
    connection.start_tls.return_value=False
    monkeypatch.setattr(ldap3,'Connection',Mock(return_value=connection))
    with pytest.raises(DirectoryUnavailable):
        authenticate_directory('alice','secret',directory_settings(ldap_tls_mode='starttls'))
    connection.bind.assert_not_called()
    connection.unbind.assert_called_once()


def test_bad_credentials_and_server_failure_are_distinct(monkeypatch):
    import ldap3
    connection=Mock(closed=False,result={'result':49})
    connection.bind.return_value=False
    factory=Mock(return_value=connection)
    monkeypatch.setattr(ldap3,'Connection',factory)
    assert not authenticate_directory('alice','bad',directory_settings())
    connection.result={'result':52}
    with pytest.raises(DirectoryUnavailable):
        authenticate_directory('alice','bad',directory_settings())
    factory.reset_mock()
    assert not authenticate_directory('alice','',directory_settings())
    assert not authenticate_directory('alice@other.org','bad',directory_settings())
    factory.assert_not_called()


def test_ldap_login_preserves_roles_hash_and_local_flags(client, admin_token, monkeypatch):
    create_user(client,admin_token,'alice',['USER'])
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='alice'))
        user.must_change_password=True
        before=user.password_hash
        db.commit()
    monkeypatch.setattr(get_settings(),'auth_mode','ldap')
    verify=Mock(return_value=True)
    monkeypatch.setattr(auth_api,'authenticate_directory',verify)
    response=client.post('/api/auth/login',json={'username':'Alice','password':'AD-password'})
    assert response.status_code==200, response.text
    token=response.json()['access_token']
    me=client.get('/api/auth/me',headers=auth(token)).json()
    assert me['roles']==['USER'] and me['auth_mode']=='ldap' and not me['must_change_password']
    assert client.get('/api/users',headers=auth(token)).status_code==403
    assert client.post('/api/auth/change-password',headers=auth(token),json={'current_password':'AD-password','new_password':'new-password-123'}).status_code==409
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='alice'))
        assert user.password_hash==before and user.must_change_password
    assert client.get('/api/auth/me',headers=auth(admin_token)).status_code==401
    monkeypatch.setattr(get_settings(),'auth_mode','local')
    assert client.get('/api/auth/me',headers=auth(token)).status_code==401
    assert client.post('/api/auth/login',json={'username':'alice','password':'Password!1234'}).status_code==200


def test_directory_denial_and_outage_do_not_fallback_to_local(client,monkeypatch):
    monkeypatch.setattr(get_settings(),'auth_mode','ldap')
    verify=Mock(return_value=False)
    monkeypatch.setattr(auth_api,'authenticate_directory',verify)
    assert client.post('/api/auth/login',json=ADMIN).status_code==401
    verify.side_effect=DirectoryUnavailable()
    assert client.post('/api/auth/login',json=ADMIN).status_code==503
    verify.reset_mock()
    assert client.post('/api/auth/login',json={'username':'unprovisioned','password':'secret'}).status_code==401
    verify.assert_not_called()


def test_locally_disabled_user_cannot_use_ldap(client,admin_token,monkeypatch):
    user=create_user(client,admin_token,'disabledldap',['USER'])
    client.patch(f"/api/users/{user['id']}/status",json={'is_active':False},headers=auth(admin_token))
    monkeypatch.setattr(get_settings(),'auth_mode','ldap')
    verify=Mock(return_value=True)
    monkeypatch.setattr(auth_api,'authenticate_directory',verify)
    assert client.post('/api/auth/login',json={'username':'disabledldap','password':'secret'}).status_code==403
    verify.assert_not_called()
