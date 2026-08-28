/* بصمات الأصوات — the one page that manages voice prints.
 *
 * Organised around PEOPLE, not print rows. Listing one row per print is what let the same
 * person appear three times under three reference numbers, which made the matcher treat his
 * own embeddings as competing identities. Here a person is one row that expands to their
 * prints, and the second tab fills itself as sessions identify new speakers.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, http, qs } from "@/api/client";
import type { EnrollmentCandidate, VoiceEnrollment } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatDuration } from "@/lib/format";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Badge, Field, Loading, Modal, useToast } from "@/components/ui";
import { IconMic, IconRefresh, IconSearch } from "@/components/Icons";
import { EnrollDialog, type EnrollTarget } from "@/components/voice/EnrollDialog";

type Tab = "people" | "pending";

/** One canonical person and the prints that belong to them. */
interface Person {
  identityId: string | null;
  name: string;
  reference: string;
  prints: VoiceEnrollment[];
  active: boolean;
  totalSeconds: number;
}

/** Arabic counted nouns: 1 singular, 2 dual, otherwise the plural. */
function printCount(n: number): string {
  if (n === 1) return T.voicePrintCountOne;
  if (n === 2) return T.voicePrintCountTwo;
  return `${n} ${T.voicePrintCount}`;
}

function groupByPerson(rows: VoiceEnrollment[]): Person[] {
  const map = new Map<string, Person>();
  for (const row of rows) {
    // Group on the canonical identity. A legacy print without one stands alone rather than
    // merging on its reference snapshot, which could join two unrelated people.
    const key = row.identity_id ?? `print:${row.id}`;
    const person = map.get(key) ?? {
      identityId: row.identity_id,
      name: row.person_name,
      reference: row.person_reference,
      prints: [],
      active: false,
      totalSeconds: 0,
    };
    person.prints.push(row);
    person.active = person.active || row.is_active;
    person.totalSeconds += row.sample_seconds ?? 0;
    map.set(key, person);
  }
  return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, "ar"));
}

function EditPersonModal({
  person,
  onClose,
  onSaved,
}: {
  person: Person;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [name, setName] = useState(person.name);
  const [reference, setReference] = useState(person.reference);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Canonical fields belong to the person, so the server applies them to every print in
      // one transaction. Sending them per print could leave one person's prints disagreeing.
      await http.patch(`/voice-enrollments/${person.prints[0].id}`, {
        person_name: name.trim(),
        person_reference: reference.trim(),
        apply_to_person: true,
      });
      toast.success(T.voicePersonUpdated);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={T.voiceEditPerson}
      onClose={onClose}
      footer={
        <>
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy || !name.trim() || !reference.trim()}
            onClick={() => void submit()}
            data-testid="person-edit-submit"
          >
            {T.save}
          </button>
          <button className="btn" type="button" onClick={onClose}>
            {T.cancel}
          </button>
        </>
      }
    >
      {error && (
        <div className="mb-16">
          <Alert kind="danger">{error}</Alert>
        </div>
      )}
      <Field label={T.voicePersonName} required>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required />
      </Field>
      <Field label={T.voicePersonReference} hint={T.voiceConsolidateHint}>
        <input
          className="input"
          dir="ltr"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          maxLength={100}
          data-testid="person-edit-reference"
        />
      </Field>
    </Modal>
  );
}

