import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, http } from "@/api/client";
import type { AssignmentRole, Investigation, Profile, Subject } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { todayIso, nowTime } from "@/lib/format";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Field, Loading, useToast } from "@/components/ui";
import { IconPlus, IconX } from "@/components/Icons";

interface AssignmentRow {
  investigator_id: string;
  assignment_role: AssignmentRole;
}

const emptySubject = (): Subject => ({
  subject_name: "",
  reference_number: "",
  military_id: "",
  rank: "",
  unit: "",
  department: "",
  notes: "",
});

const clean = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);

export function InvestigationFormPage() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const toast = useToast();
  const { user } = useAuth();

  const [investigators, setInvestigators] = useState<Profile[]>([]);
  const [loaded, setLoaded] = useState(!isEdit);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [sessionNumber, setSessionNumber] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [sessionDate, setSessionDate] = useState(todayIso());
  const [startTime, setStartTime] = useState(nowTime());
  const [endTime, setEndTime] = useState("");
  const [notes, setNotes] = useState("");
  const [expectedSpeakers, setExpectedSpeakers] = useState(2);
  const [assignments, setAssignments] = useState<AssignmentRow[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([emptySubject()]);

  useEffect(() => {
    void http.get<Profile[]>("/investigators").then((list) => {
      setInvestigators(list);
      if (!isEdit && user?.profile) setAssignments([{ investigator_id: user.profile.id, assignment_role: "LEAD" }]);
    });
  }, [isEdit, user]);

  useEffect(() => {
    if (!id) return;
    void http.get<Investigation>(`/investigations/${id}`).then((s) => {
      setTitle(s.title);
      setSessionNumber(s.session_number);
      setDescription(s.description ?? "");
      setLocation(s.location ?? "");
      setSessionDate(s.session_date ?? "");
      setStartTime(s.start_time?.slice(0, 5) ?? "");
      setEndTime(s.end_time?.slice(0, 5) ?? "");
      setNotes(s.notes ?? "");
      setExpectedSpeakers(s.expected_speaker_count);
      setAssignments(s.investigators.map((i) => ({ investigator_id: i.id, assignment_role: i.assignment_role ?? "ASSISTANT" })));
      setSubjects(s.subjects.length ? s.subjects : [emptySubject()]);
      setLoaded(true);
    });
  }, [id]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const payload = {
      title: title.trim(),
      description: clean(description),
      location: clean(location),
      session_date: sessionDate || null,
      start_time: startTime || null,
      end_time: endTime || null,
      notes: clean(notes),
      expected_speaker_count: expectedSpeakers,
      investigators: assignments.filter((a) => a.investigator_id),
      subjects: subjects
        .map((s) => ({
          subject_name: clean(s.subject_name),
          reference_number: clean(s.reference_number),
          military_id: clean(s.military_id),
          rank: clean(s.rank),
          unit: clean(s.unit),
          department: clean(s.department),
          notes: clean(s.notes),
        }))
        .filter((s) => Object.values(s).some(Boolean)),
    };
    try {
      const saved = isEdit
        ? await http.put<Investigation>(`/investigations/${id}`, payload)
        : await http.post<Investigation>("/investigations", { ...payload, session_number: clean(sessionNumber) });
      toast.success(isEdit ? T.sessionUpdated : T.sessionCreated);
      navigate(`/investigations/${saved.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) return <Loading />;

  const updateSubject = (i: number, key: keyof Subject, value: string) =>
    setSubjects((prev) => prev.map((s, idx) => (idx === i ? { ...s, [key]: value } : s)));

  return (
    <>
      <div className="page-header">
        <h1>{isEdit ? T.edit + " — " + sessionNumber : T.newInvestigation}</h1>
      </div>
      <form onSubmit={submit} className="card">
        <div className="card-body">
          {error && (
            <div className="mb-16">
              <Alert kind="danger">{error}</Alert>
            </div>
          )}
          <div className="form-grid">
            <div className="section-title">{T.sessionInfo}</div>
            <Field label={T.title} required full>
              <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={300} />
            </Field>
            {!isEdit && (
              <Field label={T.sessionNumber} hint="يُولَّد تلقائياً عند تركه فارغاً">
                <input className="input mono" value={sessionNumber} onChange={(e) => setSessionNumber(e.target.value)} maxLength={64} dir="ltr" />
              </Field>
            )}
            <Field label={T.expectedSpeakers}>
              <input className="input" type="number" min={1} max={20} value={expectedSpeakers} onChange={(e) => setExpectedSpeakers(Number(e.target.value) || 1)} />
            </Field>
            {expectedSpeakers > 4 && (
              <div className="field full">
                <Alert kind="warning">{T.speakerLimitWarning}</Alert>
              </div>
            )}
            <Field label={T.description} full>
              <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={8000} />
            </Field>

            <div className="section-title">{T.investigatorsLabel}</div>
            <div className="field full">
              {assignments.map((a, i) => (
                <div className="flex mb-16" key={i}>
                  <select
                    className="select"
                    value={a.investigator_id}
                    onChange={(e) => setAssignments((prev) => prev.map((x, idx) => (idx === i ? { ...x, investigator_id: e.target.value } : x)))}
                    style={{ flex: 1 }}
                  >
                    <option value="">{T.selectInvestigator}</option>
                    {investigators.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.rank ? `${p.rank} ` : ""}
                        {p.full_name}
                        {p.military_id ? ` (${p.military_id})` : ""}
                      </option>
                    ))}
                  </select>
                  <select
                    className="select"
                    value={a.assignment_role}
                    onChange={(e) => setAssignments((prev) => prev.map((x, idx) => (idx === i ? { ...x, assignment_role: e.target.value as AssignmentRole } : x)))}
                    style={{ width: 180 }}
                  >
                    <option value="LEAD">{T.leadInvestigator}</option>
                    <option value="ASSISTANT">{T.assistantInvestigator}</option>
                  </select>
                  <button type="button" className="icon-btn" onClick={() => setAssignments((prev) => prev.filter((_, idx) => idx !== i))} aria-label={T.removeSubject}>
                    <IconX />
                  </button>
                </div>
              ))}
              <button type="button" className="btn btn-sm" onClick={() => setAssignments((prev) => [...prev, { investigator_id: "", assignment_role: "ASSISTANT" }])}>
                <IconPlus /> {T.addInvestigator}
              </button>
            </div>

            <div className="section-title">{T.subjectInfo}</div>
            {subjects.map((s, i) => (
              <div className="field full" key={i}>
                <div className="form-grid-3 form-grid" style={{ padding: 14, border: "1px solid var(--line-soft)", borderRadius: 8, position: "relative" }}>
                  <Field label={T.subjectName}>
                    <input className="input" value={s.subject_name ?? ""} onChange={(e) => updateSubject(i, "subject_name", e.target.value)} />
                  </Field>
                  <Field label={T.referenceNumber}>
                    <input className="input" value={s.reference_number ?? ""} onChange={(e) => updateSubject(i, "reference_number", e.target.value)} />
                  </Field>
                  <Field label={T.militaryId}>
                    <input className="input" value={s.military_id ?? ""} onChange={(e) => updateSubject(i, "military_id", e.target.value)} dir="ltr" />
                  </Field>
                  <Field label={T.rank}>
                    <input className="input" value={s.rank ?? ""} onChange={(e) => updateSubject(i, "rank", e.target.value)} />
                  </Field>
                  <Field label={T.unit}>
                    <input className="input" value={s.unit ?? ""} onChange={(e) => updateSubject(i, "unit", e.target.value)} />
                  </Field>
                  <Field label={T.department}>
                    <input className="input" value={s.department ?? ""} onChange={(e) => updateSubject(i, "department", e.target.value)} />
                  </Field>
                  <Field label={T.notes} full>
                    <textarea className="textarea" style={{ minHeight: 60 }} value={s.notes ?? ""} onChange={(e) => updateSubject(i, "notes", e.target.value)} />
                  </Field>
                  {subjects.length > 1 && (
                    <button type="button" className="icon-btn" style={{ position: "absolute", top: 6, insetInlineEnd: 6 }} onClick={() => setSubjects((prev) => prev.filter((_, idx) => idx !== i))} aria-label={T.removeSubject}>
                      <IconX />
                    </button>
                  )}
                </div>
              </div>
            ))}
            <div className="field full">
              <button type="button" className="btn btn-sm" onClick={() => setSubjects((prev) => [...prev, emptySubject()])}>
                <IconPlus /> {T.addSubject}
              </button>
            </div>

            <div className="section-title">{T.locationAndTime}</div>
            <Field label={T.location}>
              <input className="input" value={location} onChange={(e) => setLocation(e.target.value)} maxLength={300} />
            </Field>
            <Field label={T.sessionDate}>
              <input className="input" type="date" value={sessionDate} onChange={(e) => setSessionDate(e.target.value)} />
            </Field>
            <Field label={T.startTime}>
              <input className="input" type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
            </Field>
            <Field label={T.endTime}>
              <input className="input" type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
            </Field>

            <div className="section-title">{T.notes}</div>
            <Field label={T.notes} full>
              <textarea className="textarea" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={8000} />
            </Field>
          </div>
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={busy || !title.trim()}>
              {busy && <span className="spinner" />} {isEdit ? T.save : T.create}
            </button>
            <button className="btn" type="button" onClick={() => navigate(-1)}>
              {T.cancel}
            </button>
          </div>
        </div>
      </form>
    </>
  );
}
