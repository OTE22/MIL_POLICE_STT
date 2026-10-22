# Optional Active Directory authentication

Default: `CENTRAL_AUTH_MODE=local`. Existing application passwords, password changes,
roles, and login screen continue to work. No database migration is required.

To use Active Directory, configure the root `.env`:

```dotenv
CENTRAL_AUTH_MODE=ldap
CENTRAL_LDAP_HOST=dc01.corp.example.org
CENTRAL_LDAP_DOMAIN=corp.example.org
CENTRAL_LDAP_TLS_MODE=ldaps
CENTRAL_LDAP_PORT=636
CENTRAL_LDAP_CA_CERT_FILE=/secrets/ad-ca.pem
CENTRAL_LDAP_TIMEOUT_SECONDS=5
```

These are examples, not real directory settings. Place the issuing CA chain (PEM) in
`secrets/ad-ca.pem`; the existing Compose secrets-directory mount exposes it at the
container path. Publicly trusted certificates can use an empty CA setting. Hostname
and certificate validation are mandatory. Use the DC's certificate DNS name.
StartTLS is also supported: set `CENTRAL_LDAP_TLS_MODE=starttls` and port `389`.
Plaintext LDAP is not supported. The backend needs DNS/network access to that server.

## Account setup and rollout

1. Before enabling LDAP, create application accounts with usernames matching each
   person's AD UPN prefix. For `alice@corp.example.org`, use `alice`. This integration
   uses the UPN suffix, which may differ from the AD DNS domain or NetBIOS domain.
   Login accepts the short application username (letters, digits, dot, underscore,
   hyphen); it does not accept `DOMAIN\alice` or a full UPN.
2. Assign roles, profiles and investigation access normally. Directory users are NOT
   auto-created and directory group membership does not grant application roles.
   Make sure an application administrator has a matching directory account before
   switching modes. Existing privileged username mappings must be reviewed explicitly.
3. Configure the directory certificate and settings, rebuild the backend to install
   the LDAP dependency, and recreate the backend so Compose reloads `.env`:
   `docker compose up -d --build backend`. A plain container restart does not reload
   changed Compose environment values. Refresh nginx if its upstream address changes.
4. Verify successful/failed login, disabled/locked/expired directory accounts,
   disabled application accounts, and directory outage handling in your environment.

LDAP mode binds directly to AD as `username@domain` with the submitted password over
verified TLS. No service account, search permission or stored AD password is needed.
Referrals are disabled. Invalid credentials never fall back to local verification.
Directory failures return a generic service-unavailable message. Application-disabled
accounts remain blocked. Login audits never include passwords or AD error details.

The same login page and JWT sessions are used. Changing authentication modes rejects
tokens issued under the other mode. Directory account changes are checked at the next
login, not on every API request; previously issued sessions can last until their token
expires. Set `CENTRAL_ACCESS_TOKEN_EXPIRE_MINUTES` to your organisation's session policy.
Disabling an application account blocks its existing sessions immediately.

In LDAP mode, self-service password changes are redirected to the institution's
directory process. Local password hashes and `must_change_password` flags are retained
but are not used for LDAP authentication. Administrative password reset operations
still affect ONLY the dormant local password, never AD; do not use them to reset AD.

Rollback: set `CENTRAL_AUTH_MODE=local` and recreate the backend. The original local
passwords and password-change requirements resume. There is no automatic fallback or
special local-admin bypass while LDAP mode is enabled.

This implements Active Directory direct UPN binding, not generic LDAP DN lookup,
automatic provisioning, group-to-role synchronisation, Windows SSO or directory MFA.
Real AD integration must be acceptance-tested with your DC and certificate chain.