function PersonRow({ person, manage, onChanged }: { person: Person; manage: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);

  const fail = (err: unknown) =>
    toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);

  const setActive = async (row: VoiceEnrollment, active: boolean) => {
    try {
      await http.patch(`/voice-enrollments/${row.id}`, { is_active: active });
      toast.success(T.voiceUpdated);
      onChanged();
    } catch (err) {
      fail(err);
    }
  };

  const removeOne = async (row: VoiceEnrollment) => {
    try {
      await http.del(`/voice-enrollments/${row.id}`);
      toast.success(T.voiceDeleted);
      onChanged();
    } catch (err) {
      fail(err);
    }
  };

  const removeAll = async () => {
    // Voice prints only. The person, their session records and the speakers all survive, and
    // the confirmation says so - "حذف الشخص" would promise far more than this does.
    if (!window.confirm(`${T.voiceDeletePrints}\n\n${T.voiceDeletePrintsConfirm}`)) return;
    try {
      for (const row of person.prints) {
        await http.del(`/voice-enrollments/${row.id}`);
      }
      toast.success(T.voicePrintsDeleted);
      onChanged();
    } catch (err) {
      fail(err);
    }
  };

  return (
    <div className="person-card" data-testid="person-row" data-reference={person.reference}>
      {editing && <EditPersonModal person={person} onClose={() => setEditing(false)} onSaved={onChanged} />}
      <div className="person-head">
        <div>
          <strong>{person.name}</strong>
          <span className="ltr muted" style={{ marginInlineStart: 8 }}>{person.reference}</span>
        </div>
        <div className="flex gap">
          <span className="muted small" data-testid="person-print-count">
            {printCount(person.prints.length)}
            {person.totalSeconds > 0 && ` · ${formatDuration(person.totalSeconds)}`}
          </span>
          <Badge kind={person.active ? "green" : "gray"}>
            {person.active ? T.voiceActive : T.voiceInactive}
          </Badge>
        </div>
      </div>

      <button type="button" className="audit-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="caret" aria-hidden>{open ? "▾" : "◂"}</span>
        {T.voicePrints}
        <span className="num"> ({person.prints.length})</span>
      </button>

      {open && (
        <div className="audit-stages" data-testid="person-prints">
          {person.prints.map((row) => (
            <div className="audit-stage" key={row.id}>
              <span className="num when">{formatDateTime(row.created_at)}</span>
              <span className="flex gap wrap">
                {/* Never hide where a biometric sample came from. */}
                {row.source_session_id ? (
                  <Link to={`/investigations/${row.source_session_id}?tab=speakers`} className="ltr">
                    {row.source_speaker_label ?? T.view}
                  </Link>
                ) : (
                  <span className="muted">{T.none}</span>
                )}
                <span className="muted">{formatDuration(row.sample_seconds)}</span>
                <Badge kind={row.is_active ? "green" : "gray"}>
                  {row.is_active ? T.voiceActive : T.voiceInactive}
                </Badge>
                {manage && (
                  <>
                    <button className="btn btn-sm" type="button" onClick={() => void setActive(row, !row.is_active)}>
                      {row.is_active ? T.voiceDeactivate : T.voiceReactivate}
                    </button>
                    <button className="btn btn-sm btn-danger" type="button" onClick={() => void removeOne(row)}>
                      {T.voiceDelete}
                    </button>
                  </>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {manage && (
        <div className="flex gap mt-8">
          <button className="btn btn-sm" type="button" onClick={() => setEditing(true)} data-testid="person-edit">
            {T.voiceEditPerson}
          </button>
          <button
            className="btn btn-sm btn-danger"
            type="button"
            onClick={() => void removeAll()}
            data-testid="person-delete-prints"
          >
            {T.voiceDeletePrints}
          </button>
        </div>
      )}
    </div>
  );
}

export function VoiceEnrollmentsPage() {
  const toast = useToast();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("people");
  const [rows, setRows] = useState<VoiceEnrollment[] | null>(null);
  const [candidates, setCandidates] = useState<EnrollmentCandidate[] | null>(null);
  const [q, setQ] = useState("");
  const [includeInactive, setIncludeInactive] = useState(true);
  const [rematching, setRematching] = useState(false);
  const [enrolling, setEnrolling] = useState<EnrollTarget | null>(null);
  const manage = can("voice.enroll");

  const load = useCallback(() => {
    void http
      .get<VoiceEnrollment[]>(`/voice-enrollments${qs({ q, include_inactive: includeInactive })}`)
      .then(setRows)
      .catch(() => setRows([]));
    if (manage) {
      void http
        .get<EnrollmentCandidate[]>("/voice-enrollments/candidates")
        .then(setCandidates)
        .catch(() => setCandidates([]));
    } else {
      setCandidates([]);
    }
  }, [q, includeInactive, manage]);

  useEffect(() => {
    const h = setTimeout(load, 200);
    return () => clearTimeout(h);
  }, [load]);

  const rematchAll = async () => {
    setRematching(true);
    try {
      const res = await http.post<{ sessions: number; scanned: number; suggested: number }>(
        "/voice-enrollments/rematch",
        {},
      );
      toast.success(
        res.suggested > 0 ? T.voiceRematchDone.replace("{n}", String(res.suggested)) : T.voiceRematchNone,
      );
      load();
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setRematching(false);
    }
  };

  const reactivate = (id: string) => {
    void http
      .patch(`/voice-enrollments/${id}`, { is_active: true })
      .then(() => {
        toast.success(T.voiceUpdated);
        load();
      })
      .catch((err) => toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic));
  };

  const people = useMemo(() => groupByPerson(rows ?? []), [rows]);

  // Two identities under one name is the fingerprint of the old duplicate-reference mistake.
  // Warn, never auto-merge: names are not identifiers.
  const duplicateNames = useMemo(() => {
    const byName = new Map<string, Person[]>();
    for (const p of people) byName.set(p.name, [...(byName.get(p.name) ?? []), p]);
    return [...byName.entries()].filter(([, group]) => group.length > 1);
  }, [people]);

  return (
    <>
      <div className="page-header">
        <h1>{T.voiceEnrollments}</h1>
        {can("voice.identify") && (
          <button
            className="btn"
            type="button"
            onClick={() => void rematchAll()}
            disabled={rematching}
            data-testid="voice-rematch-all"
          >
            <IconRefresh /> {rematching ? T.voiceRematchRunning : T.voiceRematchAll}
          </button>
        )}
      </div>

      <div className="audit-filters">
        <button
          type="button"
          className={`chip ${tab === "people" ? "active" : ""}`}
          onClick={() => setTab("people")}
          data-testid="tab-people"
        >
          {T.voiceTabPeople} <span className="num">({people.length})</span>
        </button>
        <button
          type="button"
          className={`chip ${tab === "pending" ? "active" : ""}`}
          onClick={() => setTab("pending")}
          data-testid="tab-pending"
        >
          {T.voiceTabPending} <span className="num">({candidates?.length ?? 0})</span>
        </button>
      </div>

      {enrolling && (
        <EnrollDialog target={enrolling} onClose={() => setEnrolling(null)} onEnrolled={() => load()} />
      )}

      {tab === "people" ? (
        <div className="card">
          <div className="toolbar">
            <div className="flex" style={{ position: "relative" }}>
              <input
                className="input search"
                placeholder={`${T.search}…`}
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
              <IconSearch
                style={{ position: "absolute", insetInlineEnd: 10, top: 9, color: "var(--muted)" }}
                width={16}
                height={16}
              />
            </div>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={includeInactive}
                onChange={(e) => setIncludeInactive(e.target.checked)}
              />
              {T.voiceInactive}
            </label>
          </div>

          {duplicateNames.length > 0 && (
            <div className="card-body">
              <Alert kind="warning">
                <div data-testid="duplicate-name-warning">⚠ {T.voiceDuplicateNames}</div>
                {duplicateNames.map(([name, group]) => (
                  <div key={name} className="mt-8">
                    <strong>{name}</strong>{" "}
                    <span className="ltr muted">
                      {group.map((g) => `${g.reference} (${g.prints.length})`).join(" · ")}
                    </span>
                  </div>
                ))}
                <div className="muted small mt-8">{T.voiceConsolidateHint}</div>
              </Alert>
            </div>
          )}

          {!rows ? (
            <Loading />
          ) : people.length === 0 ? (
            <div className="card-body muted center">{T.voiceNoPeople}</div>
          ) : (
            <div className="card-body">
              {people.map((p) => (
                <PersonRow key={p.identityId ?? p.prints[0].id} person={p} manage={manage} onChanged={load} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="card">
          {!candidates ? (
            <Loading />
          ) : candidates.length === 0 ? (
            <div className="card-body muted center">{T.voiceNoPending}</div>
          ) : (
            <div className="card-body">
              {candidates.map((c) => (
                <div
                  className="person-card"
                  key={c.speaker_id}
                  data-testid="candidate-row"
                  data-reference={c.person_reference}
                >
                  <div className="person-head">
                    <div>
                      {/* The canonical name is who this IS, so it leads. The session label is
                          shown beside it only when it differs - that is the case worth seeing,
                          and it is no longer possible to mistake one for the other. */}
                      <strong>{c.person_name}</strong>
                      <span className="ltr muted" style={{ marginInlineStart: 8 }}>{c.person_reference}</span>
                      {c.display_name && c.display_name !== c.person_name && (
                        <span className="muted small" style={{ marginInlineStart: 8 }}>
                          {c.display_name}
                        </span>
                      )}
                    </div>
                    <span className="muted small">
                      <Link to={`/investigations/${c.session_id}?tab=speakers`} className="ltr">
                        {c.session_number}
                      </Link>
                      {" · "}
                      <span className="ltr">{c.speaker_label}</span>
                      {c.sample_seconds ? ` · ${formatDuration(c.sample_seconds)}` : ""}
                    </span>
                  </div>
                  {c.enrollment_state === "enrolled_inactive" ? (
                    // Reactivate rather than create a second print of the same sample.
                    <div className="flex gap mt-8">
                      <span className="muted small">{T.voiceAlreadyEnrolled}</span>
                      <button
                        className="btn btn-sm"
                        type="button"
                        data-testid="candidate-reactivate"
                        onClick={() => c.inactive_enrollment_id && reactivate(c.inactive_enrollment_id)}
                      >
                        {T.voiceReactivate}
                      </button>
                    </div>
                  ) : (
                    <div className="mt-8">
                      <button
                        className="btn btn-sm btn-primary"
                        type="button"
                        data-testid="candidate-enroll"
                        onClick={() =>
                          setEnrolling({
                            sessionId: c.session_id,
                            speakerId: c.speaker_id,
                            // The registry name, never the session label: the label may
                            // carry a rank, and enrolment asserts the person's real name.
                            personName: c.person_name,
                            reference: c.person_reference,
                            sampleSeconds: c.sample_seconds,
                          })
                        }
                      >
                        <IconMic width={14} height={14} /> {T.voiceEnroll}
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
}
