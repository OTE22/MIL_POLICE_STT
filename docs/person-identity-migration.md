# Person identities without reference numbers

The person reference number (الرقم المرجعي) has been retired. The application no longer
generates `MIL-*`, `CIV-*`, or `TMP-*` numbers, accepts manual reference overrides, or
displays a reference field. Military service numbers and identity documents remain useful
person details and are retained.

Each person has an internal UUID. Participants, investigators, speakers, and voiceprints
link to that UUID. It is selected through the person picker, never typed by an operator.
Saving or reordering participants preserves their existing identity. Two people with the
same name remain separate; names and family registration numbers never merge people.

Military service numbers are scoped to their security branch and stored as external
identifiers. Entering the same number in the same branch reuses the person; a conflicting
name is refused. A civilian can be selected from the existing-person search using their
UUID. Documentary identifier conflicts still require the operator to select the correct
person rather than silently merge records.

## API changes

- `SubjectIn` and subject responses carry `identity_id` alongside the session-local
  `participant_key`. A participant keeps its identity during editing.
- Speaker PATCH accepts `identity_id` only with `voice.identify`. The person must already
  participate in the accessible session, either as a subject or investigator.
- Voice enrollment uses the speaker's stored identity and still requires recorded consent.
- `reference_number`, `person_reference`, `identity_reference`, and enrollment reference
  snapshots are removed from responses. Requests containing retired reference fields are
  rejected; reload older clients after deployment.
- Renaming a person preserves their UUID and enrollment-time name snapshots. Consolidation
  remains an explicit privileged operation; old UUIDs resolve through merge aliases.

## Deployment

Deploy the backend and frontend together. Alembic revision `d8a4f2c91e60` preserves UUID
links, recovers legacy rows still carrying only a reference, preserves military identifier
aliases, and removes reference columns, sequences, and the override permission. Conflicting
legacy military identifiers abort the migration transaction for review.

Take a database backup before upgrading. The migration cannot reconstruct deleted reference
numbers on downgrade; rollback requires restoring that backup and the previous application.
Historical audit logs and already-issued documents remain unchanged. Retired placeholders
in previously approved report templates render empty; replace those layouts to remove
their old field labels too. New templates must omit the retired placeholders.

The replacement regression tests cover UUID persistence, duplicate names, military-number
scoping, authorization, voice enrollment, merge resolution, and migration of legacy links.
