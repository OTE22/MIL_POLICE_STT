# Deployment verification — 22 October 2026

Deployed backend and frontend to the existing localhost stack. Migration:
`f0a6b4e13d82`. Frontend bundle: `index-CITimwPc.js`.

Verification completed:

- 157 distinct relevant backend tests passed across the regression run and targeted
  reruns, including report generation, schema, drafts, attribution, template management,
  wording assistance, LDAP/local authentication, and the new M53 workflow.
- The initial legacy verification-response test failure was fixed by omitting the new
  PDF result for older Word-only reports. Its targeted rerun passed.
- Browser workflow against a separate test database: normal sign-in/password change,
  edit a form value, save and read it back, confirm review, issue, retrieve PDF, and verify
  archive hashes. The template page loaded, downloaded its blank PDF, and showed no
  console errors or horizontal overflow. Temporary browser-test containers were removed.
- Blank/short/long application-generated specimens: 3/3/4 pages; complete body character
  inventories preserved on every page. Independent Word exports also passed those checks.
  Word's local font substitution means the editable copy is not a pixel-identity claim;
  the server-rendered PDF is the print master.
- Live backend health returned HTTP 200 with database=true. Backend, frontend, agent and
  PostgreSQL container health checks passed; nginx served the new frontend and API.
- Production counts before/after: 1 session, 38 transcript segments, 19 speaker records,
  2 template versions, 2 issued reports. Both existing reports still passed integrity checks.
- Authentication remains in local mode. No real directory-server connection was exercised.

Database backup (ignored from Git):
`storage/backups/before-m53-final-20261022.dump`

SHA-256:
`71183b44169c3ec84d711f0efe2460a1ac6ec0f4d3788cda670ad528aeeb8a3d`

Rollback images retained:
`military-stt/central-backend:before-m53-20261021` and
`military-stt/central-frontend:before-m53-20261021`. The database migration is additive;
the earlier application can ignore the new nullable columns.

The built-in form is selected per report and supports one identified statement-giver.
It reconstructs the supplied scan's ruled structure and fixed wording; it is not an
institution-issued master or a certificate-based signing system. The older uploaded Word
template workflow and issued reports remain available.
