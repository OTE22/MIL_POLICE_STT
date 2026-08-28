/* تحديد الهوية — say who an unknown speaker is.
 *
 * Cohere discovers speakers; this dialog establishes who the human is; enrolment registers
 * their voice. Three connected stages, not three identity systems — so this reuses the
 * EXISTING person workflow rather than inventing a voice-specific one:
 *
 *   اختيار شخص موجود → the canonical registry, so a person entered by another investigator
 *                       is reused instead of duplicated
 *   إضافة شخص جديد   → the very same SubjectFields form used by إنشاء جلسة / إضافة شخص
 *
 * On confirm it calls two existing endpoints: PUT /investigations/{id} to record the person
 * on the session, then PATCH .../speakers/{id} to link the speaker. The backend resolves the
 * canonical identity from الرقم المرجعي; the client never sends an identity_id.
 */

import { useEffect, useMemo, useState } from "react";

import { ApiError, http, qs } from "@/api/client";
import type { PersonSearchResult, Speaker, Subject } from "@/api/types";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Field, Loading, Modal, useToast } from "@/components/ui";
import { SubjectFields, emptySubject } from "@/components/subjects/SubjectFields";
import { linkToRegistryPerson } from "@/lib/link-speaker";
import { normalizeReference } from "@/lib/person-reference";

type Mode = "existing" | "new";

/** The canonical identity key, as the backend resolves it: الرقم المرجعي. */
function referenceOf(subject: Subject): string {
  return (subject.reference_number ?? "").trim();
}

