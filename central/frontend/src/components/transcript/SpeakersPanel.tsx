import { useState } from "react";

import { ApiError, http } from "@/api/client";
import type { Speaker, SpeakerRole } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDuration, speakerColor } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Field, useToast } from "@/components/ui";
import { VoiceEnrollButton, VoiceSuggestion } from "./VoiceSuggestion";

const ROLES: SpeakerRole[] = ["INVESTIGATOR", "SUBJECT", "WITNESS", "OTHER", "UNKNOWN"];

/** A person already recorded in the session: an assigned investigator or a listed subject. */
export interface SpeakerCandidate {
  name: string;
  role: SpeakerRole;
  hint: string;
}

function SpeakerForm({
  sessionId,
  speaker,
  candidates,
  onSaved,
}: {
  sessionId: string;
  speaker: Speaker;
  candidates: SpeakerCandidate[];
  onSaved: (s: Speaker) => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [name, setName] = useState(speaker.display_name ?? "");
  const [role, setRole] = useState<SpeakerRole>(speaker.speaker_role);

  /* Picking someone already in the session fills the الصفة too, but never overrides a
     role the investigator has deliberately set. */
  const changeName = (value: string) => {
    setName(value);
    const match = candidates.find((c) => c.name === value);
    if (match && role === "UNKNOWN") setRole(match.role);
  };
  const [ref, setRef] = useState(speaker.reference_number ?? "");
  const [notes, setNotes] = useState(speaker.notes ?? "");
  const [busy, setBusy] = useState(false);
  const editable = can("speakers.assign");

  const save = async () => {
    setBusy(true);
    try {
      const updated = await http.patch<Speaker>(`/investigations/${sessionId}/speakers/${speaker.id}`, {
        display_name: name.trim() || null,
        speaker_role: role,
        reference_number: ref.trim() || null,
        notes: notes.trim() || null,
      });
      onSaved(updated);
      toast.success(T.speakerSaved);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="speaker-card" data-testid="speaker-card" data-label={speaker.speaker_label}>
      <VoiceSuggestion
        sessionId={sessionId}
        speaker={speaker}
        onDecided={(patch) => {
          if (patch.display_name !== undefined && patch.display_name !== null) setName(patch.display_name);
          onSaved({ ...speaker, ...patch });
        }}
      />
      <div className="head">
        <strong>
          <span className="sw" style={{ background: speakerColor(speaker.speaker_label) }} />
          <span className="ltr">{speaker.speaker_label}</span>
          {" → "}
          {speaker.display_name || (speaker.speaker_role !== "UNKNOWN" ? t(`role_${speaker.speaker_role}`) : T.unnamed)}
        </strong>
        <span className="meta">
          {T.segmentCount}: <span className="num">{speaker.segment_count}</span> — {T.speakingTime}: {formatDuration(speaker.total_seconds)}
        </span>
      </div>
      <div className="form-grid">
        <Field label={T.displayName} hint={candidates.length ? T.speakerCandidateHint : undefined}>
          <input
            className="input"
            list={`speaker-candidates-${speaker.id}`}
            value={name}
            onChange={(e) => changeName(e.target.value)}
            disabled={!editable}
            maxLength={200}
            data-testid="speaker-name"
          />
          {candidates.length > 0 && (
            <datalist id={`speaker-candidates-${speaker.id}`}>
              {candidates.map((c) => (
                <option key={`${c.role}-${c.name}`} value={c.name}>
                  {c.hint}
                </option>
              ))}
            </datalist>
          )}
        </Field>
        <Field label={T.speakerRole}>
          <select className="select" value={role} onChange={(e) => setRole(e.target.value as SpeakerRole)} disabled={!editable}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`role_${r}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={T.referenceNumber}>
          <input className="input" value={ref} onChange={(e) => setRef(e.target.value)} disabled={!editable} maxLength={100} />
        </Field>
        <Field label={T.notes}>
          <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} disabled={!editable} maxLength={2000} />
        </Field>
      </div>
      {editable && candidates.length > 0 && (
        <div className="flex wrap candidate-chips">
          {candidates.map((c) => (
            <button
              key={`${c.role}-${c.name}`}
              type="button"
              className={`radio-chip ${name === c.name ? "selected" : ""}`}
              onClick={() => changeName(c.name)}
              title={c.hint}
              data-testid="speaker-candidate"
            >
              {c.name}
              <span className="muted small">{c.hint}</span>
            </button>
          ))}
        </div>
      )}
      {editable && (
        <div className="flex wrap">
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void save()} type="button">
            {T.assignName}
          </button>
          <VoiceEnrollButton sessionId={sessionId} speaker={speaker} onEnrolled={() => onSaved({ ...speaker })} />
        </div>
      )}
    </div>
  );
}

export function SpeakersPanel({
  sessionId,
  speakers,
  candidates = [],
  onChange,
}: {
  sessionId: string;
  speakers: Speaker[];
  candidates?: SpeakerCandidate[];
  onChange: (s: Speaker[]) => void;
}) {
  return (
    <div className="card">
      <div className="card-header">
        <h3>{T.speakers}</h3>
        <span className="muted small">{speakers.length > 4 ? T.speakerLimitWarning : ""}</span>
      </div>
      <div className="card-body">
        {speakers.length === 0 && <div className="muted center">{T.noTranscript}</div>}
        {speakers.map((s) => (
          <SpeakerForm
            key={s.id}
            sessionId={sessionId}
            speaker={s}
            candidates={candidates}
            onSaved={(u) => onChange(speakers.map((x) => (x.id === u.id ? u : x)))}
          />
        ))}
      </div>
    </div>
  );
}
