# Voice review and speaker presentation

Updated 2026-09-20. The review panel, grouped speaker presentation and manual same-person
confirmation workflow are deployed in the local application.

The manual **فحص البصمات الصوتية** remains read-only. The result now explains each
finding, offers source playback and pair comparison, and separates explicit human
review actions from the check itself. Similarity is a score, not identity probability.

- Comparisons require the same model, dimension, revision and provider, following the
  matcher compatibility policy. Missing metadata only compares with matching missing
  metadata. Incompatible groups are explained separately from inconsistent samples.
- **استماع ومقارنة** loads authenticated source audio on demand. Selecting a segment
  seeks to its start and pauses at its end; playing one sample pauses the other.
  Source resolution requires transcript permission and access to the investigation.
  It follows the source speaker's recording and the most recent transcript preceding
  enrollment, never the latest unrelated recording. Legacy samples without a known
  recording report unavailable. These are source transcript segments, not a claim to
  reproduce the exact concatenated audio used by the encoder.
- Operators with `voice.enroll` may add a note, flag a print, resolve a review, or
  deactivate a print. Each requires a reason and records the user, time and print ID.
  Existing enrollment notes remain unchanged. A timestamp/identity check rejects
  stale decisions. Deactivation invalidates pending suggestions based on that print;
  confirmed identities remain intact. Existing registry controls allow reactivation.
- Review events use the append-only audit log (`VOICE_PRINT_REVIEWED`), with a scoped
  history endpoint returning only review fields. The panel shows the latest 100 actions,
  including reviews of subsequently deleted prints. Flags persist across check runs.
  No migration is needed for these review events.

## Confirming the same person within or across groups

Select two or more prints (individually, by computed group, or using select all), compare
their source audio, and enter a reason under **تأكيد وحدة الهوية**. The selected prints
may be in one computed component, different components, or incompatible model groups.
The human declaration is specifically that those samples belong to the displayed person;
it does not establish a numerical comparison for incompatible embeddings.

The result shows a separate **نفس الشخص — مؤكّد يدوياً** set with the reviewer, timestamp,
reason and selected sample details. Group labels shown in those details come from the
current check; the persisted decision references stable print IDs, not component numbers.
It preserves the original cosine scores,
components, vectors and matching behavior. This is not a merge of two person records.
Up to 100 samples may be selected in one decision, and identical active decisions are
rejected to avoid accidental repeat submissions.

Confirmations store exact print IDs and reviewed update timestamps in append-only audit
events. Adding a new print does not extend an existing confirmation. Editing, reviewing,
deactivating, deleting or moving an included print makes the confirmation stale, requiring
a fresh human review. Changing numerical thresholds alone does not invalidate a human
decision. **إعادة فتح المراجعة** records a new event and reason while retaining the original
decision. Both confirmation and reopening require `voice.enroll`.

`tests/test_voice_identity_confirmation.py` verifies these guarantees. The feature uses
the existing audit-log schema and requires no new database migration.

### Operator steps

1. Run **فحص البصمات الصوتية** for the person.
2. Tick **تحديد للتأكيد** on individual samples, or use **تحديد المجموعة** /
   **تحديد جميع العينات**. Selection is allowed inside or across computed groups.
3. With exactly two selected samples, use **مقارنة العينتين المحددتين** for A/B playback.
   For larger selections, inspect the required pairs through **استماع ومقارنة**.
4. Under **تأكيد وحدة الهوية**, check the listed samples, enter a reason, and press
   **تأكيد أن العينات للشخص نفسه**. The button remains disabled without a reason.
5. Review the saved **مجموعة تأكيد يدوي**. To withdraw that decision, use
   **إعادة فتح المراجعة**, enter a reason and press **تأكيد إعادة الفتح**.

**نتيجة المقارنة الآلية** can still say **تحتاج مراجعة** after a human confirmation:
the automatic result and human decision answer different questions. A confirmation can
cover only some samples. No transitive confirmation is inferred between overlapping sets.

### API and persistence

