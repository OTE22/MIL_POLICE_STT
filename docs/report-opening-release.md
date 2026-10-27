# Official opening release — 27 October 2026

Implemented permanent opening before statements, with fixed wording based on supplied PDF
pages 12/54, a right official heading/subject column, ruled table, canonical session/profile
facts, referral fields and explicit event confirmations. The opening and first statement share
one continuous table. Conclusion pagination and immutable archival services remain in use.

Validation: 33 tests passed across report opening, HTML API, server renderer and integrated
workflow. Coverage includes concurrent saves, field ownership, escaping, draft upgrades,
review, issuance, archive downloads, closure, reopening and immutable issued bytes. An initial
issuance run found the old database format constraint; migration `a27689aebc56` fixes this by
allowing v3 alongside v1/v2. The final rerun passed. Frontend TypeScript/Vite build passed.

Migration rehearsal restored the live database into an isolated test database and compared all
pre-existing column values and row counts before/after: unchanged. Fresh database/storage
backups and rollback images are recorded in
`storage/backups/report-opening-20261027T065942Z/release.json`.

Runtime verification passed: both deployed images healthy, migration at `a27689aebc56`,
localhost assets byte-identical to the build, opening present in the live preview, and the
draft revision token unchanged by verification. This particular session has no issued archives;
historical immutability was exercised by the integration tests. The desktop agent was unchanged.

Visual artifacts: `storage/test-artifacts/report-opening/short.pdf` (one page) and `long.pdf`
(14 pages), with inspected first-page and continuation screenshots. Typography remains bundled
IBM Plex Sans Arabic, not the unidentified scanned typeface. This is a digital reconstruction,
not a pixel-identical copy. A native browser UI check could not run because the computer-use
connection was unavailable; runtime verification used read-only HTTP and rendered PDF inspection.

No real referral facts, oath confirmations, uniforms, testimony, signatures or approvals were
invented or entered into the live session. Missing opening facts explicitly block issuance.