export function IdentifySpeakerDialog({
  sessionId,
  speaker,
  onClose,
  onIdentified,
}: {
  sessionId: string;
  speaker: Speaker;
  onClose: () => void;
  onIdentified: () => void;
}) {
  const toast = useToast();
  const [mode, setMode] = useState<Mode>("existing");
  // Start from the name they just typed: if that person is already known, choosing them
  // is one click. It only seeds the search - selection is still by reference, never name.
  const [q, setQ] = useState(speaker.display_name ?? "");
  const [results, setResults] = useState<PersonSearchResult[] | null>(null);
  const [picked, setPicked] = useState<PersonSearchResult | null>(null);
  /* إضافة شخص جديد starts EMPTY. It used to be seeded from the speaker's existing
     identity_name and reference_number, which only ever had a value when the speaker was
     ALREADY identified - so the "create someone new" tab opened holding someone who already
     exists, and then warned that they exist. A form cannot both create a person and describe
     a different one.

     Nothing is seeded from display_name either: that label may carry a rank
     ("الرائد علي حسن"), and seeding from it wrote the rank into subjects.subject_name and from
     there into person_identities.person_name. Ranks are structured data or they are nothing,
     and guessing at prefixes would mangle real names.

     Typing a name that already exists still raises the "هذا الشخص موجود مسبقاً" banner with
     استخدام الشخص الموجود - detection belongs there, not in a prefill. */
  const [subject, setSubject] = useState<Subject>(emptySubject);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== "existing") return;
    const h = setTimeout(() => {
      void http
        .get<PersonSearchResult[]>(`/voice-enrollments/people${qs({ q })}`)
        .then(setResults)
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(h);
  }, [q, mode]);

  // Typing a reference that already exists is not an error - it is the whole point of the
  // registry. Surface it so the investigator reuses the person instead of colliding with them.
  const existingMatch = useMemo(() => {
    if (mode !== "new") return null;
    // normalizeReference, not toUpperCase: the backend folds NFKC and Arabic-Indic digits
    // too, so "LBN-ZAHLE-١١" is the same key to it. Ad-hoc folding here made the client miss
    // collisions the server would then refuse.
    const ref = normalizeReference(referenceOf(subject));
    if (!ref) return null;
    return (results ?? []).find((r) => normalizeReference(r.person_reference) === ref) ?? null;
  }, [mode, subject, results]);

  useEffect(() => {
    if (mode !== "new") return;
    const ref = referenceOf(subject);
    if (!ref) return;
    const h = setTimeout(() => {
      void http
        .get<PersonSearchResult[]>(`/voice-enrollments/people${qs({ q: ref })}`)
        .then(setResults)
        .catch(() => undefined);
    }, 300);
    return () => clearTimeout(h);
  }, [mode, subject]);

  // A new person needs a name, and a reference they will actually END UP with - either one
  // the identifiers derive, or one the backend will issue. Demanding a typed reference was
  // what made a new civilian impossible to identify: theirs does not exist until save.
  const willBeIssued = subject.person_type === "CIVILIAN" || subject.person_type === "UNKNOWN";
  const canSubmit =
    mode === "existing"
      ? picked !== null
      : Boolean((subject.subject_name ?? "").trim()) && (willBeIssued || Boolean(referenceOf(subject)));

  const submit = async () => {
    setBusy(true);
    setError(null);
    const name = mode === "existing" ? picked!.person_name : (subject.subject_name ?? "").trim();
    const reference = mode === "existing" ? picked!.person_reference : referenceOf(subject);
    try {
      // Record the person on the session and link the speaker. Both steps, and the retry
      // safety around them, live in lib/link-speaker so the picker runs the same code.
      await linkToRegistryPerson(sessionId, speaker.id, {
        canonicalName: name,
        reference,
        // mode "new" carries the whole form: its identifiers are what the backend derives or
        // issues the reference from.
        subject: mode === "new" ? subject : undefined,
      });

      toast.success(T.identifySaved);
      onIdentified();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={T.identifySpeaker}
      onClose={onClose}
      footer={
        <>
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || !canSubmit}
            onClick={() => void submit()}
            data-testid="identify-submit"
          >
            {T.save}
          </button>
          <button className="btn" type="button" onClick={onClose}>
            {T.cancel}
          </button>
        </>
      }
    >
      {/* Which speaker this is about. The canonical-name field no longer starts from this
          label, so without showing it here the operator loses the only clue they had. */}
      <div className="muted small mb-8" data-testid="identify-speaker-context">
        <span className="ltr">{speaker.speaker_label}</span>
        {speaker.display_name ? ` — ${T.identifyLabelledAs}: ${speaker.display_name}` : ""}
      </div>
      <div className="audit-filters" role="tablist">
        <button
          type="button"
          className={`chip ${mode === "existing" ? "active" : ""}`}
          onClick={() => setMode("existing")}
          data-testid="identify-existing"
        >
          {T.identifyChooseExisting}
        </button>
        <button
          type="button"
          className={`chip ${mode === "new" ? "active" : ""}`}
          onClick={() => setMode("new")}
          data-testid="identify-new"
        >
          {T.identifyAddNew}
        </button>
      </div>

      {error && (
        <div className="mb-16">
          <Alert kind="danger">{error}</Alert>
        </div>
      )}

      {mode === "existing" ? (
        <>
          <Field label={T.search}>
            <input
              className="input"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={T.identifySearchPlaceholder}
              data-testid="identify-search"
            />
          </Field>
          {!results ? (
            <Loading />
          ) : results.length === 0 ? (
            <div className="muted center">{T.identifyNoResults}</div>
          ) : (
            <div className="person-list" data-testid="identify-results">
              {results.map((r) => (
                <button
                  key={r.identity_id}
                  type="button"
                  className={`person-row ${picked?.identity_id === r.identity_id ? "selected" : ""}`}
                  onClick={() => setPicked(r)}
                  data-testid="identify-person"
                  data-reference={r.person_reference}
                >
                  <strong>{r.person_name}</strong>
                  <span className="ltr muted">{r.person_reference}</span>
                  {/* Totals cover only sessions this user may see. */}
                  <span className="muted small">
                    {r.accessible_print_count} {T.voicePrintCount}
                  </span>
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          {existingMatch && (
            <div className="mb-16">
              <Alert kind="info">
                <div>{T.identifyPersonExists}</div>
                <div className="mt-8">
                  <strong>{existingMatch.person_name}</strong>{" "}
                  <span className="ltr muted">{existingMatch.person_reference}</span>
                </div>
                <button
                  className="btn btn-sm mt-8"
                  type="button"
                  onClick={() => {
                    setPicked(existingMatch);
                    setMode("existing");
                  }}
                  data-testid="identify-use-existing"
                >
                  {T.identifyUseExisting}
                </button>
              </Alert>
            </div>
          )}
          {/* The same form as إضافة شخص - one person model, one set of rules. */}
          <SubjectFields
            sessionId={sessionId}
            subject={subject}
            index={0}
            canRemove={false}
            canUploadDocuments={false}
            onChange={setSubject}
            onRemove={() => undefined}
          />
        </>
      )}
    </Modal>
  );
}
