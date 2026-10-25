# Investigation reporting: HTML/PDF

The HTML editor is the sole report editor. Word/M53 generators, templates and their report records are retired; old creation APIs return HTTP 410. The owner authorized deletion of legacy data. Database backups and rollback images remain available for recovery.

1. Create the investigation session and assign exactly one lead investigator. Enter participants once and select their canonical identities.
2. Record and synchronize original audio. Wait for all processing jobs; review transcription, attribution and speaker identities. Machine text stays intact beneath human corrections.
3. Open the report and add statements or notes. Selecting a session participant imports their known facts and attributed answers. A source refresh rebuilds the import catalogue without replacing saved wording.
4. Save and inspect the server preview. Explicit overrides remain separate from imported person facts. If upstream evidence or identities change, review the displayed changes and confirm the saved wording remains appropriate.
5. Save the content review. A user with `reports.finalize` issues the official HTML/PDF. Draft exports display **مسودة**. Official PDF uses the exact issued HTML, pinned Chromium and bundled Inter / IBM Plex Sans Arabic fonts.
6. Download or verify issued versions from the archive. Files, source snapshots, hashes, issuer and time are retained. A correction requires a reason and creates a successor; it never changes an issued artifact.
7. Use explicit investigation workflow actions to request review, approve, close, archive or reopen. Closure requires current issued content, original audio and no active jobs. Processing completion alone does not close the investigation.

Session, segment and report edits reject stale versions. Optional fields support explicit clearing. Participant removal is explicit and retains the row and evidence; scan removal retains a downloadable historical version.

See [field lineage and duplication matrix](investigation-workflow-field-lineage.md) for canonical owners, database fields, API paths and downstream consumers. See [validation and deployment](investigation-workflow-validation.md) for the verification record.
