"""Read-only AD authentication by direct UPN bind. Never stores directory passwords."""
import re
import ssl
from app.config import Settings


class DirectoryUnavailable(Exception):
    pass


def authenticate_directory(username: str, password: str, settings: Settings) -> bool:
    # No anonymous binds, domain overrides, DN interpolation or credential referrals.
    if not password or not re.fullmatch(r'[A-Za-z0-9._-]+', username):
        return False
    from ldap3 import Connection, Server, Tls, SIMPLE, NONE
    from ldap3.core.exceptions import LDAPException
    connection = None
    try:
        tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=settings.ldap_ca_cert_file or None,
                  version=ssl.PROTOCOL_TLS_CLIENT, valid_names=[settings.ldap_host])
        server = Server(settings.ldap_host, port=settings.ldap_port,
                        use_ssl=settings.ldap_tls_mode == 'ldaps', tls=tls,
                        connect_timeout=settings.ldap_timeout_seconds, get_info=NONE)
        connection = Connection(server, user=f'{username}@{settings.ldap_domain}', password=password,
                                authentication=SIMPLE, auto_bind=False, auto_referrals=False,
                                read_only=True, raise_exceptions=False,
                                receive_timeout=settings.ldap_timeout_seconds)
        connection.open()
        if connection.closed:
            raise DirectoryUnavailable()
        if settings.ldap_tls_mode == 'starttls' and not connection.start_tls():
            raise DirectoryUnavailable()
        if connection.bind():
            return True
        if (connection.result or {}).get('result') == 49:
            return False  # Invalid, expired, locked or disabled AD credentials.
        raise DirectoryUnavailable()
    except (LDAPException, OSError, ValueError):
        # Never expose LDAP diagnostics or credentials to the client or logs.
        raise DirectoryUnavailable() from None
    finally:
        if connection is not None:
            try:
                connection.unbind()
            except (LDAPException, OSError):
                pass
