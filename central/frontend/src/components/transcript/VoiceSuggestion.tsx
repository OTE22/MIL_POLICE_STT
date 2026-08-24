/* Voice-based identity suggestion for one speaker.

   A suggestion is never applied on its own: the investigator presses تأكيد, which is the
   only path by which a voice comparison can reach display_name. تجاهل records the
   rejection (kept for the audit trail) without touching the name. */

import { useState } from "react";

import { ApiError, http } from "@/api/client";
import type { Speaker, VoiceEnrollment } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDuration } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Alert, Badge, Field, Modal, useToast } from "@/components/ui";
import { IconCheck, IconMic, IconX } from "@/components/Icons";

function scoreBadge(score: number | null) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const kind = score >= 0.8 ? "green" : score >= 0.7 ? "blue" : "amber";
  return (
    <Badge kind={kind}>
      {T.voiceMatchScore}: <span className="num">{pct}%</span>
    </Badge>
  );
}

/** تأكيد / تجاهل for a pending suggestion. */
export function VoiceSuggestion({
  sessionId,
  speaker,
  onDecided,
}: {
  sessionId: string;
  speaker: Speaker;
  onDecided: (s: Partial<Speaker>) => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [busy, setBusy] = useState(false);

  if (!can("voice.identify")) return null;

  if (speaker.identification_status === "CONFIRMED") {
    return (
      <div className="voice-row">
        <Badge kind="green">{T.ident_CONFIRMED}</Badge>
        {speaker.suggested_name && <span className="muted small">{speaker.suggested_name}</span>}
        {scoreBadge(speaker.suggested_score)}
      </div>
    );
  }
  if (speaker.identification_status === "REJECTED") {
    return (
      <div className="voice-row">
        <Badge kind="gray">{T.ident_REJECTED}</Badge>
        {speaker.suggested_name && <span className="muted small">{speaker.suggested_name}</span>}
      </div>
    );
  }
  if (speaker.identification_status !== "SUGGESTED" || !speaker.suggested_name) return null;

  const decide = async (accept: boolean) => {
    setBusy(true);
    try {
      const res = await http.post<{ identification_status: string; display_name: string | null }>(
        `/investigations/${sessionId}/speakers/${speaker.id}/identification`,
        { accept },
      );
      onDecided({
        identification_status: res.identification_status as Speaker["identification_status"],
        display_name: res.display_name,
      });
      toast.success(accept ? T.voiceConfirmed : T.voiceRejected);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="voice-suggestion" data-testid="voice-suggestion">
      <div className="flex between wrap">
        <div className="flex wrap">
          <IconMic width={16} height={16} />
          <strong>{T.voiceSuggestion}:</strong>
          <span data-testid="voice-suggested-name">{speaker.suggested_name}</span>
          {scoreBadge(speaker.suggested_score)}
        </div>
        <div className="flex">
          <button
            className="btn btn-success btn-sm"
            type="button"
            disabled={busy || !can("speakers.assign")}
            onClick={() => void decide(true)}
            data-testid="voice-confirm"
          >
            <IconCheck width={14} height={14} /> {T.voiceConfirm}
          </button>
          <button
            className="btn btn-sm"
            type="button"
            disabled={busy}
            onClick={() => void decide(false)}
            data-testid="voice-reject"
          >
            <IconX width={14} height={14} /> {T.voiceReject}
          </button>
        </div>
      </div>
      <div className="hint">{T.voiceSuggestionHint}</div>
    </div>
  );
}

/** Create a voice template from a speaker whose name is already established. */
export function VoiceEnrollButton({
  sessionId,
  speaker,
  onEnrolled,
}: {
  sessionId: string;
  speaker: Speaker;
  onEnrolled: () => void;
}) {
  const toast = useToast();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [personName, setPersonName] = useState(speaker.display_name ?? "");
  const [reference, setReference] = useState(speaker.reference_number ?? "");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!can("voice.enroll") || !speaker.has_voice_embedding) return null;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await http.post<VoiceEnrollment>(`/investigations/${sessionId}/speakers/${speaker.id}/enroll`, {
        person_name: personName.trim(),
        person_reference: reference.trim(),
        model: speaker.suggested_model || "nvidia/speakerverification_speakernet",
        provider: "nemo_speakernet",
        sample_seconds: speaker.total_seconds,
        consent_recorded: consent,
      });
      toast.success(T.voiceEnrolled);
      setOpen(false);
      onEnrolled();
    } catch (err) {
      setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button
        className="btn btn-sm"
        type="button"
        onClick={() => {
          setPersonName(speaker.display_name ?? "");
          setReference(speaker.reference_number ?? "");
          setConsent(false);
          setError(null);
          setOpen(true);
        }}
        title={speaker.display_name ? T.voiceEnroll : T.voiceEnrollNeedsName}
        disabled={!speaker.display_name}
        data-testid="voice-enroll"
      >
        <IconMic width={14} height={14} /> {T.voiceEnroll}
      </button>
      {open && (
        <Modal
          title={T.voiceEnrollTitle}
          onClose={() => setOpen(false)}
          footer={
            <>
              <button
                className="btn btn-primary"
                type="button"
                disabled={busy || !consent || !personName.trim() || !reference.trim()}
                onClick={() => void submit()}
                data-testid="voice-enroll-submit"
              >
                {T.voiceEnroll}
              </button>
              <button className="btn" type="button" onClick={() => setOpen(false)}>
                {T.cancel}
              </button>
            </>
          }
        >
          <p className="muted small mb-16">{T.voiceEnrollIntro}</p>
          {error && (
            <div className="mb-16">
              <Alert kind="danger">{error}</Alert>
            </div>
          )}
          <div className="form-grid" style={{ gridTemplateColumns: "1fr" }}>
            <Field label={T.voicePersonName} required>
              <input className="input" value={personName} onChange={(e) => setPersonName(e.target.value)} maxLength={200} />
            </Field>
            <Field label={T.voicePersonReference} required hint={T.voicePersonReferenceHint}>
              <input className="input" dir="ltr" value={reference} onChange={(e) => setReference(e.target.value)} maxLength={100} />
            </Field>
            <div className="field">
              <span className="muted small">
                {T.speakingTime}: {formatDuration(speaker.total_seconds)} — {t(`ident_${speaker.identification_status}`)}
              </span>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} data-testid="voice-consent" />
              {T.voiceConsent}
            </label>
            {!consent && <div className="error-text">{T.voiceConsentRequired}</div>}
          </div>
        </Modal>
      )}
    </>
  );
}
