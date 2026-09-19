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
import type {
  BiometricCheck,
  BiometricPrintCheck,
  BiometricPrintStatus,
  EnrollmentCandidate,
  VoiceEnrollment,
} from "@/api/types";
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
            disabled={busy || !name.trim()}
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
    </Modal>
  );
}

const BIO_STATUS: Record<BiometricPrintStatus, { label: () => string; kind: "green" | "blue" | "amber" | "gray" }> = {
  COHERENT: { label: () => T.voiceBioStatusCoherent, kind: "green" },
  NEAR_DUPLICATE: { label: () => T.voiceBioStatusNearDup, kind: "blue" },
  ISOLATED: { label: () => T.voiceBioStatusIsolated, kind: "amber" },
  SINGLE_PRINT: { label: () => T.voiceBioStatusSingle, kind: "gray" },
};

const BIO_OVERALL: Record<BiometricCheck["overall_status"], { label: () => string; kind: "green" | "amber" | "gray" }> = {
  COHERENT: { label: () => T.voiceBioOverallCoherent, kind: "green" },
  REVIEW_REQUIRED: { label: () => T.voiceBioOverallReview, kind: "amber" },
  SINGLE_PRINT: { label: () => T.voiceBioOverallSingle, kind: "gray" },
  NO_PRINTS: { label: () => T.voiceBioOverallNone, kind: "gray" },
};

function BioPrintLine({ row, showComponent }: { row: BiometricPrintCheck; showComponent: boolean }) {
  const status = BIO_STATUS[row.status];
  return (
    <div className="audit-stage" data-testid="bio-print-row">
      <span className="num when">{formatDateTime(row.created_at)}</span>
      <span className="flex gap wrap">
        {row.source_session_id ? (
          <Link to={`/investigations/${row.source_session_id}?tab=speakers`} className="ltr">
            {row.source_speaker_label ?? T.view}
          </Link>
        ) : (
          <span className="muted">{T.none}</span>
        )}
        {row.peer_similarity_max != null && (
          <span className="muted num" dir="ltr">
            {T.voiceBioMaxSim} {row.peer_similarity_max.toFixed(2)}
          </span>
        )}
        {showComponent && (
          <Badge kind="navy">{T.voiceBioComponent.replace("{n}", String(row.component_id))}</Badge>
        )}
        <Badge kind={status.kind}>{status.label()}</Badge>
      </span>
    </div>
  );
}

/** Result of the manual, advisory فحص البصمات الصوتية. Pure display: nothing was changed. */
function BiometricCheckModal({ result, onClose }: { result: BiometricCheck; onClose: () => void }) {
  const overall = BIO_OVERALL[result.overall_status];
  return (
    <Modal title={`${T.voiceBioCheckTitle} — ${result.person_name}`} onClose={onClose}>
      <div className="flex gap wrap" data-testid="bio-check-summary">
        <span>
          {T.voiceBioOverall}: <Badge kind={overall.kind}>{overall.label()}</Badge>
        </span>
        <span className="muted">
          {T.voiceBioActivePrints}: <span className="num">{result.total_active_prints}</span>
        </span>
        <span className="muted">
          {T.voiceBioComponents}: <span className="num" data-testid="bio-components">{result.number_of_components}</span>
        </span>
      </div>
      <div className="muted small mt-8" dir="rtl">
        {T.voiceBioThresholds}:{" "}
        <span className="num" dir="ltr">
          {result.coherence_threshold.toFixed(2)} / {result.near_duplicate_threshold.toFixed(2)}
        </span>
      </div>
      {result.overall_status === "REVIEW_REQUIRED" && (
        <div className="mt-8">
          <Alert kind="warning">{T.voiceBioReviewHint}</Alert>
        </div>
      )}
      {result.groups.map((group) => (
        <div className="mt-8" key={`${group.model}:${group.embedding_dim}`}>
          {result.groups.length > 1 && (
            <div className="muted small ltr">
              {group.model} · {group.embedding_dim}
            </div>
          )}
          <div className="audit-stages">
            {group.prints.map((row) => (
              <BioPrintLine key={row.enrollment_id} row={row} showComponent={group.component_count > 1} />
            ))}
          </div>
        </div>
      ))}
      <div className="muted small mt-8">{T.voiceBioAdvisory}</div>
    </Modal>
  );
}

function PersonRow({
  person,
  manage,
  canCheck,
  onChanged,
}: {
  person: Person;
  manage: boolean;
  canCheck: boolean;
  onChanged: () => void;
}) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<BiometricCheck | null>(null);

  // On demand only - the spec forbids computing coherence just to render the page.
  const runCheck = async () => {
    if (!person.identityId) return;
    setChecking(true);
    try {
      setCheckResult(await http.post<BiometricCheck>(`/voice-enrollments/people/${person.identityId}/biometric-check`, {}));
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setChecking(false);
    }
  };

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
    <div className="person-card" data-testid="person-row" data-identity-id={person.identityId}>
      {editing && <EditPersonModal person={person} onClose={() => setEditing(false)} onSaved={onChanged} />}
      {checkResult && <BiometricCheckModal result={checkResult} onClose={() => setCheckResult(null)} />}
      <div className="person-head">
        <div>
          <strong>{person.name}</strong>
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

      {(manage || canCheck) && (
        <div className="flex gap mt-8">
          {canCheck && (
            <button
              className="btn btn-sm"
              type="button"
              // Manual by design; needs a canonical identity and at least one active print.
              disabled={checking || !person.identityId || !person.active}
              onClick={() => void runCheck()}
              data-testid="person-bio-check"
            >
              {checking ? T.voiceBioCheckRunning : T.voiceBioCheck}
            </button>
          )}
          {manage && (
            <>
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
            </>
          )}
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
                      {group.map((g) => `${g.name} (${g.prints.length})`).join(" · ")}
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
                <PersonRow
                  key={p.identityId ?? p.prints[0].id}
                  person={p}
                  manage={manage}
                  canCheck={can("voice.identify")}
                  onChanged={load}
                />
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
                  data-identity-id={c.identity_id}
                >
                  <div className="person-head">
                    <div>
                      {/* The canonical name is who this IS, so it leads. The session label is
                          shown beside it only when it differs - that is the case worth seeing,
                          and it is no longer possible to mistake one for the other. */}
                      <strong>{c.person_name}</strong>
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
                            identityId: c.identity_id,
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