| Endpoint (under `/api`) | Permission and behavior |
|---|---|
| `POST /voice-enrollments/people/{identity_id}/biometric-check` | `voice.identify`; read-only numerical result plus `identity_confirmations` |
| `GET /voice-enrollments/{enrollment_id}/source` | `voice.identify`, `transcripts.read`, source-session access; recording/transcript IDs and segment times |
| `GET /recordings/{recording_id}/audio` | Existing authenticated audio route; `transcripts.read` and source-session access |
| `GET /voice-enrollments/people/{identity_id}/reviews` | `voice.identify`; latest 100 per-print review events |
| `POST /voice-enrollments/{enrollment_id}/reviews` | `voice.enroll`; `action`, `reason`, `identity_id`, `expected_updated_at` |
| `POST /voice-enrollments/people/{identity_id}/identity-confirmations` | `voice.enroll`; reason plus 2–100 distinct print IDs and their reviewed timestamps |
| `POST /voice-enrollments/people/{identity_id}/identity-confirmations/{confirmation_id}/reopen` | `voice.enroll`; reason; original confirmation retained |

A confirmation body uses the timestamps returned by the latest check, for example:

```json
{
  "reason": "تمت مراجعة التسجيلين والتحقق من صاحب الصوت",
  "prints": [
    {"enrollment_id": "00000000-0000-0000-0000-000000000001", "expected_updated_at": "2026-09-20T06:00:00Z"},
    {"enrollment_id": "00000000-0000-0000-0000-000000000002", "expected_updated_at": "2026-09-20T06:00:00Z"}
  ]
}
```

These are illustrative IDs and timestamps. Every selected print must still be active and
owned by the requested person. Stale versions, inactive/missing prints or different owners
return `409 voice_review_stale`; refresh before trying again. Duplicate IDs, a missing or
blank reason, or an out-of-range selection are rejected with 422. Repeating an active
confirmation of the same set returns `409 voice_confirmation_exists`.

`VOICE_IDENTITY_SET_CONFIRMED` stores the reviewed print IDs/timestamps and reason in the
append-only audit log. `VOICE_IDENTITY_SET_REOPENED` references the original event and
records the reopening reason. The computed confirmation status is `ACTIVE`, `STALE` or
`REOPENED`. These events are separate from the latest-100 per-print history and are returned
with the check. Reopening an already reopened decision returns 409; a decision outside the
requested identity returns 404. No vector is included in these payloads or audit records.

## Speaker cards

The **المتحدثون** panel shows one card per canonical person, with expandable voice
observations. Unknown observations stay separate, even when their display names match.
Each observation retains its own identity picker, role, notes and enrollment controls.
Recording filenames identify samples; `SPEAKER_*` labels remain in source details.
Speaking-time totals cover the newest transcript of each recording in the session;
reprocessing a recording does not add its speech twice.

Verification: `tests/test_voice_review.py` covers review persistence, permission gates,
stale decisions, deactivation, model compatibility, source access and session totals.
Frontend checks are in `tests/voice-review.test.ts`, `tests/transcript-speakers.test.ts`
and `tests/voice-review-ui.py`. The browser check uses only synthetic intercepted API
responses against a local frontend preview, including silent test audio; it does not
validate biometric accuracy or modify real investigation records.

## Verification and deployment — 2026-09-20

- 32 targeted backend tests passed across `test_voice_identity_confirmation.py`,
  `test_biometric_check.py` and `test_voice_review.py`.
- The TypeScript/production frontend build passed. Browser checks passed for same-group
  and cross-group selection/confirmation, reopening, reason requirements, A/B audio,
  review history, speaker grouping, desktop/mobile overflow and browser errors.
- Backend and frontend images were rebuilt and deployed; both containers became healthy.
  The proxy configuration passed validation and was reloaded. The public health endpoint
  returned HTTP 200 with `database: true`; the served bundle contained the new controls.
  Both confirmation and reopening routes refused unauthenticated requests with HTTP 401.
- Existing images were retained under `before-identity-confirmation-20260920` tags for
  rollback. The deployment introduced no new database migration.

Browser interactions used synthetic intercepted API responses and silent test audio.
Live verification checked deployment and authentication, without making identity decisions
on real records. Representative real-audio accuracy and live enrollment acceptance remain
separate work; see [the readiness review](voice-enrollment-readiness-review.md).
