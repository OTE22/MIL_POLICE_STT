/* اختيار الشخص — the one place a speaker is bound to a person.
 *
 * It replaces a free-text box, three look-alike chips and two buttons that both established
 * identity through different doors. Selecting someone here IS identifying them; there is no
 * second step and no other way.
 *
 * Five choices, and each says what it will do:
 *
 *   مشاركو الجلسة        subjects on this session -> linked immediately
 *   مُحقّقو الجلسة        investigators running it -> linked immediately
 *   البحث عن شخص مسجل    the canonical registry -> recorded here, then linked
 *   إضافة شخص جديد       the person form -> created, then linked
 *   تسمية مؤقتة          a label only, and only while nobody has been identified
 *
 * Investigators are people, not staff: they speak in the interviews they run, so they are rows
 * in the same registry and can carry a voice print. One whose profile cannot yield a
 * الرقم المرجعي is listed DISABLED rather than hidden, so the gap is visible and fixable.
 *
 * Every link resolves through الرقم المرجعي, never through the displayed name: two people in one
 * session may share a rank and a name, so a row carries its person, not its string.
 */

import { useEffect, useMemo, useState } from "react";

import { ApiError, http, qs } from "@/api/client";
import type { PersonSearchResult, SessionPerson, Speaker } from "@/api/types";
import { Modal, useToast } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { T, errorMessage } from "@/lib/i18n";
import { linkToRegistryPerson, linkToSessionParticipant, setTemporaryLabel } from "@/lib/link-speaker";
import { isPlaceholderName, normalizeReference } from "@/lib/person-reference";

/** How a person is written, everywhere: the CANONICAL name and nothing else.
 *
 * The rank is deliberately NOT folded in. It is a role that changes with promotion while the
 * person does not, `person_identities` has no column for it, and بصمات الأصوات therefore cannot
 * show one - so concatenating it here is what made the same human read as "MAJOR ALI" in the
 * picker and "ALI" in the voice registry. It is rendered beside the name instead, like the
 * الرقم المرجعي already is.
 */
function label(p: { person_name: string }): string {
  return p.person_name.trim() || T.unnamed;
}

/** The one row. Both sections use it, so a person cannot be written two ways again. */
function PersonRow({
  person,
  busy,
  testId,
  onPick,
}: {
  person: SessionPerson;
  busy: boolean;
  testId: string;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      className="person-row"
      disabled={busy || !person.selectable}
      title={person.selectable ? undefined : T.pickPersonIncomplete}
      data-reference={person.reference_number ?? ""}
      data-testid={testId}
      onClick={onPick}
    >
      <strong>{label(person)}</strong>
      {/* Decoration, beside the name - never part of it. */}
      {person.rank && <span className="muted small">{person.rank}</span>}
      <span className="ltr muted">
        {person.reference_number ?? T.pickPersonIncomplete}
      </span>
    </button>
  );
}

