/* Voice-based identity suggestion for one speaker.

   A suggestion is never applied on its own: the investigator presses تأكيد, which is the
   only path by which a voice comparison can reach display_name. تجاهل records the
   rejection (kept for the audit trail) without touching the name. */

import { useState } from "react";

import { ApiError, http } from "@/api/client";
import type { Speaker } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { T, errorMessage } from "@/lib/i18n";
import { EnrollDialog } from "@/components/voice/EnrollDialog";
import { Badge, useToast } from "@/components/ui";
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
  const { can } = useAuth();
  const [open, setOpen] = useState(false);

  if (!can("voice.enroll")) return null;

  // Rendered even without an embedding, but disabled with the reason in the tooltip: hiding
  // the control entirely left the investigator with no explanation of why enrolment was
  // unavailable for this speaker.
  // Gated on the canonical IDENTITY, not on display_name: a speaker can be identified while
  // its session-local label is blank, and the API refuses a print with no identity.
  const blocked = !speaker.identity_id || !speaker.has_voice_embedding;

  return (
    <>
      <button
        className="btn btn-sm"
        type="button"
        onClick={() => setOpen(true)}
        title={
          // Report the hard blocker first: a missing embedding needs the recording
          // reprocessed, while a missing identity is something they can fix right here.
          !speaker.has_voice_embedding
            ? T.voiceEnrollNeedsEmbedding
            : !speaker.identity_id
              ? T.voiceEnrollNeedsIdentity
              : T.voiceEnroll
        }
        disabled={blocked}
        data-testid="voice-enroll"
      >
        <IconMic width={14} height={14} /> {T.voiceEnroll}
      </button>
      {open && (
        <EnrollDialog
          target={{
            sessionId,
            speakerId: speaker.id,
            // The registry, and nothing else. The button is gated on identity_id, so these
            // are always present - and falling back to display_name / reference_number would
            // be dead code that quietly re-opens the leak it replaced, sending a
            // rank-decorated label as a canonical name. The server ignores both fields now
            // and reads the identity itself; they are sent for the confirmation screen.
            personName: speaker.identity_name ?? "",
            identityId: speaker.identity_id ?? "",
            model: speaker.suggested_model,
            sampleSeconds: speaker.total_seconds,
          }}
          onClose={() => setOpen(false)}
          onEnrolled={() => onEnrolled()}
        />
      )}
    </>
  );
}
