import { useState } from "react";

import { ApiError, http } from "@/api/client";
import type { Speaker, SpeakerRole } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDuration, speakerColor } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Field, useToast } from "@/components/ui";
import { VoiceEnrollButton, VoiceSuggestion } from "./VoiceSuggestion";
import { IdentifySpeakerDialog } from "@/components/voice/IdentifySpeakerDialog";
import { SpeakerPicker } from "./SpeakerPicker";

const ROLES: SpeakerRole[] = ["INVESTIGATOR", "SUBJECT", "WITNESS", "OTHER", "UNKNOWN"];

function SpeakerForm({
  sessionId,
  speaker,
  onSaved,
  onReloadRequested,
}: {
  sessionId: string;
  speaker: Speaker;
  onSaved: (s: Speaker) => void;
  /** Identifying rewrites the speaker and the session server-side, so refetch rather
      than patch local state. */
  onReloadRequested: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [identifying, setIdentifying] = useState(false);
  const [role, setRole] = useState<SpeakerRole>(speaker.speaker_role);
  const [notes, setNotes] = useState(speaker.notes ?? "");
  const [busy, setBusy] = useState(false);
  const editable = can("speakers.assign");

  /* الصفة and ملاحظات are the ONLY things حفظ writes. Identity is established by اختيار الشخص
     and nothing else - which is what the old تعيين الاسم got wrong: it either labelled a
     speaker or created a canonical person depending on which chip had been clicked, and
     nothing on screen said which. */
  const dirty = role !== speaker.speaker_role || notes !== (speaker.notes ?? "");

  const save = async () => {
    setBusy(true);
    try {
      const updated = await http.patch<Speaker>(`/investigations/${sessionId}/speakers/${speaker.id}`, {
        speaker_role: role,
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
      {identifying && (
        <IdentifySpeakerDialog
          sessionId={sessionId}
          speaker={speaker}
          onClose={() => setIdentifying(false)}
          onIdentified={onReloadRequested}
        />
      )}
      <VoiceSuggestion
        sessionId={sessionId}
        speaker={speaker}
        /* No local name state to sync any more: the picker renders speaker.display_name, so
           updating the speaker is enough. */
        onDecided={(patch) => onSaved({ ...speaker, ...patch })}
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
        <Field label={T.speakerPerson}>
          {/* One control. Selecting a person IS identifying them - there is no separate
              "set the name" step that sometimes also created a canonical person. */}
          <SpeakerPicker
            sessionId={sessionId}
            speaker={speaker}
            onLinked={onReloadRequested}
            onAddNew={() => setIdentifying(true)}
            disabled={!editable || busy}
          />
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
<Field label={T.notes}>
          <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} disabled={!editable} maxLength={2000} />
        </Field>
      </div>
      {speaker.display_name && !speaker.identity_id && (
        <div className="muted small mt-8" data-testid="speaker-not-identified">
          {T.speakerNeedsIdentity}
        </div>
      )}
      {editable && (
        <div className="flex wrap">
          <button
            className="btn btn-primary btn-sm"
            disabled={busy || !dirty}
            onClick={() => void save()}
            type="button"
            data-testid="speaker-save"
          >
            {T.save}
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
  onChange,
  onReload,
}: {
  sessionId: string;
  speakers: Speaker[];
  onChange: (s: Speaker[]) => void;
  onReload?: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [rematching, setRematching] = useState(false);

  /* Voice matching runs once, when the agent submits its result. A voice enrolled after
     that would never reach this session, so the investigator can ask for a re-check.
     Confirmed and rejected speakers are left alone by the server. */
  const rematch = async () => {
    setRematching(true);
    try {
      const res = await http.post<{ scanned: number; suggested: number }>(
        `/investigations/${sessionId}/voice-rematch`,
        {},
      );
      toast.success(
        res.suggested > 0 ? T.voiceRematchDone.replace("{n}", String(res.suggested)) : T.voiceRematchNone,
      );
      onReload?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setRematching(false);
    }
  };

  const canRematch = can("voice.identify") && speakers.some((s) => s.has_voice_embedding);

  return (
    <div className="card">
      <div className="card-header">
        <h3>{T.speakers}</h3>
        <div className="flex gap">
          <span className="muted small">{speakers.length > 4 ? T.speakerLimitWarning : ""}</span>
          {canRematch && (
            <button
              className="btn btn-sm"
              type="button"
              onClick={rematch}
              disabled={rematching}
              title={T.voiceRematchHint}
              data-testid="voice-rematch"
            >
              {rematching ? T.voiceRematchRunning : T.voiceRematch}
            </button>
          )}
        </div>
      </div>
      <div className="card-body">
        {speakers.length === 0 && <div className="muted center">{T.noTranscript}</div>}
        {speakers.map((s) => (
          <SpeakerForm
            key={s.id}
            sessionId={sessionId}
            speaker={s}
            onSaved={(u) => onChange(speakers.map((x) => (x.id === u.id ? u : x)))}
            onReloadRequested={() => onReload?.()}
          />
        ))}
      </div>
    </div>
  );
}