export function SpeakerPicker({
  sessionId,
  speaker,
  onLinked,
  onAddNew,
  disabled,
}: {
  sessionId: string;
  speaker: Speaker;
  /** Re-read from the server: the backend may converge a merged reference onto its survivor,
      so what was sent is not always what was stored. */
  onLinked: () => void;
  onAddNew: () => void;
  disabled: boolean;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const mayIdentify = can("voice.identify");

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<PersonSearchResult[] | null>(null);
  const [people, setPeople] = useState<SessionPerson[]>([]);
  const [temporary, setTemporary] = useState("");

  /* Everyone on this session, from the one endpoint that knows how to name them. Fetched when
     the modal opens so a person added or renamed elsewhere is never stale here. */
  useEffect(() => {
    if (!open) return;
    void http
      .get<SessionPerson[]>(`/investigations/${sessionId}/people`)
      .then(setPeople)
      .catch(() => setPeople([]));
  }, [open, sessionId]);

  const subjects = useMemo(() => people.filter((p) => p.source === "SUBJECT"), [people]);
  const investigators = useMemo(
    () => people.filter((p) => p.source === "INVESTIGATOR"),
    [people],
  );

  useEffect(() => {
    if (!open || !mayIdentify) return;
    const handle = setTimeout(() => {
      void http
        .get<PersonSearchResult[]>(`/voice-enrollments/people${qs({ q })}`)
        .then(setResults)
        .catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(handle);
  }, [q, open, mayIdentify]);

  /* A person is offered ONCE, across every section. Matching is by canonical reference and
     never by name - two people who share a name are two people and both must stay pickable.
     De-duplicating against subjects alone is what listed an investigator twice, under two
     different names, in the same modal. */
  const registryResults = useMemo(() => {
    const here = new Set(
      people.map((p) => normalizeReference(p.reference_number)).filter(Boolean),
    );
    return (results ?? []).filter((r) => !here.has(normalizeReference(r.person_reference)));
  }, [results, people]);

  /* Linking is identical whoever they are - that is the point of one shape. The rank is
     shown on the card but never sent as part of the person's name. */
  const pick = (person: SessionPerson) =>
    void run(() =>
      linkToSessionParticipant(sessionId, speaker.id, {
        canonicalName: person.person_name,
        reference: person.reference_number!,
        // The STORED label is the canonical name too. If it carried the rank, this picker's own
        // trigger button would read "MAJOR ALI" while its rows read "ALI", and the speaker card
        // would disagree with بصمات الأصوات for the same person.
        displayName: person.person_name,
      }),
    );

  const run = async (action: () => Promise<Speaker>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      toast.success(T.speakerSaved);
      setOpen(false);
      onLinked();
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  const current = speaker.display_name || T.unnamed;

  return (
    <>
      <button
        type="button"
        className="input picker-trigger"
        onClick={() => setOpen(true)}
        disabled={disabled}
        data-testid="speaker-person-picker"
      >
        <span className={speaker.display_name ? "" : "muted"}>{current}</span>
        <span className="muted small">{T.pickPerson}</span>
      </button>

      {open && (
        <Modal title={T.pickPerson} onClose={() => (busy ? undefined : setOpen(false))}>
          {error && <div className="mb-16"><div className="alert danger">{error}</div></div>}

          <div className="picker-section">
            <h4>{T.pickParticipants}</h4>
            {subjects.length === 0 ? (
              <p className="muted small">{T.pickNoParticipants}</p>
            ) : (
              <div className="person-list">
                {subjects.map((p) => (
                  <PersonRow
                    key={p.participant_key ?? p.reference_number ?? p.person_name}
                    person={p}
                    busy={busy}
                    testId="pick-participant"
                    onPick={() => pick(p)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* The people running the session. They speak in the recording, so they are people
              in the registry like anyone else - assignment registers them under
              MIL-<BRANCH>-<serial>, and from there they are identified and voice-enrolled by
              exactly the same machinery as a subject. A profile that predates the requirement
              has no reference yet; it is shown and disabled rather than hidden, so the gap is
              visible and fixable instead of silently absent. */}
          {investigators.length > 0 && (
            <div className="picker-section">
              <h4>{T.pickInvestigators}</h4>
              <p className="muted small">{T.pickInvestigatorHint}</p>
              <div className="person-list mt-8">
                {investigators.map((inv) => (
                  <PersonRow
                    key={inv.reference_number ?? inv.person_name}
                    person={inv}
                    busy={busy}
                    testId="pick-investigator"
                    onPick={() => pick(inv)}
                  />
                ))}
              </div>
            </div>
          )}

          {mayIdentify && (
            <div className="picker-section">
              <h4>{T.pickSearchRegistry}</h4>
              <input
                className="input"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={T.pickSearchPlaceholder}
                disabled={busy}
                data-testid="pick-search"
              />
              {registryResults.length > 0 && (
                <div className="person-list mt-8">
                  {registryResults.map((r) => (
                    <button
                      key={r.identity_id}
                      type="button"
                      className="person-row"
                      disabled={busy}
                      data-reference={r.person_reference}
                      data-testid="pick-registry"
                      onClick={() =>
                        void run(() =>
                          linkToRegistryPerson(sessionId, speaker.id, {
                            canonicalName: r.person_name,
                            reference: r.person_reference,
                          }),
                        )
                      }
                    >
                      {/* Without this the row reads "CIV-00000019  CIV-00000019". */}
                      <strong>
                        {isPlaceholderName(r.person_name, r.person_reference)
                          ? T.unnamed
                          : r.person_name}
                      </strong>
                      <span className="ltr muted">{r.person_reference}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {mayIdentify && (
            <div className="picker-section">
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy}
                data-testid="pick-add-new"
                onClick={() => {
                  setOpen(false);
                  onAddNew();
                }}
              >
                {T.pickAddNew}
              </button>
            </div>
          )}

          {/* Only while nobody has been identified. Once a speaker IS someone, a working label
              would be a way to quietly disagree with the registry. */}
          {!speaker.identity_id && (
            <div className="picker-section">
              <h4>{T.pickTemporaryLabel}</h4>
              <p className="muted small">{T.pickTemporaryHint}</p>
              <div className="flex gap mt-8">
                <input
                  className="input"
                  value={temporary}
                  onChange={(e) => setTemporary(e.target.value)}
                  maxLength={200}
                  disabled={busy}
                  data-testid="pick-temporary-input"
                />
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={busy || !temporary.trim()}
                  data-testid="pick-temporary-save"
                  onClick={() => void run(() => setTemporaryLabel(sessionId, speaker.id, temporary))}
                >
                  {T.save}
                </button>
              </div>
            </div>
          )}
        </Modal>
      )}
    </>
  );
}
